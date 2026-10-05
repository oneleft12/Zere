using System.Diagnostics;
using System.Text;
using ZERE.Voice.Audio;
using Whisper.net;

namespace ZERE.Voice.Whisper;

public class WhisperService : ISttService
{
    private readonly string _mediumModelPath;
    private readonly string _baseModelPath;
    private readonly Lazy<WhisperFactory> _factory;
    private bool _disposed;

    public string CurrentModel { get; private set; } = "medium";

    public WhisperService()
    {
        // Путь строится относительно AppContext.BaseDirectory с учётом структуры проекта:
        // bin/Debug/net10.0/ → ../../.. → корень решения, затем ZERE.Voice/Models.
        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        var modelsDir = Path.Combine(root, "ZERE.Voice", "Models");

        _mediumModelPath = Path.Combine(modelsDir, "ggml-medium.bin");
        _baseModelPath = Path.Combine(modelsDir, "ggml-base.bin");

        // Используем medium если доступна, иначе base
        var modelPath = File.Exists(_mediumModelPath) ? _mediumModelPath : _baseModelPath;
        CurrentModel = File.Exists(_mediumModelPath) ? "medium" : "base";

        _factory = new Lazy<WhisperFactory>(() => WhisperFactory.FromPath(modelPath));
    }

    public bool IsInstalled()
    {
        return File.Exists(_mediumModelPath) || File.Exists(_baseModelPath);
    }

    /// <summary>
    /// Предзагрузка модели в память при старте (анализ S3): первая транскрибация
    /// не должна ждать загрузку ggml-файла. Вызывается в фоне, сбои не критичны.
    /// </summary>
    public bool Preload()
    {
        if (!IsInstalled())
            return false;

        try
        {
            _ = _factory.Value;
            Console.WriteLine($"[Voice] Whisper предзагружен (модель: {CurrentModel}).");
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Whisper] Не удалось предзагрузить модель: {ex.Message}");
            return false;
        }
    }

    /// <summary>
    /// Распознаёт WAV-файл. timeoutSeconds — защита от зависания (анализ F6):
    /// в C# раньше таймаута не было вовсе; по истечении возвращается пустой
    /// результат, а фоновая задача доработает и освободит ресурсы сама.
    /// </summary>
    public async Task<string> TranscribeAsync(string wavFile, int timeoutSeconds = 30)
    {
        if (!IsInstalled())
            return "Модель Whisper не найдена.";

        var sw = Stopwatch.StartNew();

        var work = Task.Run(() => TranscribeCoreAsync(wavFile));
        var finished = await Task.WhenAny(work, Task.Delay(TimeSpan.FromSeconds(timeoutSeconds)));

        if (finished != work)
        {
            // Наблюдаем за «осиротевшей» фоновой задачей, чтобы исключение
            // не осталось ненаблюденным после таймаута.
            _ = work.ContinueWith(
                t => _ = t.Exception,
                TaskContinuationOptions.OnlyOnFaulted);

            Console.WriteLine(
                $"[Whisper] Таймаут распознавания ({timeoutSeconds} с) — возвращаю пустой результат.");
            return "";
        }

        var result = await work;

        Console.WriteLine($"[Perf] STT={sw.ElapsedMilliseconds} мс (модель: {CurrentModel})");

        return result;
    }

    private async Task<string> TranscribeCoreAsync(string wavFile)
    {
        // Предобработка аудио для лучшего распознавания
        var processedFile = AudioPreprocessor.ProcessForWhisper(wavFile);

        try
        {
            var factory = _factory.Value;

            using var processor = factory.CreateBuilder()
                .WithLanguage("ru")
                .Build();

            await using var stream = File.OpenRead(processedFile);

            var result = new StringBuilder();

            await foreach (var segment in processor.ProcessAsync(stream))
            {
                var text = segment.Text.Trim();

                // Фильтруем пустые сегменты и артефакты
                if (!string.IsNullOrWhiteSpace(text) &&
                    text.Length > 1 &&
                    !text.All(c => c == ' ' || c == '.' || c == ','))
                {
                    result.Append(text);
                    result.Append(' ');
                }
            }

            return result.ToString().Trim();
        }
        finally
        {
            // Удаляем обработанный файл
            if (processedFile != wavFile)
            {
                try { File.Delete(processedFile); } catch { }
            }
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;
        _disposed = true;

        // Нативная память ggml освобождается через фабрику (анализ F3).
        if (_factory.IsValueCreated)
        {
            try { _factory.Value.Dispose(); } catch { /* фабрика уже освобождена */ }
        }

        GC.SuppressFinalize(this);
    }
}
