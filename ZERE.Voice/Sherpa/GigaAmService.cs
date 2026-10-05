using System.Diagnostics;
using System.Security.Cryptography;
using ZERE.Voice.Audio;
using NAudio.Wave;
using SherpaOnnx;

namespace ZERE.Voice.Sherpa;

/// <summary>
/// Распознавание речи GigaAM-v3 punct (SaluteDevices/Sber, MIT) через
/// sherpa-onnx (Apache-2.0, Next-gen Kaldi) — основной STT-движок ZERE
/// (отчёт docs/STT_ENGINE_RESEARCH.md, §5, этапы 0–4).
///
/// Почему он основной (замеры на этой машине, 4 потока, 11,29 с русского wav):
/// RTF 0.14–0.17 против 1.1–1.4 у faster-whisper medium и качество текста
/// («У лукоморья дуб зелёный.» с пунктуацией против искажений у Whisper).
/// </summary>
public class GigaAmService : ISttService
{
    /// <summary>Имя папки модели в ZERE.Voice/Models (совпадает с именем архива).</summary>
    public const string ModelDirName =
        "sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16";

    private const string ModelUrl =
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
        + ModelDirName + ".tar.bz2";

    // Контрольные суммы архива — те же, что в installer/install.ps1 (§ артефакты).
    private const string ModelSha256 =
        "f9620a0099019c6afcee26525ef9ed3297fa50dd5691c1902af0c948fc1a470b";
    private const long ModelSizeBytes = 170197019;

    private readonly string _modelsDir;
    private readonly string _modelDir;
    private readonly SemaphoreSlim _ensureLock = new(1, 1);
    private readonly object _initLock = new();

    private OfflineRecognizer? _recognizer;
    private volatile bool _ensureAttempted;
    private bool _disposed;

    public string CurrentModel => "gigaam-v3";

    public GigaAmService()
    {
        // Путь строится как в WhisperService: bin/Debug/net10.0/ → 4 уровня
        // вверх → корень решения, затем ZERE.Voice/Models.
        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        _modelsDir = Path.Combine(root, "ZERE.Voice", "Models");
        _modelDir = Path.Combine(_modelsDir, ModelDirName);
    }

    public bool IsInstalled()
    {
        return File.Exists(Path.Combine(_modelDir, "encoder.int8.onnx")) &&
               File.Exists(Path.Combine(_modelDir, "decoder.onnx")) &&
               File.Exists(Path.Combine(_modelDir, "joiner.onnx")) &&
               File.Exists(Path.Combine(_modelDir, "tokens.txt"));
    }

    /// <summary>
    /// Предзагрузка при старте: при отсутствии модели — разовое скачивание
    /// (163 МБ, проверка SHA-256) и распаковка, затем инициализация
    /// распознавателя (анализ S3: первая транскрибация не ждёт загрузку).
    /// </summary>
    public bool Preload()
    {
        try
        {
            EnsureModelAsync().GetAwaiter().GetResult();

            if (!IsInstalled())
            {
                Console.WriteLine(
                    "[GigaAm] Модель не найдена — распознавание GigaAM недоступно " +
                    "(скачайте её установщиком или вручную).");
                return false;
            }

            _ = GetRecognizer();
            Console.WriteLine($"[Voice] GigaAM предзагружен (модель: {CurrentModel}).");
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[GigaAm] Не удалось предзагрузить модель: {ex.Message}");
            return false;
        }
    }

    /// <summary>
    /// Распознаёт WAV-файл. Таймаут — та же схема, что в WhisperService
    /// (анализ F6): по истечении возвращается пустой результат, а «осиротевшая»
    /// задача доработает и освободит ресурсы сама.
    /// </summary>
    public async Task<string> TranscribeAsync(string wavFile, int timeoutSeconds = 30)
    {
        if (!IsInstalled())
            return "Модель GigaAM не найдена.";

        var sw = Stopwatch.StartNew();

        var work = Task.Run(() => TranscribeCore(wavFile));
        var finished = await Task.WhenAny(work, Task.Delay(TimeSpan.FromSeconds(timeoutSeconds)));

        if (finished != work)
        {
            // Наблюдаем за фоновой задачей, чтобы исключение не осталось
            // ненаблюденным после таймаута (зеркало WhisperService).
            _ = work.ContinueWith(
                t => _ = t.Exception,
                TaskContinuationOptions.OnlyOnFaulted);

            Console.WriteLine(
                $"[GigaAm] Таймаут распознавания ({timeoutSeconds} с) — возвращаю пустой результат.");
            return "";
        }

        var result = await work;

        Console.WriteLine($"[Perf] STT={sw.ElapsedMilliseconds} мс (модель: {CurrentModel})");

        return result;
    }

