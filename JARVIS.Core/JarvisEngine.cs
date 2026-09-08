using JARVIS.Core.Handlers;
using JARVIS.Core.Plugins;

namespace JARVIS.Core;

public class JarvisEngine
{
    private readonly HandlerPipeline _pipeline;
    private readonly MemoryExtractor _extractor = new();
    private readonly PluginManager _pluginManager;
    private readonly PluginConfig _config;

    public PluginManager PluginManager => _pluginManager;
    public PluginConfig Config => _config;

    public JarvisEngine()
    {
        _config = PluginConfig.Load();
        _pluginManager = new PluginManager();
        _pluginManager.LoadAll();

        _pluginManager.SetActivePersonality(_config.ActivePersonalityId, _config.ActivePersonalityStyle);

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
            new AIHandler(_pluginManager)
        });
    }

    public async Task<string> ProcessAsync(string message)
    {
        _extractor.TryExtract(message);

        var result = await _pipeline.HandleAsync(message);

        return result ?? "Команда не распознана.";
    }
}
