namespace ZERE.Core.Plugins.Interfaces;

public interface IPlugin
{
    string Id { get; }
    string Name { get; }
    string Description { get; }
    string Version { get; }
    string Author { get; }
    PluginType Type { get; }
    void Initialize();
    void Dispose();
}

public enum PluginType
{
    Personality,
    CommandHandler,
    MemoryProvider,
    VoiceEngine,
    Other
}
