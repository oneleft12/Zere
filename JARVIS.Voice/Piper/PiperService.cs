using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text;
using JARVIS.Voice.Text;

namespace JARVIS.Voice.Piper;

/// <summary>
/// TTS на базе piper с ПЕРСИСТЕНТНЫМ процессом.
///
/// Идея (Этап 1 «низкая задержка»):
///  - процесс piper запускается один раз при Initialize — модель грузится ~1 с только при старте,
///    а не при каждом вызове (раньше каждый SpeakAsync платил ~1 с за запуск + загрузку модели);
///  - текст уходит в stdin ПОСТРОЧНО, каждая строка — одно предложение;
///  - каждое предложение читается из stdout как готовый кадр WAV (`-f -`) и отдаётся потребителю
///    сразу, пока следующее предложение уже синтезируется в фоне (pipelining).
///
/// Протокол stdout (проверен эмпирически на piper 1.2.0):
///  - кадр = корректный WAV (RIFF + объявленные размеры сходятся);
///  - ПОСЛЕ объявленного размера data piper дописывает «хвост» из нулевых байт
///    (паддинг ~0.78% длины). Хвост принадлежит предыдущему кадру, поэтому чтение
///    следующего кадра начинается с поиска магии RIFF — она пропускает этот хвост.
///  - порядок байтов в трубке строго последовательный, поэтому схема не рассинхронизируется:
///    строка записывается ровно перед чтением её кадра.
/// </summary>
public sealed class PiperService : IDisposable
{
    public bool IsLoaded { get; private set; }

    private readonly string _piperDir;
    private readonly string _espeakDataPath;
    private string _currentVoice = "ru_RU-irina-medium";
    private string? _piperExe;
    private string? _cachedModelPath;

    // Параметры инференса. Меняются только между репликами (процесс перезапускается).
    private float _lengthScale = 1.15f;
    private float _sentenceSilence = 0.2f;
    private const float NoiseScale = 0.35f; // минимум шума синтеза (не шипит)
    private const float NoiseW = 0.65f;     // стабильная интонация, без металличности

    private static readonly TimeSpan FrameTimeout = TimeSpan.FromSeconds(30);

    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly object _processLock = new();

    private Process? _process;
    private StreamWriter? _stdin;
    private Stream? _stdout;
    private bool _warmed;
    private int _fileSeq;

    public string CurrentVoice => _currentVoice;

    public PiperService()
    {
        // Путь строится относительно AppContext.BaseDirectory с учётом структуры проекта:
        // bin/Debug/net10.0/ → ../../.. → корень решения, затем JARVIS.Voice/Piper.
        // Если структура проекта изменится, этот путь нужно обновить.
        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        _piperDir = Path.Combine(root, "JARVIS.Voice", "Piper");
        _espeakDataPath = Path.Combine(_piperDir, "espeak-ng-data");
    }

    public bool Initialize(string? voiceName = null)
    {
        if (voiceName != null)
            _currentVoice = voiceName;

        _piperExe = FindPiperExecutable();

        if (_piperExe == null)
        {
            Console.WriteLine("[Piper] Исполняемый файл piper не найден.");
            IsLoaded = false;
            return false;
        }

        var modelPath = FindModelPath();

        if (modelPath == null)
        {
            Console.WriteLine($"[Piper] Модель '{_currentVoice}' не найдена в {_piperDir}");
            IsLoaded = false;
            return false;
        }

        _cachedModelPath = modelPath;

        CleanupOldOutputs();

        try
        {
            lock (_processLock)
            {
                StartProcessLocked();
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Piper] Не удалось запустить процесс: {ex.Message}");
            IsLoaded = false;
            return false;
        }

        IsLoaded = true;

        if (Directory.Exists(_espeakDataPath))
            Console.WriteLine($"[Piper] espeak-ng-data: {_espeakDataPath}");
        else
            Console.WriteLine($"[Piper] ⚠ espeak-ng-data не найден: {_espeakDataPath}");

        Console.WriteLine($"[Piper] Загружен (персистентный процесс). Голос: {_currentVoice}");

        // Прогрев модели в фоне: первая реплика не должна ждать загрузку ONNX (~1 с).
        _ = Task.Run(async () =>
        {
            await _gate.WaitAsync().ConfigureAwait(false);
            try
            {
                await WarmupUnderGateAsync().ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Piper] Прогрев не удался: {ex.Message}");
            }
            finally
            {
                _gate.Release();
            }
        });