    private string TranscribeCore(string wavFile)
    {
        // Та же предобработка, что и для Whisper: ресемплинг → noise gate →
        // AGC → лимитер → нормализация, на выходе 16 kHz mono PCM16.
        var processedFile = AudioPreprocessor.ProcessForWhisper(wavFile);

        try
        {
            var recognizer = GetRecognizer();
            var (sampleRate, samples) = ReadWavSamples(processedFile);

            if (samples.Length == 0)
                return "";

            var stream = recognizer.CreateStream();
            try
            {
                stream.AcceptWaveform(sampleRate, samples);
                recognizer.Decode(stream);

                var text = (stream.Result.Text ?? "").Trim();

                // Пустой или чисто пунктуационный результат — фильтр
                // зеркалит логику WhisperService.
                if (string.IsNullOrWhiteSpace(text) ||
                    text.All(c => char.IsWhiteSpace(c) || char.IsPunctuation(c)))
                {
                    return "";
                }

                return text;
            }
            finally
            {
                stream.Dispose();
            }
        }
        finally
        {
            if (processedFile != wavFile)
            {
                try { File.Delete(processedFile); } catch { }
            }
        }
    }

    private OfflineRecognizer GetRecognizer()
    {
        if (_recognizer != null)
            return _recognizer;

        lock (_initLock)
        {
            if (_recognizer != null)
                return _recognizer;

            var config = new OfflineRecognizerConfig();
            config.FeatConfig.SampleRate = 16000;
            config.FeatConfig.FeatureDim = 80;

            config.ModelConfig.Tokens = Path.Combine(_modelDir, "tokens.txt");
            config.ModelConfig.Transducer.Encoder = Path.Combine(_modelDir, "encoder.int8.onnx");
            config.ModelConfig.Transducer.Decoder = Path.Combine(_modelDir, "decoder.onnx");
            config.ModelConfig.Transducer.Joiner = Path.Combine(_modelDir, "joiner.onnx");

            // nemo_transducer обязателен: без него init падает с
            // «vocab_size does not exist in the metadata» (проверено).
            config.ModelConfig.ModelType = "nemo_transducer";
            config.ModelConfig.NumThreads = Math.Max(1, Math.Min(4, Environment.ProcessorCount));
            config.ModelConfig.Debug = 0;
            config.DecodingMethod = "greedy_search";

            _recognizer = new OfflineRecognizer(config);
            return _recognizer;
        }
    }

    /// <summary>
    /// Читает WAV в float-сэмплы: mono-склейка каналов + линейный ресемплинг
    /// до 16 kHz (sherpa принимает любой sample rate, но предобработка
    /// гарантирует 16 kHz; это — страховка на случай её сбоя).
    /// </summary>
    private static (int SampleRate, float[] Samples) ReadWavSamples(string path)
    {
        ISampleProvider source = new AudioFileReader(path);
        var channels = Math.Max(1, source.WaveFormat.Channels);
        var sampleRate = source.WaveFormat.SampleRate;

        var buffer = new List<float>(sampleRate * channels);
        var chunk = new float[4096];
        int read;

        while ((read = source.Read(chunk, 0, chunk.Length)) > 0)
        {
            for (var i = 0; i < read; i++)
                buffer.Add(chunk[i]);
        }

        if (channels > 1)
        {
            var frames = buffer.Count / channels;
            var mono = new float[frames];

            for (var f = 0; f < frames; f++)
            {
                float sum = 0;
                for (var c = 0; c < channels; c++)
                    sum += buffer[f * channels + c];
                mono[f] = sum / channels;
            }

            buffer.Clear();
            buffer.AddRange(mono);
        }

        var samples = buffer.ToArray();

        if (sampleRate != 16000)
            samples = Resample(samples, sampleRate, 16000);

        return (sampleRate == 16000 ? sampleRate : 16000, samples);
    }

    private static float[] Resample(float[] input, int fromRate, int toRate)
    {
        if (input.Length == 0 || fromRate == toRate)
            return input;

        var outputLength = (int)((long)input.Length * toRate / fromRate);
        if (outputLength <= 0)
            return input;

        var output = new float[outputLength];
        var ratio = (double)fromRate / toRate;

        for (var i = 0; i < outputLength; i++)
        {
            var pos = i * ratio;
            var i0 = (int)pos;
            var i1 = Math.Min(i0 + 1, input.Length - 1);
            var frac = pos - i0;
            output[i] = (float)(input[i0] * (1.0 - frac) + input[i1] * frac);
        }

        return output;
    }

