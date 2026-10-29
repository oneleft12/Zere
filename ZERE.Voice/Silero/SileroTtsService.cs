using System.Diagnostics;
using System.Globalization;
using System.Net.Http;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using ZERE.Voice.Text;

namespace ZERE.Voice.Silero;

/// <summary>
/// TTS на Silero v5 (русский голос) — единственный движок проекта
/// (ChatTTS удалён): публичный контракт повторяет общий интерфейс TTS
/// (IsLoaded / CurrentVoice / Initialize / RefreshAvailability /
/// SynthesizeStreamAsync / SetInferenceParams / SetVoice / Dispose).
///
/// Silero v5_5_ru — русская модель с автоматическими ударениями и
/// омографами; синтез короткой фразы занимает 0.3–1.7 с на CPU.
///
/// Как устроено:
///  - Silero — Python-библиотека (torch-пакет .pt), поэтому тяжёлая часть в
///    сайдкаре tools/zere_silero_server.py;
///  - сайдкар поднимается uv с `--python 3.12 --with torch --with soundfile`;
///    дополнительно качается только файл модели (~145 МБ);
///  - ЛЕНИВАЯ загрузка: Initialize проверяет инструментарий, сервер и файл
///    модели поднимаются при первом синтезе;
///  - текст идёт ПОПРЕДЛОЖЕННО: первое предложение
///    играет, пока следующее ещё синтезируется;
///  - сайдкар отдаёт PCM s16le моно 24 кГц, клиент заворачивает его в WAV —
///    дальше обычный тракт: DSP-обработка и воспроизведение.
///
/// Ограничения: темп речи не настраивается (у Silero v5 нет параметра скорости),
/// веса — CC-NC-BY: для личного использования ок, для
/// коммерческого релиза это блокер (docs/TTS_SILERO.md).
/// </summary>
public sealed class SileroTtsService : IDisposable
{
    /// <summary>Инструментарий найден — движок доступен (модель ещё не в памяти).</summary>
    public bool IsLoaded { get; private set; }

    /// <summary>Что именно мешает работе движка (для панели/логов).</summary>
    public string UnavailableReason { get; private set; } = "";

    public int SampleRate { get; private set; } = DefaultSampleRate;

    public string CurrentVoice => _currentVoice;

    private const string LogPrefix = "[Silero]";
    private const int DefaultSampleRate = 24000;
    private const int Port = 8473;
    private const int MaxStartAttempts = 2;
    private const string DefaultVoice = "baya";

    /// <summary>
    /// Первый запуск включает скачивание модели (~145 МБ) и подъём torch —
    /// это может занять минуты, поэтому таймаут увеличен до 10 минут.
    /// </summary>
    private static readonly TimeSpan StartTimeout = TimeSpan.FromMinutes(10);

    /// <summary>Именованные голоса v5_5_ru.</summary>
    private static readonly string[] BuiltinVoices =
    [
        "baya", "xenia", "kseniya", "aidar", "eugene"
    ];

    private readonly string _root;
    private readonly string _outputDir;
    private readonly HttpClient _http;
    private readonly SemaphoreSlim _serverGate = new(1, 1);
    private readonly SemaphoreSlim _synthGate = new(1, 1);

    private Process? _process;
    private string _baseUrl = $"http://127.0.0.1:{Port}";
    private string _currentVoice = DefaultVoice;
    private float _sentenceSilence = 0.2f;
    private int _startAttempts;
    private int _fileSeq;
    private bool _serverReady;
    private bool _startFailed;

    public SileroTtsService()
    {
        // Как и в PocketTtsService:
        // bin/Debug/net10.0/ → 4 уровня вверх → корень решения.
        _root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        _outputDir = Path.Combine(_root, "ZERE.Voice", "Silero");

        _http = new HttpClient { Timeout = TimeSpan.FromMinutes(15) };
    }

    /// <summary>
    /// Проверяет инструментарий (uv + сервер) и фиксирует голос. Модель НЕ
    /// загружается — это делает первый SynthesizeStreamAsync (ленивая загрузка).
    /// </summary>
    public bool Initialize(string? voiceName = null)
    {
        if (!string.IsNullOrWhiteSpace(voiceName))
            _currentVoice = SanitizeVoice(voiceName);

        IsLoaded = ProbeToolchain(out var reason);

        if (!IsLoaded)
        {
            UnavailableReason = reason;
            Console.WriteLine($"{LogPrefix} Инструментарий не найден ({reason}) — Silero недоступен.");
            return false;
        }

        UnavailableReason = "";
        Console.WriteLine(
            $"{LogPrefix} Доступен (русский голос; модель ~145 МБ качается при первом синтезе). " +
            $"Голос: {_currentVoice}");

        CleanupOldOutputs();
        return true;
    }