        return true;
    }

    /// <summary>
    /// Синтезирует текст ПОПРЕДЛОЖЕННО и отдаёт путь к WAV-файлу каждого предложения,
    /// как только он готов. Следующее предложение синтезируется в фоне,
    /// пока потребитель играет предыдущее.
    /// </summary>
    public async IAsyncEnumerable<string> SynthesizeStreamAsync(
        string text,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        text = SpeechText.Clean(text);

        if (string.IsNullOrWhiteSpace(text) || !IsLoaded)
            yield break;

        var sentences = SpeechText.SplitSentences(text);

        await _gate.WaitAsync(ct).ConfigureAwait(false);

        try
        {
            // Идемпотентно: на первом обращении догоняет прогрев,
            // если фоновый прогрев ещё не успел.
            await WarmupUnderGateAsync().ConfigureAwait(false);

            var pendingWrite = sentences[0];
            var nextIndex = 1;
            var unreadFrame = false;

            while (true)
            {
                // Отмена проверяется ТОЛЬКО на границе кадров:
                // на этом месте непрочитанных кадров в процессе нет — буферы чистые.
                if (ct.IsCancellationRequested)
                    yield break;

                if (pendingWrite == null && !unreadFrame)
                    yield break;

                byte[] frame;

                if (pendingWrite != null)
                {
                    try
                    {
                        await WriteLineAsync(pendingWrite).ConfigureAwait(false);
                        pendingWrite = null;
                        unreadFrame = true;
                        frame = await ReadFrameAsync().ConfigureAwait(false);
                        unreadFrame = false;
                    }
                    catch
                    {
                        // Буферы процесса могли рассинхронизироваться — перезапускаем
                        // и пробрасываем ошибку наверх (потребитель сделает фолбэк на текст).
                        unreadFrame = false;
                        try { RestartProcess(); } catch { /* важнее исходная ошибка */ }
                        throw;
                    }
                }
                else
                {
                    // unreadFrame без pendingWrite возможно только извне — читаем дальше.
                    try
                    {
                        frame = await ReadFrameAsync().ConfigureAwait(false);
                        unreadFrame = false;
                    }
                    catch
                    {
                        unreadFrame = false;
                        try { RestartProcess(); } catch { }
                        throw;
                    }
                }

                var file = SaveFrame(frame);

                // Запускаем синтез СЛЕДУЮЩЕГО предложения заранее — пока потребитель
                // обрабатывает и играет текущий файл, процесс уже пишет следующий.
                if (nextIndex < sentences.Count)
                    pendingWrite = sentences[nextIndex++];

                yield return file;
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>
    /// Прогрев: одна короткая фраза под нагрузкой гейта, кадр отбрасывается.
    /// После этого первая настоящая реплика идёт без ~1-секундной загрузки модели.
    /// </summary>
    private async Task WarmupUnderGateAsync()
    {
        if (_warmed || !IsLoaded)
            return;

        for (var attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                await WriteLineAsync("Проверка связи.").ConfigureAwait(false);
                await ReadFrameAsync().ConfigureAwait(false); // отбрасываем — кадр только для прогрева
                _warmed = true;
                return;
            }
            catch (Exception ex) when (attempt == 0)
            {
                Console.WriteLine($"[Piper] Прогрев не удался, перезапуск: {ex.Message}");
                RestartProcess();
            }
        }
    }

    /// <summary>
    /// Задержка синтеза: length_scale (из VoiceConfig.SpeechSpeed) и пауза после
    /// предложения (VoiceConfig.SentenceSilence). Процесс перезапускается, т.к.
    /// параметры передаются ему при старте.
    /// </summary>
    public void SetInferenceParams(float lengthScale, float sentenceSilence)
    {
        lengthScale = Math.Clamp(lengthScale, 0.5f, 3.0f);
        sentenceSilence = Math.Clamp(sentenceSilence, 0f, 2f);

        if (Math.Abs(lengthScale - _lengthScale) < 0.001f &&
            Math.Abs(sentenceSilence - _sentenceSilence) < 0.001f)
            return;

        _lengthScale = lengthScale;
        _sentenceSilence = sentenceSilence;

        if (!IsLoaded)
            return;

        lock (_processLock)
        {
            if (_process == null)
                return;
            try
            {
                StartProcessLocked();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Piper] Перезапуск после смены параметров не удался: {ex.Message}");
            }
        }
    }

    public void SetVoice(string voiceName)
    {
        if (voiceName == _currentVoice && IsLoaded)
            return;

        var previousVoice = _currentVoice;
        _currentVoice = voiceName;
        _cachedModelPath = null;

        if (!IsLoaded)
            return;

        var modelPath = FindModelPath();
        if (modelPath == null)
        {
            Console.WriteLine($"[Piper] Голос '{voiceName}' не найден, остаёмся на '{previousVoice}'.");
            _currentVoice = previousVoice;
            return;
        }

        _cachedModelPath = modelPath;

        lock (_processLock)
        {
            try
            {
                StartProcessLocked();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Piper] Смена голоса не удалась: {ex.Message}");
            }
        }
    }

    public List<string> GetAvailableVoices()
    {
        if (!Directory.Exists(_piperDir))
            return new List<string>();

        return Directory.GetFiles(_piperDir, "*.onnx")
            .Select(f => Path.GetFileNameWithoutExtension(f))
            .ToList();
    }

    // ─── Работа с процессом ────────────────────────────────

    /// <summary>Вызывать только под _processLock. Убивает старый процесс и запускает новый.</summary>
    private void StartProcessLocked()
    {
        KillProcessLocked();

        if (_piperExe == null || _cachedModelPath == null)
            throw new InvalidOperationException("Piper не инициализирован (нет exe или модели).");

        // Форматирование чисел строго InvariantCulture: иначе в русской локали
        // получим "0,35" и piper не разберёт аргументы.
        var args = string.Format(CultureInfo.InvariantCulture,
            "-m \"{0}\" -f - -q --noise_scale {1} --length_scale {2} --noise_w {3} --sentence_silence {4} --espeak_data \"{5}\"",
            _cachedModelPath, NoiseScale, _lengthScale, NoiseW, _sentenceSilence, _espeakDataPath);

        var psi = new ProcessStartInfo
        {
            FileName = _piperExe,
            Arguments = args,
            UseShellExecute = false,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = _piperDir,
            StandardInputEncoding = new UTF8Encoding(false)
        };

        if (Directory.Exists(_espeakDataPath))
        {
            psi.EnvironmentVariables["ESPEAKDATA_PATH"] = _espeakDataPath;
            psi.EnvironmentVariables["ESPEAK_DATA_PATH"] = _espeakDataPath;
        }

        var process = Process.Start(psi)
            ?? throw new IOException("Не удалось запустить процесс piper.");

        var stdout = process.StandardOutput.BaseStream;

        // Если piper умер — закрываем stdout, чтобы зависшие чтения разблокировались.
        process.EnableRaisingEvents = true;
        process.Exited += (_, _) =>
        {
            try { stdout.Dispose(); } catch { /* процесс уже завершён */ }
        };

        // stderr надо постоянно читать, иначе буфер забьётся и процесс встанет.
        _ = Task.Run(async () =>
        {
            try
            {
                var err = await process.StandardError.ReadToEndAsync().ConfigureAwait(false);
                if (!string.IsNullOrWhiteSpace(err))
                    Console.WriteLine($"[Piper] stderr: {err.Trim()}");
            }
            catch { /* процесс завершён */ }
        });

        process.StandardInput.AutoFlush = true;

        _process = process;
        _stdin = process.StandardInput;
        _stdout = stdout;
        _warmed = false; // модель загружается заново — нужен прогрев
    }

    private void RestartProcess()
    {
        lock (_processLock)
        {
            StartProcessLocked();
        }
    }

    /// <summary>Вызывать только под _processLock.</summary>
    private void KillProcessLocked()
    {
        var process = _process;
        _process = null;
        _stdin = null;
        _stdout = null;

        if (process == null)
            return;

        try
        {
            // Штатное завершение: закрываем stdin — piper выйдет сам по EOF.
            process.StandardInput.Close();
            if (!process.WaitForExit(1000))
                process.Kill(entireProcessTree: true);
        }
        catch
        {
            try { process.Kill(entireProcessTree: true); } catch { /* уже завершён */ }
        }
        finally
        {
            try { process.Dispose(); } catch { }
        }
    }

    private Task WriteLineAsync(string line)
    {
        var stdin = _stdin ?? throw new IOException("Piper: stdin недоступен (процесс не запущен).");
        return stdin.WriteLineAsync(line);
    }

    // ─── Чтение кадров из stdout ───────────────────────────

    /// <summary>
    /// Читает один кадр WAV из stdout: ищет магию RIFF (заодно пропуская нулевой
    /// «хвост» предыдущего кадра), разбирает чанки и возвращает готовый байтовый
    /// образ WAV-файла (объявленные размеры в заголовке сходятся с данными).
    /// </summary>
    private async Task<byte[]> ReadFrameAsync()
    {
        using var cts = new CancellationTokenSource(FrameTimeout);
        var token = cts.Token;

        var header = new MemoryStream(64);

        // 1. Ресинхронизация: пропускаем всё до магии RIFF
        //    (это нулевой хвост предыдущего кадра — он всегда меньше 32 КБ).
        var window = new byte[4];
        while (true)
        {
            var b = await ReadExactAsync(1, token).ConfigureAwait(false);
            window[0] = window[1];
            window[1] = window[2];
            window[2] = window[3];
            window[3] = b[0];

            if (window[0] == (byte)'R' && window[1] == (byte)'I' &&
                window[2] == (byte)'F' && window[3] == (byte)'F')
            {
                header.Write(window, 0, 4);
                break;
            }
        }

        // 2. RIFF-size + "WAVE"
        var riffRest = await ReadExactAsync(8, token).ConfigureAwait(false);
        if (riffRest[4] != (byte)'W' || riffRest[5] != (byte)'A' ||
            riffRest[6] != (byte)'V' || riffRest[7] != (byte)'E')
        {
            throw new IOException("Piper: некорректный кадр WAV (нет WAVE).");
        }
        header.Write(riffRest, 0, 8);

        // 3. Чанки до data (fmt и любые прочие идут в заголовок как есть)
        while (true)
        {
            var chunkHead = await ReadExactAsync(8, token).ConfigureAwait(false);
            var id = Encoding.ASCII.GetString(chunkHead, 0, 4);
            var size = BitConverter.ToInt32(chunkHead, 4);

            if (size < 0 || size > 100_000_000)
                throw new IOException($"Piper: повреждён размер чанка '{id}' ({size}).");

            header.Write(chunkHead, 0, 8);

            if (id == "data")
            {
                var payload = await ReadExactAsync(size, token).ConfigureAwait(false);
                var headerBytes = header.ToArray();
                var frame = new byte[headerBytes.Length + payload.Length];
                Buffer.BlockCopy(headerBytes, 0, frame, 0, headerBytes.Length);
                Buffer.BlockCopy(payload, 0, frame, headerBytes.Length, payload.Length);
                return frame;
            }

            // Нечётный чанк дополняется pad-байтом по спецификации WAV.
            var extra = size + (size & 1);
            var chunkData = await ReadExactAsync(extra, token).ConfigureAwait(false);
            header.Write(chunkData, 0, chunkData.Length);
        }
    }

    private async Task<byte[]> ReadExactAsync(int count, CancellationToken token)
    {
        var stream = _stdout ?? throw new IOException("Piper: stdout недоступен (процесс не запущен).");
        var buffer = new byte[count];
        var offset = 0;

        while (offset < count)
        {
            int read;
            try
            {
                read = await stream.ReadAsync(buffer.AsMemory(offset, count - offset), token)
                    .ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                throw new TimeoutException($"Piper: таймаут чтения кадра ({FrameTimeout.TotalSeconds:0} с).");
            }

            if (read == 0)
                throw new IOException("Piper: поток закрыт — процесс завершился.");

            offset += read;
        }

        return buffer;
    }

    private string SaveFrame(byte[] frame)
    {
        // Префикс output_ — чтобы файл подхватывала CleanupOldOutputs.
        var name = $"output_stream_{DateTime.Now:yyyyMMdd_HHmmss}_{Interlocked.Increment(ref _fileSeq)}.wav";
        var path = Path.Combine(_piperDir, name);
        File.WriteAllBytes(path, frame);
        return path;
    }

    // ─── Поиск файлов ──────────────────────────────────────

    private string? FindPiperExecutable()
    {
        var piperPath = Path.Combine(_piperDir, "piper");

        if (File.Exists(piperPath))
            return piperPath;

        var piperExe = Path.Combine(_piperDir, "piper.exe");

        if (File.Exists(piperExe))
            return piperExe;

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "piper",
                Arguments = "--version",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                CreateNoWindow = true
            };

            using var process = Process.Start(psi);
            process?.WaitForExit(3000);

            if (process?.ExitCode == 0)
                return "piper";
        }
        catch { }

        return null;
    }

    private string? FindModelPath()
    {
        var modelFile = $"{_currentVoice}.onnx";

        var modelPath = Path.Combine(_piperDir, modelFile);

        if (File.Exists(modelPath))
            return modelPath;

        var onnxFiles = Directory.GetFiles(_piperDir, "*.onnx");

        if (onnxFiles.Length > 0)
            return onnxFiles[0];

        return null;
    }

    private void CleanupOldOutputs()
    {
        try
        {
            var cutoff = DateTime.Now.AddHours(-1);
            var outputFiles = Directory.GetFiles(_piperDir, "output_*.wav");

            foreach (var file in outputFiles)
            {
                var fileInfo = new FileInfo(file);

                if (fileInfo.LastWriteTime < cutoff)
                {
                    try
                    {
                        fileInfo.Delete();
                    }
                    catch
                    {
                        // Ignore individual file deletion failures during cleanup
                    }
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
        lock (_processLock)
        {
            KillProcessLocked();
        }

        try { _gate.Dispose(); } catch { }
        GC.SuppressFinalize(this);
    }
}
