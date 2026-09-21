using NAudio.Wave;

namespace JARVIS.Voice.Audio;

public class AudioPlayer : IDisposable
{
    private readonly object _lock = new();
    private WaveOutEvent? _output;
    private AudioFileReader? _reader;
    private bool _cleaningUp;

    public bool IsPlaying { get; private set; }

    public async Task PlayAsync(string wavFile, float volume = 1.0f)
    {
        if (!File.Exists(wavFile))
        {
            Console.WriteLine($"[AudioPlayer] Файл не найден: {wavFile}");
            return;
        }

        // Ensure any previous playback is cleaned up before starting new instance.
        Cleanup();

        try
        {
            _reader = new AudioFileReader(wavFile)
            {
                Volume = volume
            };

            _output = new WaveOutEvent();
            _output.Init(_reader);

            IsPlaying = true;
            _output.PlaybackStopped += (_, _) =>
            {
                IsPlaying = false;
                Cleanup();
            };

            _output.Play();

            while (IsPlaying)
            {
                await Task.Delay(100);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[AudioPlayer] Ошибка воспроизведения: {ex.Message}");
            Cleanup();
        }
    }

    public void Stop()
    {
        _output?.Stop();
        IsPlaying = false;
        Cleanup();
    }

    private void Cleanup()
    {
        lock (_lock)
        {
            if (_cleaningUp)
                return;

            _cleaningUp = true;

            try
            {
                _output?.Dispose();
                _reader?.Dispose();
                _output = null;
                _reader = null;
            }
            finally
            {
                _cleaningUp = false;
            }
        }
    }

    public void Dispose()
    {
        Stop();
        GC.SuppressFinalize(this);
    }
}
