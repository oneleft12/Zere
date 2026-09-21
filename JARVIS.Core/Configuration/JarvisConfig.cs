using System.Text.Json;

namespace JARVIS.Core.Configuration;

public class JarvisConfig
{
    public string Version { get; set; } = "1.7.0";
    public string AssistantName { get; set; } = "JARVIS";
    public string Language { get; set; } = "ru";
    public string Model { get; set; } = "qwen3.5:2b";

    public bool VoiceEnabled { get; set; }
    public bool AutoMemory { get; set; }
    public bool DebugMode { get; set; }
    public int OllamaTimeoutMinutes { get; set; } = 10;

    public string LogLevel { get; set; } = "Info";

    private static readonly string ConfigPath =
        Path.Combine(
            Directory.GetCurrentDirectory(),
            "config",
            "config.json");

    public static JarvisConfig Load()
    {
        var configDir = Path.GetDirectoryName(ConfigPath);

        if (configDir != null)
            Directory.CreateDirectory(configDir);

        if (!File.Exists(ConfigPath))
        {
            var config = new JarvisConfig();

            var json = JsonSerializer.Serialize(
                config,
                new JsonSerializerOptions
                {
                    WriteIndented = true
                });

            File.WriteAllText(ConfigPath, json);

            return config;
        }

        var text = File.ReadAllText(ConfigPath);

        return JsonSerializer.Deserialize<JarvisConfig>(
            text,
            new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            }) ?? new JarvisConfig();
    }
}