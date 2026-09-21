using System.Text;
using JARVIS.Voice.Audio;
using Whisper.net;

namespace JARVIS.Voice.Whisper;

public class WhisperService
{
    private readonly string _mediumModelPath;
    private readonly string _baseModelPath;
    private readonly Lazy<WhisperFactory> _factory;

    public string CurrentModel { get; private set; } = "medium";

    public WhisperService()
    {
        // Путь строится относительно AppContext.BaseDirectory с учётом структуры проекта:
        // bin/Debug/net10.0/ → ../../.. → корень решения, затем JARVIS.Voice/Models.
        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        var modelsDir = Path.Combine(root, "JARVIS.Voice", "Models");

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

    public async Task<string> TranscribeAsync(string wavFile)
    {
        if (!IsInstalled())
            return "Модель Whisper не найдена.";

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
}
