using ZERE.Core.Plugins.Interfaces;

namespace ZERE.Core.Plugins;

public abstract class BasePlugin : IPlugin
{
    public abstract string Id { get; }
    public abstract string Name { get; }
    public abstract string Description { get; }
    public abstract string Version { get; }
    public abstract string Author { get; }
    public abstract PluginType Type { get; }

    public virtual void Initialize() { }

    /// <summary>
    /// Кастомный паттерн очистки ресурсов плагина. Не реализует System.IDisposable напрямую —
    /// управляется PluginManager.DisposeAll() при перезагрузке/выключении.
    /// </summary>
    public virtual void Dispose() { }
}
