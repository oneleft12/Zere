using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using ZERE.Voice.Text;

namespace ZERE.Voice.Pocket;

/// <summary>
/// TTS с клонированием голоса (Этап 2): персистентный HTTP-сервер
/// xVibePocketTTS (tools/zere_tts_server.py поверх uv, работает на CPU).
///
/// Ключевые свойства:
///  - сервер стартует один раз при Initialize; веса (~458 МБ) скачиваются
///    при первом запуске и кэшируются;
///  - POST /tts отдаёт PCM-поток (s16le) chunk'ами ПО МЕРЕ синтеза —
///    через StreamPlayer первый звук не ждёт окончания генерации (~200–500 мс);
///  - референс пользователя (голос) кодируется в .safetensors один раз
///    и кэшируется на диске (tools/voice_cache);
///  - при любой ошибке инициализации вызывающий код откатывается на Piper.
/// </summary>
public sealed class PocketTtsService : IDisposable
{
    public bool IsAvailable { get; private set; }
    public int SampleRate { get; private set; } = 24000;
    public string VoiceName { get; private set; } = "";

    private readonly string _root;
    private readonly HttpClient _http;
    private Process? _process;
    private bool _ownsProcess;
    private string _baseUrl = "";

    // Параметры последнего запуска — для фонового восстановления (анализ F2).
    private string _uvExe = "";
    private string _script = "";
    private string _project = "";
    private string _voiceReference = "";
    private int _port;

    private System.Threading.Timer? _healthTimer;
    private int _recovering;

