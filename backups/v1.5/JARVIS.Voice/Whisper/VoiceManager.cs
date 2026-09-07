using JARVIS.Voice.Whisper;

namespace JARVIS.Voice.Audio;

public class VoiceManager
{
    private readonly AudioRecorder _recorder = new();
    private readonly WhisperService _whisper = new();

    public bool IsInstalled()
    {
        return _whisper.IsInstalled();
    }

    public async Task<string> ListenAsync()
{
    var wav = await _recorder.RecordAsync();

    Console.WriteLine("🧠 Распознаю речь...");

    return await _whisper.TranscribeAsync(wav);
}
}