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

    public string PiperVoice { get; set; } = "ru_RU-ruslan-medium";

    public int MicrophoneIndex { get; set; } = 0;

    public float Volume { get; set; } = 1.0f;

    public bool WakeWordEnabled { get; set; } = true;

    public string WakeWord { get; set; } = "джарвис";

    /// <summary>
    /// Включить DSP-обработку голоса (EQ, компрессия, нормализация).
    /// Делает звук более «кинематографичным».
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
}