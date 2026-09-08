namespace JARVIS.Voice.Audio;

public class VoiceConfig
{
    public bool Enabled { get; set; } = false;

    public string Language { get; set; } = "ru";

    public string WhisperModel { get; set; } = "ggml-base.bin";

    public string PiperVoice { get; set; } = "ru_RU-irina-medium";

    public int MicrophoneIndex { get; set; } = 0;

    public float Volume { get; set; } = 1.0f;

    public bool WakeWordEnabled { get; set; } = true;

    public string WakeWord { get; set; } = "джарвис";
}