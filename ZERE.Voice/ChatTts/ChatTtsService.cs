using System.Diagnostics;
using System.Globalization;
using System.Net.Http;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using ZERE.Voice.Text;

namespace ZERE.Voice.ChatTts;

/// <summary>
/// TTS на ChatTTS (2Noise/ChatTTS) — замена Piper БЕЗ изменения архитектуры:
/// публичный контракт повторяет PiperService, поэтому VoiceManager и остальные
/// модули правок не заметили (IsLoaded / CurrentVoice / Initialize /
/// SynthesizeStreamAsync / SetInferenceParams / SetVoice / Dispose).
///
/// Как это устроено:
///  - ChatTTS — Python-библиотека, поэтому тяжёлая часть живёт в сайдкаре
///    tools/zere_chattts_server.py (тот же приём, что у PocketTTS);
///  - сайдкар поднимается uv с `--python 3.12`: это проверенная версия стека
///    ChatTTS (torch/torchaudio/numba), uv приносит её сам и не трогает
///    системный Python;
///  - ЛЕНИВАЯ загрузка в двух слоях: Initialize только проверяет инструментарий
///    (ничего не грузит), сервер и веса поднимаются при первом синтезе;
///  - текст идёт ПОПРЕДЛОЖЕННО (как у Piper): первое предложение играет, пока
///    следующее ещё синтезируется;
///  - сайдкар отдаёт PCM s16le моно 24 кГц, клиент заворачивает его в WAV —
///    дальше обычный тракт: DSP-обработка и воспроизведение.
/// </summary>
public sealed class ChatTtsService : IDisposable
{
    /// <summary>Инструментарий найден — движок доступен (модель ещё не в памяти).</summary>
    public bool IsLoaded { get; private set; }

    /// <summary>Что именно мешает работе движка (для панели/логов).</summary>
    public string UnavailableReason { get; private set; } = "";

    public int SampleRate { get; private set; } = DefaultSampleRate;

    public string CurrentVoice => _currentVoice;

    private const string LogPrefix = "[ChatTTS]";
    private const int DefaultSampleRate = 24000;
    private const int Port = 8472;
    private const int MaxStartAttempts = 2;

    /// <summary>Первая загрузка весов ChatTTS долгая (скачивание + CPU/GPU init).</summary>
    private static readonly TimeSpan StartTimeout = TimeSpan.FromMinutes(10);

    private static readonly string[] BuiltinVoices =
    [
        "zere-standard", "zere-warm", "zere-strict",
        "zere-ironic", "zere-business", "zere-casual"
    ];

    private readonly string _root;
    private readonly string _outputDir;
    private readonly HttpClient _http;
    private readonly SemaphoreSlim _serverGate = new(1, 1);
    private readonly SemaphoreSlim _synthGate = new(1, 1);

    private Process? _process;
    private string _baseUrl = $"http://127.0.0.1:{Port}";
    private string _currentVoice = "zere-standard";
    private float _lengthScale = 1.15f;
    private float _sentenceSilence = 0.2f;
    private int _startAttempts;
    private int _fileSeq;
    private bool _serverReady;
    private bool _startFailed;

    public ChatTtsService()
    {
        // Как и в PiperService/PocketTtsService:
        // bin/Debug/net10.0/ → 4 уровня вверх → корень решения.
        _root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        _outputDir = Path.Combine(_root, "ZERE.Voice", "ChatTts");

        // Синтез длинной фразы на CPU/первой загрузке может идти минутами.
        _http = new HttpClient { Timeout = TimeSpan.FromMinutes(15) };
    }

    /// <summary>
    /// Проверяет инструментарий (uv + сервер) и фиксирует профиль голоса.
    /// Модель НЕ загружается — это делает первый SynthesizeStreamAsync
    /// (ленивая загрузка: старт ZERE не платит временем и памятью за TTS).
    /// </summary>
    public bool Initialize(string? voiceName = null)
    {
        if (!string.IsNullOrWhiteSpace(voiceName))
            _currentVoice = voiceName;

        IsLoaded = ProbeToolchain(out var reason);

        if (!IsLoaded)
        {
            UnavailableReason = reason;
            Console.WriteLine($"{LogPrefix} Инструментарий не найден ({reason}) — ChatTTS недоступен.");
            return false;
        }

        UnavailableReason = "";
        Console.WriteLine(
            $"{LogPrefix} Доступен (ленивая загрузка модели при первом синтезе). " +
            $"Профиль голоса: {_currentVoice}");

        CleanupOldOutputs();
        return true;
    }

