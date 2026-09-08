using System.Text.Json;

namespace JARVIS.Core.Plugins;

public class PluginConfig
{
    public string ActivePersonalityId { get; set; } = "personality";
    public string ActivePersonalityStyle { get; set; } = "Friendly";
    public string ActiveCommandHandlerId { get; set; } = "";
    public Dictionary<string, string> PluginSettings { get; set; } = new();

    private static readonly string ConfigPath = Path.Combine(
        Directory.GetCurrentDirectory(),
        "config",
        "plugins.json");

    public static PluginConfig Load()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(ConfigPath)!);

        if (!File.Exists(ConfigPath))
        {
            var config = new PluginConfig();
            Save(config);
            return config;
        }

        var text = File.ReadAllText(ConfigPath);

        return JsonSerializer.Deserialize<PluginConfig>(
            text,
            new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            }) ?? new PluginConfig();
    }

    public static void Save(PluginConfig config)
    {
        var json = JsonSerializer.Serialize(
            config,
            new JsonSerializerOptions
            {
                WriteIndented = true
            });

        File.WriteAllText(ConfigPath, json);
    }

    public string GetSetting(string pluginId, string key, string defaultValue = "")
    {
        var fullKey = $"{pluginId}.{key}";
        return PluginSettings.TryGetValue(fullKey, out var value) ? value : defaultValue;
    }

    public void SetSetting(string pluginId, string key, string value)
    {
        var fullKey = $"{pluginId}.{key}";
        PluginSettings[fullKey] = value;
    }
}
