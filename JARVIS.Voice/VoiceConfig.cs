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

    public string PiperVoice { get; set; } = "ru_RU-irina-medium";

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
    /// Значение 1.05 даёт более естественную, «размеренную» подачу.
    /// </summary>
    public float SpeechSpeed { get; set; } = 1.05f;
}