    /// <summary>
    /// Перепроверяет инструментарий без побочных эффектов (два File.Exists).
    ///
    /// Нужно, потому что uv/сайдкар могут появиться при работающем ZERE
    /// (например, их поставил установщик): панель до этого отвечала 503, а после
    /// перепроверки озвучка работает без перезапуска приложения.
    /// </summary>
    public bool RefreshAvailability()
    {
        if (IsLoaded)
            return true;

        IsLoaded = ProbeToolchain(out var reason);
        UnavailableReason = reason;

        if (IsLoaded)
        {
            Console.WriteLine(
                $"{LogPrefix} Движок стал доступен. Профиль голоса: {_currentVoice}");
            CleanupOldOutputs();
        }

        return IsLoaded;
    }

    /// <summary>Инструментарий на месте? reason — что именно отсутствует.</summary>
    private bool ProbeToolchain(out string reason)
    {
        var uvExe = Path.Combine(_root, "tools", "uv.exe");
        var script = Path.Combine(_root, "tools", "zere_chattts_server.py");

        if (!File.Exists(uvExe) || !File.Exists(script))
        {
            reason = "нет tools/uv.exe или tools/zere_chattts_server.py";
            return false;
        }

        reason = "";
        return true;
    }

    /// <summary>
    /// Синтезирует текст ПОПРЕДЛОЖЕННО и отдаёт путь к WAV каждого предложения,
    /// как только оно готово (контракт PiperService, включая порядок отмены:
    /// отмена проверяется только на границе предложений).
    /// </summary>
    public async IAsyncEnumerable<string> SynthesizeStreamAsync(
        string text,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        text = SpeechText.Clean(text);

        if (string.IsNullOrWhiteSpace(text) || !IsLoaded)
            yield break;

        // Сайдкар поднимается здесь и только здесь (первый синтез) — лениво.
        if (!await EnsureServerAsync(ct).ConfigureAwait(false))
            yield break;

        var sentences = SpeechText.SplitSentences(text);

        await _synthGate.WaitAsync(ct).ConfigureAwait(false);

        try
        {
            foreach (var sentence in sentences)
            {
                if (ct.IsCancellationRequested)
                    yield break;

                var file = await SynthesizeSentenceAsync(sentence, ct).ConfigureAwait(false);

                yield return file;
            }
        }
        finally
        {
            _synthGate.Release();
        }
    }

    /// <summary>
    /// Темп речи и пауза после предложения. У ChatTTS параметры приходят на
    /// каждый запрос, поэтому перезапуск процесса (как было у Piper) не нужен.
    /// </summary>
    public void SetInferenceParams(float lengthScale, float sentenceSilence)
    {
        _lengthScale = Math.Clamp(lengthScale, 0.5f, 3.0f);
        _sentenceSilence = Math.Clamp(sentenceSilence, 0f, 2f);
    }

    /// <summary>Смена профиля голоса: модель не перезагружается, профиль идёт в запрос.</summary>
    public void SetVoice(string voiceName)
    {
        if (!string.IsNullOrWhiteSpace(voiceName))
            _currentVoice = voiceName;
    }

    /// <summary>Доступные профили голоса (у ChatTTS нет именованных голосов).</summary>
    public List<string> GetAvailableVoices() => BuiltinVoices.ToList();

    // ─── Сайдкар ───────────────────────────────────────────