    public PocketTtsService()
    {
        // Как и в PiperService: bin/Debug/net10.0/ → 4 уровня вверх → корень решения.
        _root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        _http = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };
    }

    /// <summary>
    /// Поднимает (или подключается к уже запущенному) серверу TTS.
    /// voiceReferencePath — WAV с образцом голоса пользователя (пусто = встроенный голос).
    /// </summary>
    public bool Initialize(string voiceReferencePath = "", int port = 8471)
    {
        var uvExe = Path.Combine(_root, "tools", "uv.exe");
        var script = Path.Combine(_root, "tools", "zere_tts_server.py");
        var project = Path.Combine(_root, "tools", "xVibePocketTTS");

        if (!File.Exists(uvExe) || !File.Exists(script) || !Directory.Exists(project))
        {
            Console.WriteLine("[Pocket] Инструментарий не найден " +
                              "(tools/uv.exe, tools/xVibePocketTTS) — клонирование недоступно.");
            return false;
        }

        // Запоминаем параметры для фонового восстановления (анализ F2).
        _uvExe = uvExe;
        _script = script;
        _project = project;
        _voiceReference = voiceReferencePath;
        _port = port;

        _baseUrl = $"http://127.0.0.1:{port}";

        try
        {
            // Сервер мог остаться от прошлого запуска — тогда просто подключаемся.
            if (ProbeReady())
            {
                Console.WriteLine("[Pocket] Сервер TTS уже запущен — подключаюсь.");
                _ownsProcess = false;
                IsAvailable = true;
                StartHealthMonitor();
                Console.WriteLine($"[Pocket] Готов. Голос: {VoiceName}, sample_rate={SampleRate}");
                return true;
            }

            StartServer(uvExe, script, project, voiceReferencePath, port);
            _ownsProcess = true;

            Console.WriteLine("[Pocket] Ожидаю сервер TTS (первый запуск — скачивание весов ~458 МБ)...");
            WaitUntilReady(TimeSpan.FromMinutes(6));

            Console.WriteLine("[Pocket] Прогрев (ударения + первый синтез)...");
            WarmUp();

            IsAvailable = true;
            StartHealthMonitor();
            Console.WriteLine($"[Pocket] Готов. Голос: {VoiceName}, sample_rate={SampleRate}");
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Pocket] Не удалось запустить: {ex.Message}");
            StopProcess();
            IsAvailable = false;
            return false;
        }
    }

    /// <summary>
    /// Помечает движок недоступным и запускает фоновое восстановление.
    /// Анализ F2: раньше сбой после Initialize оставлял Pocket «мёртвым»
    /// до конца сессии — каждый следующий ответ уходил в текст; теперь
    /// сервер перезапускается в фоне, а до этого озвучка идёт через Piper.
    /// </summary>
    public void MarkUnavailableAndRecover()
    {
        IsAvailable = false;
        StartRecovery();
    }

    private void StartRecovery()
    {
        if (Interlocked.Exchange(ref _recovering, 1) == 1)
            return; // восстановление уже идёт

        if (string.IsNullOrEmpty(_uvExe))
        {
            // Параметры запуска неизвестны (сервер подключался чужой) —
            // восстановиться не можем, остаёмся на Piper.
            Interlocked.Exchange(ref _recovering, 0);
            return;
        }

        _ = Task.Run(() =>
        {
            try
            {
                StopProcess();

                Console.WriteLine("[Pocket] Перезапуск сервера TTS...");
                StartServer(_uvExe, _script, _project, _voiceReference, _port);
                _ownsProcess = true;

                WaitUntilReady(TimeSpan.FromSeconds(90));
                WarmUp();

                IsAvailable = true;
                Console.WriteLine("[Pocket] Сервер TTS восстановлен.");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Pocket] Восстановление не удалось: {ex.Message}. Остаёмся на Piper.");
                StopProcess();
                IsAvailable = false;
            }
            finally
            {
                Interlocked.Exchange(ref _recovering, 0);
            }
        });
    }

    /// <summary>
    /// Фоновая проверка здоровья сервера раз в 30 с: мёртвый процесс
    /// обнаруживается ДО следующей реплики, а не по факту сбоя озвучки.
    /// </summary>
    private void StartHealthMonitor()
    {
        _healthTimer?.Dispose();

        _healthTimer = new System.Threading.Timer(_ =>
        {
            try
            {
                if (!IsAvailable || Volatile.Read(ref _recovering) != 0)
                    return;

                if (!ProbeReady())
                {
                    Console.WriteLine("[Pocket] ⚠ Сервер TTS не отвечает — запускаю восстановление...");
                    MarkUnavailableAndRecover();
                }
            }
            catch
            {
                // Мониторинг не должен ронять приложение
            }
        }, null, TimeSpan.FromSeconds(30), TimeSpan.FromSeconds(30));
    }

    /// <summary>
    /// Синтезирует текст и отдаёт PCM-куски (s16le моно) ПО МЕРЕ готовности —
    /// первые байты приходят через ~200–500 мс после запроса.
    /// </summary>
    public async IAsyncEnumerable<byte[]> SynthesizePcmAsync(
        string text,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        if (!IsAvailable)
            yield break;

        text = SpeechText.Clean(text);

        if (string.IsNullOrWhiteSpace(text))
            yield break;

        var payload = JsonSerializer.Serialize(new { text });

        using var request = new HttpRequestMessage(HttpMethod.Post, _baseUrl + "/tts")
        {
            Content = new StringContent(payload, Encoding.UTF8, "application/json")
        };

        // ResponseHeadersRead — КРИТИЧНО: без него HttpClient буферизует
        // весь ответ и стриминг (и низкая задержка) теряется.
        using var response = await _http
            .SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct)
            .ConfigureAwait(false);

        response.EnsureSuccessStatusCode();

        if (response.Headers.TryGetValues("X-Sample-Rate", out var rates) &&
            int.TryParse(rates.FirstOrDefault(), out var rate))
        {
            SampleRate = rate;
        }

        var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        var buffer = new byte[16 * 1024];

        while (true)
        {
            var read = await stream.ReadAsync(buffer, ct).ConfigureAwait(false);
            if (read <= 0)
                yield break;

            var chunk = new byte[read];
            Array.Copy(buffer, chunk, read);
            yield return chunk;
        }
    }

    // ─── Внутреннее ────────────────────────────────────────

    private void StartServer(string uvExe, string script, string project,
        string voiceReferencePath, int port)
    {
        var args = new StringBuilder();
        args.Append("run --project \"").Append(project).Append('"');
        args.Append(" --with num2words");           // раскрытие цифр в слова
        args.Append(" python \"").Append(script).Append('"');
        args.Append(" --port ").Append(port);

        if (!string.IsNullOrWhiteSpace(voiceReferencePath) && File.Exists(voiceReferencePath))
        {
            args.Append(" --voice \"").Append(voiceReferencePath).Append('"');
        }

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

        // Логи сервера на русском: Python пишет UTF-8, читаем тоже в UTF-8.
        psi.Environment["PYTHONUTF8"] = "1";
        psi.StandardOutputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        psi.StandardErrorEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

        var process = Process.Start(psi)
            ?? throw new IOException("Не удалось запустить сервер TTS.");

        // Логи сервера (в т.ч. прогресс скачивания весов) — в консоль ZERE.
        _ = Task.Run(async () =>
        {
            try
            {
                string? line;
                while ((line = await process.StandardOutput.ReadLineAsync()) != null)
                {
                    if (!string.IsNullOrWhiteSpace(line))
                        Console.WriteLine(line);
                }
            }
            catch { /* процесс завершён */ }
        });

        _ = Task.Run(async () =>
        {
            try
            {
                string? line;
                while ((line = await process.StandardError.ReadLineAsync()) != null)
                {
                    if (!string.IsNullOrWhiteSpace(line))
                        Console.WriteLine(line);
                }
            }
            catch { /* процесс завершён */ }
        });

        process.EnableRaisingEvents = true;
        process.Exited += (_, _) =>
        {
            if (IsAvailable)
                Console.WriteLine("[Pocket] ⚠ Сервер TTS неожиданно завершился.");
        };

        _process = process;
    }

    private bool ProbeReady()
    {
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(1));
            using var response = _http.GetAsync($"{_baseUrl}/health", cts.Token)
                .GetAwaiter().GetResult();

            if (!response.IsSuccessStatusCode)
                return false;

            var json = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            ApplyHealth(JsonDocument.Parse(json).RootElement);
            return VoiceName.Length > 0 && SampleRate > 0;
        }
        catch
        {
            return false;
        }
    }

    private void WaitUntilReady(TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        var lastLog = DateTime.UtcNow;

        while (DateTime.UtcNow < deadline)
        {
            if (_process is { HasExited: true })
                throw new IOException($"Сервер TTS завершился (код {_process.ExitCode}).");

            try
            {
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                using var response = _http.GetAsync($"{_baseUrl}/health", cts.Token)
                    .GetAwaiter().GetResult();

                if (response.IsSuccessStatusCode)
                {
                    var json = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                    using var doc = JsonDocument.Parse(json);
                    ApplyHealth(doc.RootElement);

                    if (doc.RootElement.TryGetProperty("status", out var status) &&
                        status.GetString() == "ready")
                    {
                        return;
                    }
                }
            }
            catch
            {
                // Сервер ещё поднимается — это нормально
            }

            if ((DateTime.UtcNow - lastLog).TotalSeconds > 10)
            {
                Console.WriteLine("[Pocket] …всё ещё загружаю (см. лог выше)");
                lastLog = DateTime.UtcNow;
            }

            Thread.Sleep(500);
        }

        throw new TimeoutException("Сервер TTS не стал ready за отведённое время.");
    }

    private void ApplyHealth(JsonElement health)
    {
        if (health.TryGetProperty("sample_rate", out var rate) && rate.TryGetInt32(out var r))
            SampleRate = r;

        if (health.TryGetProperty("voice", out var voice))
            VoiceName = voice.GetString() ?? VoiceName;
    }

    private void WarmUp()
    {
        // Прогрев: заодно при первом запуске скачиваются модели ударений (RUAccent).
        var payload = JsonSerializer.Serialize(new { text = "Готово." });
        using var request = new HttpRequestMessage(HttpMethod.Post, _baseUrl + "/tts")
        {
            Content = new StringContent(payload, Encoding.UTF8, "application/json")
        };

        using var response = _http.SendAsync(request)
            .GetAwaiter().GetResult();
        response.EnsureSuccessStatusCode();

        using var stream = response.Content.ReadAsStream();
        var buffer = new byte[16 * 1024];
        while (stream.Read(buffer, 0, buffer.Length) > 0)
        {
            // отбрасываем — прогрев
        }
    }

    private void StopProcess()
    {
        IsAvailable = false;

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

    public void Dispose()
    {
        try { _healthTimer?.Dispose(); } catch { }

        if (_ownsProcess)
            StopProcess();

        try { _http.Dispose(); } catch { }
        GC.SuppressFinalize(this);
    }
}
