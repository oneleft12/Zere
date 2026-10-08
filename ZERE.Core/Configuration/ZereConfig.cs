using System.Text.Json;

namespace ZERE.Core.Configuration;

public class ZereConfig
{
    public string Version { get; set; } = "1.8.0";
    public string AssistantName { get; set; } = "ZERE";
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
    // "chattts" — ChatTTS (нейросетевой синтез, замена Piper; ленивая загрузка).
    // При сбое pocket всегда откат на chattts.
    public string TtsEngine { get; set; } = "pocket";

    // ── STT (отчёт docs/STT_ENGINE_RESEARCH.md, §5) ───────
    // Движок распознавания речи: "gigaam" — GigaAM-v3 punct (sherpa-onnx,
    // основной; модель качается установщиком или при первой предзагрузке),
    // "whisper" — откат на Whisper (ggml). При сбое gigaam всегда откат
    // на whisper — зеркало отката TTS-движков (pocket→chattts).
    public string SttEngine { get; set; } = "gigaam";

    // Путь к WAV-референсу голоса пользователя (пусто = встроенный голос).
    // Заполняется командой «записать голос».
    public string VoiceReferencePath { get; set; } = "";

    // ── Слово-триггер (анализ S2: VAD+STT → keyword spotting) ──
    // Движок: "auto" — стриминговый KWS на своей ONNX-модели
    // (ZERE.Voice/WakeWord/models/wake_<слово>.onnx), если она есть, иначе
    // прежний детектор на VAD + STT; "kws" — только KWS (нет модели →
    // предупреждение и откат на STT); "whisper" — прежний детектор.
    // Паритет с Python ZereConfig, подробности — docs/WAKE_WORD.md.
    public string WakeEngine { get; set; } = "auto";
    public string WakeModelPath { get; set; } = "";

    // Порог вероятности, число кадров подряд и cooldown. 0 — значения из
    // манифеста модели (их подбирает tools/wake_word/evaluate.py по метрике
    // «FA/час при recall ≥ 97 %»).
    public float WakeThreshold { get; set; } = 0.0f;
    public int WakeMinConsecutive { get; set; } = 0;
    public int WakeCooldownMs { get; set; } = 0;

    // Энергетическая отсечка тишины: пока RMS последних 300 мс ниже порога,
    // модель не запускается вовсе (в тихой комнате — ноль работы).
    public bool WakeEnergyGate { get; set; } = true;

    // DSP-обработка озвучки ChatTTS (EQ + мягкий компрессор + нормализация).
    // Ключ config.json: audioProcessing. Читается на каждое предложение
    // (VoiceManager), поэтому переключается на лету из панели; false —
    // «сырой» выход TTS без единого фильтра.
    public bool AudioProcessing { get; set; } = true;

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

    public static ZereConfig Load()
    {
        var configDir = Path.GetDirectoryName(ConfigPath);

        if (configDir != null)
            Directory.CreateDirectory(configDir);

        if (!File.Exists(ConfigPath))
        {
            var config = new ZereConfig();

            var json = JsonSerializer.Serialize(config, WriteOptions);

            File.WriteAllText(ConfigPath, json);

            return config;
        }

        var text = File.ReadAllText(ConfigPath);

        // Битый JSON не должен валить старт: откатываемся к дефолтам
        // (паритет с Python-порт, у которого такой откат уже был).
        try
        {
            return JsonSerializer.Deserialize<ZereConfig>(
                text,
                new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = true
                }) ?? new ZereConfig();
        }
        catch (JsonException)
        {
            return new ZereConfig();
        }
    }

    public void Save()
    {
        var json = JsonSerializer.Serialize(this, WriteOptions);

        File.WriteAllText(ConfigPath, json);
    }
}