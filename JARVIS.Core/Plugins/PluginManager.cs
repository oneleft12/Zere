using System.Reflection;
using JARVIS.Core.Plugins.Interfaces;

namespace JARVIS.Core.Plugins;

public class PluginManager
{
    private readonly string _pluginsPath;
    private readonly List<IPlugin> _plugins = new();
    private readonly List<IPersonalityPlugin> _personalities = new();
    private readonly List<ICommandHandlerPlugin> _commandHandlers = new();

    public IReadOnlyList<IPlugin> Plugins => _plugins.AsReadOnly();
    public IReadOnlyList<IPersonalityPlugin> Personalities => _personalities.AsReadOnly();
    public IReadOnlyList<ICommandHandlerPlugin> CommandHandlers => _commandHandlers.AsReadOnly();

    public IPersonalityPlugin? ActivePersonality { get; private set; }

    public PluginManager(string? pluginsPath = null)
    {
        _pluginsPath = pluginsPath ?? Path.Combine(
            Directory.GetCurrentDirectory(),
            "plugins");

        Directory.CreateDirectory(_pluginsPath);
    }

    public void LoadAll()
    {
        _plugins.Clear();
        _personalities.Clear();
        _commandHandlers.Clear();

        LoadBuiltInPlugins();

        var dllFiles = Directory.GetFiles(_pluginsPath, "*.dll", SearchOption.AllDirectories);

        foreach (var dll in dllFiles)
        {
            try
            {
                LoadPlugin(dll);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[PluginManager] Ошибка загрузки {Path.GetFileName(dll)}: {ex.Message}");
            }
        }

        Console.WriteLine($"[PluginManager] Всего загружено: {_plugins.Count} плагинов.");
    }

    private void LoadBuiltInPlugins()
    {
        var assembly = Assembly.GetExecutingAssembly();

        var pluginTypes = assembly.GetTypes()
            .Where(t => typeof(IPlugin).IsAssignableFrom(t) && !t.IsAbstract && !t.IsInterface);

        foreach (var type in pluginTypes)
        {
            try
            {
                var plugin = (IPlugin)Activator.CreateInstance(type)!;
                plugin.Initialize();

                _plugins.Add(plugin);

                switch (plugin)
                {
                    case IPersonalityPlugin personality:
                        _personalities.Add(personality);
                        break;

                    case ICommandHandlerPlugin commandHandler:
                        _commandHandlers.Add(commandHandler);
                        break;
                }

                Console.WriteLine($"[PluginManager] Встроенный: {plugin.Name} v{plugin.Version} ({plugin.Type})");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[PluginManager] Ошибка загрузки встроенного плагина {type.Name}: {ex.Message}");
            }
        }
    }

    private void LoadPlugin(string dllPath)
    {
        var assembly = Assembly.LoadFrom(dllPath);

        var pluginTypes = assembly.GetTypes()
            .Where(t => typeof(IPlugin).IsAssignableFrom(t) && !t.IsAbstract && !t.IsInterface);

        foreach (var type in pluginTypes)
        {
            var plugin = (IPlugin)Activator.CreateInstance(type)!;
            plugin.Initialize();

            _plugins.Add(plugin);

            switch (plugin)
            {
                case IPersonalityPlugin personality:
                    _personalities.Add(personality);
                    break;

                case ICommandHandlerPlugin commandHandler:
                    _commandHandlers.Add(commandHandler);
                    break;
            }

            Console.WriteLine($"[PluginManager] Загружен: {plugin.Name} v{plugin.Version} ({plugin.Type})");
        }
    }

    public bool SetActivePersonality(string pluginId)
    {
        var personality = _personalities.FirstOrDefault(p => p.Id == pluginId);

        if (personality == null)
            return false;

        ActivePersonality = personality;
        Console.WriteLine($"[PluginManager] Активная личность: {personality.Name} | Стиль: {personality.Style}");
        return true;
    }

    public IPlugin? GetById(string id)
    {
        return _plugins.FirstOrDefault(p => p.Id == id);
    }

    public List<IPlugin> GetByType(PluginType type)
    {
        return _plugins.Where(p => p.Type == type).ToList();
    }

    public void DisposeAll()
    {
        foreach (var plugin in _plugins)
        {
            try
            {
                plugin.Dispose();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[PluginManager] Ошибка выгрузки {plugin.Name}: {ex.Message}");
            }
        }

        _plugins.Clear();
        _personalities.Clear();
        _commandHandlers.Clear();
    }
}
