using Whisper.net;

namespace JARVIS.Voice.Whisper;

public class WhisperService
{
    private readonly string _modelPath;

    public WhisperService()
    {
        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        _modelPath = Path.Combine(root, "JARVIS.Voice", "Models", "ggml-base.bin");
    }

    public bool IsInstalled()
    {
        return File.Exists(_modelPath);
    }

    public async Task<string> TranscribeAsync(string wavFile)
    {
        if (!IsInstalled())
            return "Модель Whisper не найдена.";

        var factory = WhisperFactory.FromPath(_modelPath);

        using var processor = factory.CreateBuilder()
            .WithLanguage("ru")
            .Build();

        await using var stream = File.OpenRead(wavFile);

        var result = "";

        await foreach (var segment in processor.ProcessAsync(stream))
        {
            result += segment.Text + " ";
        }

        return result.Trim();
    }
}