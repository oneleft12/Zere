using NAudio.Wave;
using System.IO;

namespace JARVIS.Voice.Audio;

public class AudioRecorder : IDisposable
{
    private WaveInEvent? _waveIn;
    private WaveFileWriter? _writer;

    public async Task<string> RecordAsync(int seconds = 5)
    {
        var folder = Path.Combine(
            Directory.GetCurrentDirectory(),
            "voice",
            "input");

        Directory.CreateDirectory(folder);

        var file = Path.Combine(folder, "record.wav");

        if (File.Exists(file))
            File.Delete(file);

        _waveIn = new WaveInEvent
        {
            WaveFormat = new WaveFormat(16000, 1)
        };

        _writer = new WaveFileWriter(file, _waveIn.WaveFormat);

        try
        {
            _waveIn.DataAvailable += (_, e) =>
            {
                _writer.Write(e.Buffer, 0, e.BytesRecorded);
                _writer.Flush();
            };

            Console.WriteLine($"🎤 Слушаю {seconds} секунд...");

            _waveIn.StartRecording();

            await Task.Delay(seconds * 1000);

            _waveIn.StopRecording();
        }
        finally
        {
            _writer.Dispose();
            _waveIn.Dispose();
        }

        Console.WriteLine("✅ Запись завершена.");

        return file;
    }

    public void Dispose()
    {
        _waveIn?.Dispose();
        _writer?.Dispose();
        GC.SuppressFinalize(this);
    }
}