    /// <summary>
    /// Разовое скачивание модели при её отсутствии: HTTP + SHA-256 + tar
    /// (Windows 10+ поставляет tar.exe; на Linux — GNU/bsdtar из PATH).
    /// </summary>
    private async Task EnsureModelAsync()
    {
        if (_ensureAttempted || IsInstalled())
            return;

        await _ensureLock.WaitAsync();

        try
        {
            if (_ensureAttempted || IsInstalled())
                return;

            _ensureAttempted = true;
            await DownloadModelAsync();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[GigaAm] Скачивание модели прервано: {ex.Message}");
        }
        finally
        {
            _ensureLock.Release();
        }
    }

    private async Task<bool> DownloadModelAsync()
    {
        Console.WriteLine($"[GigaAm] Модель не найдена — скачиваю GigaAM-v3 (~163 МБ): {ModelUrl}");

        var archivePath = Path.Combine(Path.GetTempPath(), ModelDirName + ".tar.bz2");

        try
        {
            Directory.CreateDirectory(_modelsDir);

            using (var http = new HttpClient())
            {
                http.Timeout = TimeSpan.FromMinutes(15);

                using var response = await http.GetAsync(
                    ModelUrl, HttpCompletionOption.ResponseHeadersRead);
                response.EnsureSuccessStatusCode();

                var totalBytes = response.Content.Headers.ContentLength ?? -1;
                await using var source = await response.Content.ReadAsStreamAsync();
                await using var target = File.Create(archivePath);

                var buffer = new byte[81920];
                long received = 0;
                var lastPercent = -1;
                int read;

                while ((read = await source.ReadAsync(buffer.AsMemory(0, buffer.Length))) > 0)
                {
                    await target.WriteAsync(buffer.AsMemory(0, read));
                    received += read;

                    if (totalBytes > 0)
                    {
                        var percent = (int)(received * 100 / totalBytes);
                        if (percent >= lastPercent + 20)
                        {
                            lastPercent = percent;
                            Console.WriteLine($"[GigaAm] скачивание: {percent}%");
                        }
                    }
                }
            }

            // Размер и SHA-256 — как в installer/install.ps1: битая выгрузка
            // не распаковывается.
            var archiveInfo = new FileInfo(archivePath);
            if (archiveInfo.Length != ModelSizeBytes)
            {
                Console.WriteLine(
                    $"[GigaAm] Неверный размер архива ({archiveInfo.Length} ≠ {ModelSizeBytes}) — отмена.");
                return false;
            }

            string hex;
            await using (var stream = File.OpenRead(archivePath))
            {
                var hash = await SHA256.HashDataAsync(stream);
                hex = Convert.ToHexString(hash);
            }

            if (!hex.Equals(ModelSha256, StringComparison.OrdinalIgnoreCase))
            {
                Console.WriteLine("[GigaAm] SHA-256 архива не совпал — отмена.");
                return false;
            }

            var psi = new ProcessStartInfo
            {
                FileName = "tar",
                Arguments = $"-xjf \"{archivePath}\" -C \"{_modelsDir}\"",
                UseShellExecute = false,
                CreateNoWindow = true,
            };

            using var proc = Process.Start(psi);
            if (proc == null)
            {
                Console.WriteLine("[GigaAm] Не удалось запустить tar — распаковка невозможна.");
                return false;
            }

            if (!proc.WaitForExit(10 * 60 * 1000))
            {
                try { proc.Kill(entireProcessTree: true); } catch { }
                Console.WriteLine("[GigaAm] Распаковка модели затянулась — прервано.");
                return false;
            }

            if (proc.ExitCode != 0)
            {
                Console.WriteLine($"[GigaAm] tar завершился с кодом {proc.ExitCode}.");
                return false;
            }

            if (!IsInstalled())
            {
                Console.WriteLine("[GigaAm] Архив распакован, но файлы модели не найдены.");
                return false;
            }

            Console.WriteLine("[GigaAm] Модель установлена и проверена (SHA-256 совпал).");
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[GigaAm] Не удалось скачать модель: {ex.Message}");
            return false;
        }
        finally
        {
            try { File.Delete(archivePath); } catch { /* файл мог уже удалиться */ }
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;
        _disposed = true;

        if (_recognizer != null)
        {
            try { _recognizer.Dispose(); } catch { /* уже освобождён */ }
            _recognizer = null;
        }

        _ensureLock.Dispose();
        GC.SuppressFinalize(this);
    }
}
