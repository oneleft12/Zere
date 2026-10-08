namespace ZERE.Voice.Audio;

public class VoiceConfig
{
    public bool Enabled { get; set; } = false;

    public string Language { get; set; } = "ru";

    /// <summary>
    /// Модель Whisper для распознавания: "base" (142 MB) или "medium" (1.5 GB).
    /// medium значительно точнее для русского языка.
    /// </summary>
    public string WhisperModel { get; set; } = "medium";

    /// <summary>
    /// Движок распознавания речи: "gigaam" — GigaAM-v3 punct (sherpa-onnx,
    /// основной, MIT; отчёт docs/STT_ENGINE_RESEARCH.md), "whisper" — откат
    /// на Whisper (ggml). Значение приходит из config.json (sttEngine) через
    /// VoiceManager.ConfigureStt; поле держит паритет с Python VoiceConfig.
    /// </summary>
    public string SttEngine { get; set; } = "gigaam";

    /// <summary>
    /// Профиль голоса ChatTTS. У ChatTTS нет именованных голосов: профиль —
    /// детерминированное зерно эмбеддинга говорящего (crc32 имени), поэтому
    /// один профиль всегда звучит одинаково. Паритет с Python VoiceConfig.
    /// </summary>
    public string ChatTtsVoice { get; set; } = "zere-standard";

    public int MicrophoneIndex { get; set; } = 0;

    public float Volume { get; set; } = 1.0f;

    public bool WakeWordEnabled { get; set; } = true;

    public string WakeWord { get; set; } = "зере";

    /// <summary>
    /// Включить DSP-обработку голоса (EQ, мягкая компрессия, нормализация).
    /// Делает звук более «кинематографичным». Значение приходит из config.json
    /// (ключ audioProcessing) через VoiceManager/панель и читается на каждое
    /// предложение — переключается без перезапуска. false = «сырой» выход TTS.
    /// </summary>
    public bool AudioProcessing { get; set; } = true;

    /// <summary>
    /// Множитель скорости речи (1.0 = норма, меньше = быстрее, больше = медленнее).
    /// 1.15 — медленная, уверенная подача для кинематографичного стиля.
    /// Передаётся ChatTTS как токен [speed_N] (дискретная шкала 1…9): 1.15 → 4.
    /// </summary>
    public float SpeechSpeed { get; set; } = 1.15f;

    /// <summary>
    /// Пауза (в секундах) после каждого предложения во время синтеза:
    /// сервер ChatTTS дописывает эту тишину в конец WAV-предложения.
    /// Меньше — отзывчивее.
    /// </summary>
    public float SentenceSilence { get; set; } = 0.2f;

    /// <summary>
    /// Пауза тишины (мс), после которой wake-детектор считает речь оконченной.
    /// Было жёсткие 1200 мс — каждый цикл платил 1.2 с сверху (анализ
    /// docs/VOICE_PERF_STABILITY_ANALYSIS.md, S4); 700 мс покрывает
    /// обычные межсловесные паузы и не рвёт фразу.
    /// </summary>
    public int WakeSilenceMs { get; set; } = 700;

    /// <summary>
    /// Пауза тишины (мс) для окончания голосовой команды (было 1500 мс).
    /// </summary>
    public int CommandSilenceMs { get; set; } = 800;

    // ── Слово-триггер (анализ S2: VAD+STT → keyword spotting) ──

    /// <summary>
    /// Движок слова-триггера: "auto" — стриминговый KWS на своей ONNX-модели
    /// (ZERE.Voice/WakeWord/models/wake_&lt;слово&gt;.onnx), если она есть и
    /// установлен onnxruntime; иначе прежний детектор на VAD + STT;
    /// "kws" — только KWS; "whisper" — прежний детектор (смена слова без
    /// обучения модели). Паритет с Python VoiceConfig, docs/WAKE_WORD.md.
    /// </summary>
    public string WakeEngine { get; set; } = "auto";

    /// <summary>Явный путь к ONNX-модели (пусто — папка моделей по слову).</summary>
    public string WakeModelPath { get; set; } = "";

    /// <summary>
    /// Порог вероятности, число кадров подряд и cooldown. 0 — значения из
    /// манифеста модели (их подбирает tools/wake_word/evaluate.py по метрике
    /// «FA/час при recall ≥ 97 %»).
    /// </summary>
    public float WakeThreshold { get; set; } = 0.0f;
    public int WakeMinConsecutive { get; set; } = 0;
    public int WakeCooldownMs { get; set; } = 0;

    /// <summary>
    /// Энергетическая отсечка тишины: пока RMS последних 300 мс ниже порога,
    /// модель не запускается вовсе (в тихой комнате — ноль работы).
    /// </summary>
    public bool WakeEnergyGate { get; set; } = true;
    public float WakeGateRms { get; set; } = 0.0015f;
}