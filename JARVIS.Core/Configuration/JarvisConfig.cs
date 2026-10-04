using System.Text.Json;

namespace JARVIS.Core.Configuration;

public class JarvisConfig
{
    public string Version { get; set; } = "1.7.0";
    public string AssistantName { get; set; } = "JARVIS";
    public string Language { get; set; } = "ru";
    public string Model { get; set; } = "qwen3.5:2b";

    public bool VoiceEnabled { get; set; }

    // Громкость голосового вывода 0.0–1.0 (ключ voiceVolume из config.json;
    // применяется к VoiceConfig.Volume). Раньше поля не было и Save()
    // молча удалял ключ из config.json.
    public double VoiceVolume { get; set; } = 0.5;

    public bool AutoMemory { get; set; } = true;
    public int OllamaTimeoutMinutes { get; set; } = 10;

    // ── LLM (Ollama) — параметры скорости/стабильности (анализ S5) ──

    /// <summary>
    /// keep_alive для Ollama (секунды, -1 — бессрочно). По умолчанию Ollama
    /// выгружает модель через 5 минут простоя, и следующий голосовой запрос
    /// платит +2…5 с на загрузку.
    /// </summary>
    public int LlmKeepAlive { get; set; } = -1;

    /// <summary>
    /// Лимит ответа в токенах в ГОЛОСОВОМ режиме (96 ≈ 1–2 предложения).
    /// В текстовом режиме лимит не применяется.
    /// </summary>
    public int LlmMaxTokens { get; set; } = 96;

    /// <summary>
    /// Таймаут запроса к Ollama в секундах. Для голоса прежние 10 минут
    /// недопустимы: пользователь ждёт молча (анализ S5).
    /// </summary>
    public int LlmTimeoutSeconds { get; set; } = 60;

    // ── TTS (Etap 2: klonirovanie golosa) ─────────────────
    // Движок озвучки: "pocket" — xVibePocketTTS (клонирование, потоковый PCM),
    // "piper" — классический синтез. При сбое pocket всегда откат на piper.
    public string TtsEngine { get; set; } = "pocket";

    // Путь к WAV-референсу голоса пользователя (пусто = встроенный голос).
    // Заполняется командой «записать голос».
    public string VoiceReferencePath { get; set; } = "";

    private static readonly string ConfigPath =
        Path.Combine(
            Directory.GetCurrentDirectory(),
            "config",
            "config.json");

    // Обе реализации пишут config.json в camelCase (как в существующем
    // файле): C# читает case-insensitive, Python — с нормализацией
    // регистра и подчёркиваний, поэтому формат записи обязателен для
    // взаимной читаемости.
    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    public static JarvisConfig Load()
    {
        var configDir = Path.GetDirectoryName(ConfigPath);

        if (configDir != null)
            Directory.CreateDirectory(configDir);

        if (!File.Exists(ConfigPath))
        {
            var config = new JarvisConfig();

            var json = JsonSerializer.Serialize(config, WriteOptions);

            File.WriteAllText(ConfigPath, json);

            return config;
        }

        var text = File.ReadAllText(ConfigPath);

        // Битый JSON не должен валить старт: откатываемся к дефолтам
        // (паритет с Python-порт, у которого такой откат уже был).
        try
        {
            return JsonSerializer.Deserialize<JarvisConfig>(
                text,
                new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = true
                }) ?? new JarvisConfig();
        }
        catch (JsonException)
        {
            return new JarvisConfig();
        }
    }

    public void Save()
    {
        var json = JsonSerializer.Serialize(this, WriteOptions);

        File.WriteAllText(ConfigPath, json);
    }
}