namespace JARVIS.Voice.Piper;

public class PiperService
{
    public bool IsLoaded { get; private set; }

    public void LoadVoice(string path)
    {
        if (!Directory.Exists(path))
            throw new DirectoryNotFoundException(path);

        IsLoaded = true;
    }

    public void Speak(string text)
    {
        if (!IsLoaded)
            return;

        Console.WriteLine($"[PIPER] {text}");
    }
}