using JARVIS.Core.Plugins.Interfaces;

namespace JARVIS.Core.Plugins;

public abstract class BasePlugin : IPlugin
{
    public abstract string Id { get; }
    public abstract string Name { get; }
    public abstract string Description { get; }
    public abstract string Version { get; }
    public abstract string Author { get; }
    public abstract PluginType Type { get; }

    public virtual void Initialize() { }
    public virtual void Dispose() { }
}
