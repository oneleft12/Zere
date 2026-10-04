namespace JARVIS.Voice.Audio;

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

    public string PiperVoice { get; set; } = "ru_RU-ruslan-medium";

    public int MicrophoneIndex { get; set; } = 0;

    public float Volume { get; set; } = 1.0f;

    public bool WakeWordEnabled { get; set; } = true;

    public string WakeWord { get; set; } = "джарвис";

    /// <summary>
    /// Включить DSP-обработку голоса (EQ, мягкая компрессия, нормализация).
    /// Делает звук более «кинематографичным». Значение приходит из config.json
    /// (ключ audioProcessing) через VoiceManager/панель и читается на каждое
    /// предложение — переключается без перезапуска. false = «сырой» выход piper.
    /// </summary>
    public bool AudioProcessing { get; set; } = true;

    /// <summary>
    /// Множитель скорости речи (1.0 = норма, меньше = быстрее, больше = медленнее).
    /// 1.15 — медленная, уверенная подача для кинематографичного стиля.
    /// Передаётся piper как --length_scale.
    /// </summary>
    public float SpeechSpeed { get; set; } = 1.15f;

    /// <summary>
    /// Пауза (в секундах) после каждого предложения во время синтеза
    /// (piper --sentence_silence). Меньше — отзывчивее.
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
}