    /// <summary>
    /// Перепроверяет инструментарий без побочных эффектов (два File.Exists):
    /// uv/сайдкар могут появиться при работающем ZERE, и тогда озвучка
    /// заработает без перезапуска.
    /// </summary>
    public bool RefreshAvailability()
    {
        if (IsLoaded)
            return true;

        IsLoaded = ProbeToolchain(out var reason);
        UnavailableReason = reason;

        if (IsLoaded)
        {
            Console.WriteLine($"{LogPrefix} Движок стал доступен. Голос: {_currentVoice}");
            CleanupOldOutputs();
        }

        return IsLoaded;
    }

    /// <summary>Инструментарий на месте? reason — что именно отсутствует.</summary>
    private bool ProbeToolchain(out string reason)
    {
        var uvExe = Path.Combine(_root, "tools", "uv.exe");
        var script = Path.Combine(_root, "tools", "zere_silero_server.py");

        if (!File.Exists(uvExe) || !File.Exists(script))
        {
            reason = "нет tools/uv.exe или tools/zere_silero_server.py";
            return false;
        }

        reason = "";
        return true;
    }

    /// <summary>
    /// Синтезирует текст ПОПРЕДЛОЖЕННО и отдаёт путь к WAV каждого предложения,
    /// как только оно готово (общий контракт TTS).
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
    /// Пауза после предложения. `lengthScale` (темп) принимается ради общего
    /// контракта TTS, но у Silero v5 нет параметра скорости — он
    /// игнорируется (в панели это видно как «скорость речи фиксирована»).
    /// </summary>
    public void SetInferenceParams(float lengthScale, float sentenceSilence)
    {
        _ = lengthScale;
        _sentenceSilence = Math.Clamp(sentenceSilence, 0f, 2f);
    }

    /// <summary>Смена голоса: модель не перезагружается, голос идёт в запрос.</summary>
    public void SetVoice(string voiceName)
    {
        if (!string.IsNullOrWhiteSpace(voiceName))
            _currentVoice = SanitizeVoice(voiceName);
    }

    /// <summary>Доступные голоса Silero.</summary>
    public List<string> GetAvailableVoices() => BuiltinVoices.ToList();

    /// <summary>
    /// Неизвестное имя голоса → дефолт: так старый профиль из конфига
    /// («zere-standard») не роняет русский движок.
    /// </summary>
    private static string SanitizeVoice(string voiceName) =>
        BuiltinVoices.Contains(voiceName, StringComparer.Ordinal) ? voiceName : DefaultVoice;

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
                $"{LogPrefix} Запускаю сервер (первый запуск — модель ~145 МБ и torch)...");

            if (!await WaitUntilReadyAsync(StartTimeout, ct).ConfigureAwait(false))
            {
                StopProcess();
                FailStart();
                return false;
            }

            Console.WriteLine(
                $"{LogPrefix} Готов. Голос: {_currentVoice}, sample_rate={SampleRate}");

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
        // до перезапуска ZERE.
        _startFailed = true;
        IsLoaded = false;
        Console.WriteLine(
            $"{LogPrefix} TTS выключен до перезапуска ZERE — ответы пойдут текстом.");
    }

    private void StartServer()
    {
        var uvExe = Path.Combine(_root, "tools", "uv.exe");
        var script = Path.Combine(_root, "tools", "zere_silero_server.py");

        // torch ставится в кэш uv. num2words не
        // нужен: у v5_5_ru в наборе символов нет ни цифр, ни латиницы, поэтому
        // текст раскрывает сам сайдкар — `zere/voice/silero/silero_text.py`
        // (числа по-русски, латиница практической транскрипцией).
        var args = new StringBuilder();
        args.Append("run --python 3.12");
        args.Append(" --with torch");
        args.Append(" --with soundfile");
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
            ?? throw new IOException("Не удалось запустить сервер Silero.");

        // Логи сервера (в т.ч. прогресс скачивания модели) — в консоль ZERE.
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
        // speed не отправляем: Silero v5 не умеет менять темп (сайдкар его
        // принимает только ради общего контракта TTS-сервера).
        var payload = JsonSerializer.Serialize(new
        {
            text = sentence,
            voice = _currentVoice,
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