    private async Task<bool> EnsureServerAsync(CancellationToken ct)
    {
        if (_serverReady)
            return true;

        if (_startFailed)
            return false;

        await _serverGate.WaitAsync(ct).ConfigureAwait(false);

        try
        {
            if (_serverReady)
                return true;

            if (_startFailed)
                return false;

            // Сервер мог остаться от прошлого запуска ZERE.
            if (await ProbeReadyAsync(ct).ConfigureAwait(false))
            {
                _serverReady = true;
                Console.WriteLine($"{LogPrefix} Сервер уже запущен — подключаюсь.");
                return true;
            }

            _startAttempts++;

            try
            {
                StartServer();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"{LogPrefix} Не удалось запустить сервер: {ex.Message}");
                FailStart();
                return false;
            }

            Console.WriteLine(
                $"{LogPrefix} Запускаю сервер (первый запуск — скачивание весов ChatTTS)...");

            if (!await WaitUntilReadyAsync(StartTimeout, ct).ConfigureAwait(false))
            {
                StopProcess();
                FailStart();
                return false;
            }

            Console.WriteLine(
                $"{LogPrefix} Готов. Профиль: {_currentVoice}, sample_rate={SampleRate}");

            _serverReady = true;
            return true;
        }
        finally
        {
            _serverGate.Release();
        }
    }

    private void FailStart()
    {
        if (_startAttempts < MaxStartAttempts)
            return;

        // Две неудачи подряд — повторять бессмысленно: озвучка уходит в текст
        // до перезапуска ZERE (тот же исход, что у Piper без piper.exe).
        _startFailed = true;
        IsLoaded = false;
        Console.WriteLine(
            $"{LogPrefix} TTS выключен до перезапуска ZERE — ответы пойдут текстом.");
    }

    private void StartServer()
    {
        var uvExe = Path.Combine(_root, "tools", "uv.exe");
        var script = Path.Combine(_root, "tools", "zere_chattts_server.py");

        // --python 3.12: проверенная версия стека ChatTTS (torch/torchaudio/
        // numba); uv приносит нужный интерпретатор сам, системный не трогает.
        var args = new StringBuilder();
        args.Append("run --python 3.12");
        args.Append(" --with ChatTTS");
        args.Append(" --with soundfile");
        args.Append(" --with num2words");           // раскрытие цифр в слова
        args.Append(" python \"").Append(script).Append('"');
        args.Append(" --port ").Append(Port.ToString(CultureInfo.InvariantCulture));
        args.Append(" --voice \"").Append(_currentVoice).Append('"');

        var psi = new ProcessStartInfo
        {
            FileName = uvExe,
            Arguments = args.ToString(),
            UseShellExecute = false,
            RedirectStandardInput = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = _root
        };

        // Логи сайдкара на русском: Python пишет UTF-8, читаем тоже в UTF-8.
        psi.Environment["PYTHONUTF8"] = "1";
        psi.StandardOutputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        psi.StandardErrorEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

        var process = Process.Start(psi)
            ?? throw new IOException("Не удалось запустить сервер ChatTTS.");

        // Логи сервера (в т.ч. прогресс скачивания весов) — в консоль ZERE.
        PipeToConsole(process.StandardOutput);
        PipeToConsole(process.StandardError);

        process.EnableRaisingEvents = true;
        process.Exited += (_, _) =>
        {
            if (_serverReady)
                Console.WriteLine($"{LogPrefix} ⚠ Сервер неожиданно завершился — поднимем при следующей реплике.");

            // Следующая реплика поднимет сервер заново (без «навсегда»).
            _serverReady = false;
        };

        _process = process;
    }

    private static void PipeToConsole(StreamReader reader)
    {
        _ = Task.Run(async () =>
        {
            try
            {
                string? line;

                while ((line = await reader.ReadLineAsync().ConfigureAwait(false)) != null)
                {
                    if (!string.IsNullOrWhiteSpace(line))
                        Console.WriteLine(line);
                }
            }
            catch { /* процесс завершён */ }
        });
    }

    private async Task<bool> ProbeReadyAsync(CancellationToken ct)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(2));

            using var response = await _http.GetAsync($"{_baseUrl}/health", cts.Token)
                .ConfigureAwait(false);

            if (!response.IsSuccessStatusCode)
                return false;

            var json = await response.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false);

            return ApplyHealth(json) && IsHealthReady(json);
        }
        catch
        {
            return false;
        }
    }

    private async Task<bool> WaitUntilReadyAsync(TimeSpan timeout, CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        var lastLog = DateTime.UtcNow;

        while (DateTime.UtcNow < deadline)
        {
            if (ct.IsCancellationRequested)
                return false;

            if (_process is { HasExited: true })
            {
                Console.WriteLine(
                    $"{LogPrefix} Сервер завершился (код {_process.ExitCode}) — см. лог выше.");
                return false;
            }

            try
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                cts.CancelAfter(TimeSpan.FromSeconds(5));

                using var response = await _http.GetAsync($"{_baseUrl}/health", cts.Token)
                    .ConfigureAwait(false);

                if (response.IsSuccessStatusCode)
                {
                    var json = await response.Content.ReadAsStringAsync(cts.Token)
                        .ConfigureAwait(false);

                    ApplyHealth(json);

                    if (IsHealthReady(json))
                        return true;

                    if (HealthFailed(json))
                        return false;
                }
            }
            catch
            {
                // Сервер ещё поднимается — это нормально
            }

            if ((DateTime.UtcNow - lastLog).TotalSeconds > 10)
            {
                Console.WriteLine($"{LogPrefix} …всё ещё загружаю (см. лог выше)");
                lastLog = DateTime.UtcNow;
            }

            await Task.Delay(500, ct).ConfigureAwait(false);
        }

        Console.WriteLine(
            $"{LogPrefix} Сервер не стал ready за {timeout.TotalMinutes:0} мин.");
        return false;
    }

    /// <summary>Разбирает /health: частота дискретизации синтеза (24 кГц).</summary>
    private bool ApplyHealth(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;

            if (root.TryGetProperty("sample_rate", out var rate) && rate.TryGetInt32(out var value) && value > 0)
                SampleRate = value;

            return true;
        }
        catch
        {
            return false;
        }
    }

    private static bool IsHealthReady(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);

            return document.RootElement.TryGetProperty("status", out var status) &&
                   status.GetString() == "ready";
        }
        catch
        {
            return false;
        }
    }

    private static bool HealthFailed(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);

            if (!document.RootElement.TryGetProperty("status", out var status) ||
                status.GetString() != "error")
                return false;

            var detail = document.RootElement.TryGetProperty("detail", out var d)
                ? d.GetString()
                : null;

            Console.WriteLine($"{LogPrefix} Сервер сообщил об ошибке: {detail}");
            return true;
        }
        catch
        {
            return false;
        }
    }

    private void StopProcess()
    {
        _serverReady = false;

        var process = _process;
        _process = null;

        if (process == null)
            return;

        try
        {
            if (!process.HasExited)
                process.Kill(entireProcessTree: true);
        }
        catch { /* уже завершён */ }
        finally
        {
            try { process.Dispose(); } catch { }
        }
    }

    // ─── Синтез предложения ────────────────────────────────

    private async Task<string> SynthesizeSentenceAsync(string sentence, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(new
        {
            text = sentence,
            voice = _currentVoice,
            speed = _lengthScale,
            silence = _sentenceSilence
        });

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, _baseUrl + "/tts")
            {
                Content = new StringContent(payload, Encoding.UTF8, "application/json")
            };

            // ResponseHeadersRead — КРИТИЧНО: без него HttpClient буферизует
            // ответ и потоковый PCM теряет смысл.
            using var response = await _http
                .SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct)
                .ConfigureAwait(false);

            response.EnsureSuccessStatusCode();

            if (response.Headers.TryGetValues("X-Sample-Rate", out var rates) &&
                int.TryParse(rates.FirstOrDefault(), NumberStyles.Integer,
                    CultureInfo.InvariantCulture, out var rate) && rate > 0)
            {
                SampleRate = rate;
            }

            using var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);

            using var pcm = new MemoryStream();
            await stream.CopyToAsync(pcm, ct).ConfigureAwait(false);

            return SaveWav(pcm.ToArray());
        }
        catch
        {
            // Сервер мог умереть: следующая реплика поднимет его заново.
            _serverReady = false;
            throw;
        }
    }

    /// <summary>
    /// Заворачивает PCM s16le моно в полноценный WAV: дальше файл идёт по
    /// обычному тракту (DSP-обработка под частоту устройства + воспроизведение).
    /// </summary>
    private string SaveWav(byte[] pcm)
    {
        Directory.CreateDirectory(_outputDir);

        var path = Path.Combine(
            _outputDir,
            $"output_{DateTime.Now:yyyyMMdd_HHmmss}_{Interlocked.Increment(ref _fileSeq)}.wav");

        using var file = new FileStream(path, FileMode.Create, FileAccess.Write);
        using var writer = new BinaryWriter(file);

        var rate = SampleRate;

        writer.Write(Encoding.ASCII.GetBytes("RIFF"));
        writer.Write(36 + pcm.Length);
        writer.Write(Encoding.ASCII.GetBytes("WAVE"));

        writer.Write(Encoding.ASCII.GetBytes("fmt "));
        writer.Write(16);                 // размер fmt-чанка
        writer.Write((short)1);           // PCM
        writer.Write((short)1);           // моно
        writer.Write(rate);               // частота
        writer.Write(rate * 2);           // байт/с = rate * каналы * 2
        writer.Write((short)2);           // выравнивание блока
        writer.Write((short)16);          // бит на сэмпл

        writer.Write(Encoding.ASCII.GetBytes("data"));
        writer.Write(pcm.Length);
        writer.Write(pcm);

        return path;
    }

    private void CleanupOldOutputs()
    {
        try
        {
            if (!Directory.Exists(_outputDir))
                return;

            var cutoff = DateTime.Now.AddHours(-1);

            foreach (var path in Directory.GetFiles(_outputDir, "output_*.wav"))
            {
                try
                {
                    if (File.GetLastWriteTime(path) < cutoff)
                        File.Delete(path);
                }
                catch
                {
                    // Ignore individual file deletion failures during cleanup
                }
            }
        }
        catch
        {
            // Ignore cleanup failures — not critical
        }
    }

    public void Dispose()
    {
        StopProcess();

        try { _http.Dispose(); } catch { }
        try { _serverGate.Dispose(); } catch { }
        try { _synthGate.Dispose(); } catch { }

        GC.SuppressFinalize(this);
    }
}
