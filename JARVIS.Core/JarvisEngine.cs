using JARVIS.Core.Handlers;
using JARVIS.Core.Plugins;

namespace JARVIS.Core;

public class JarvisEngine
{
    private readonly HandlerPipeline _pipeline;
    private readonly MemoryExtractor _extractor;
    private readonly PluginManager _pluginManager;

    public PluginManager PluginManager => _pluginManager;

    public JarvisEngine(HandlerPipeline pipeline, MemoryExtractor extractor, PluginManager pluginManager)
    {
        _pipeline = pipeline;
        _extractor = extractor;
        _pluginManager = pluginManager;
    }

    public async Task<string> ProcessAsync(string message)
    {
        _extractor.TryExtract(message);

        var result = await _pipeline.HandleAsync(message);

        return result ?? "Команда не распознана.";
    }
}
