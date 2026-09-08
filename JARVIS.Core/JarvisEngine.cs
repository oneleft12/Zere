using JARVIS.Core.Handlers;

namespace JARVIS.Core;

public class JarvisEngine
{
    private readonly HandlerPipeline _pipeline;
    private readonly MemoryExtractor _extractor = new();

    public JarvisEngine()
    {
        _pipeline = new HandlerPipeline(new IJarvisHandler[]
        {
            new MemoryHandler(),
            new MemoryQueryHandler(),
            new ConversationHandler(),
            new ProcessHandler(),
            new WindowsHandler(),
            new FileHandler(),
            new GameHandler(),
            new VolumeHandler(),
            new AIHandler()
        });
    }

    public async Task<string> ProcessAsync(string message)
    {
        _extractor.TryExtract(message);

        var result = await _pipeline.HandleAsync(message);

        return result ?? "Команда не распознана.";
    }
}
