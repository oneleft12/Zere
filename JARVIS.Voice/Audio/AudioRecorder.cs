using NAudio.Wave;
using System.IO;

namespace JARVIS.Voice.Audio;

public class AudioRecorder : IDisposable
{
    private WaveInEvent? _waveIn;
    private WaveFileWriter? _writer;

    /// <summary>
    /// Запись аудио с микрофона.
    /// Использует 16 kHz mono (стандарт Whisper) с оптимальными настройками.
    /// </summary>
    public async Task<string> RecordAsync(int seconds = 5, int sampleRate = 16000)
    {
        var folder = Path.Combine(
            Directory.GetCurrentDirectory(),
            "voice",
            "input");

        Directory.CreateDirectory(folder);

        var file = Path.Combine(folder, "record.wav");

        if (File.Exists(file))
            File.Delete(file);

        // Оптимальные настройки для Whisper STT
        var waveFormat = new WaveFormat(sampleRate, 16, 1);

        _waveIn = new WaveInEvent
        {
            WaveFormat = waveFormat,
            BufferMilliseconds = 50,     // Маленький буфер для низкой задержки
            NumberOfBuffers = 3,         // 3 буфера для плавности
            DeviceNumber = 0             // Дефолтный микрофон
        };

        _writer = new WaveFileWriter(file, waveFormat);

        var tcs = new TaskCompletionSource<bool>();

        try
        {
            _waveIn.DataAvailable += (_, e) =>
            {
                _writer.Write(e.Buffer, 0, e.BytesRecorded);
                _writer.Flush();
            };

            _waveIn.RecordingStopped += (_, e) =>
            {
                tcs.TrySetResult(true);
            };

            Console.WriteLine($"🎤 Слушаю {seconds} секунд...");

            _waveIn.StartRecording();

            // Ждём указанное время или отмены
            var delayTask = Task.Delay(seconds * 1000);
            var completedTask = await Task.WhenAny(delayTask, tcs.Task);

            _waveIn.StopRecording();

            // Даём время на завершение записи
            await Task.Delay(200);
        }
        finally
        {
            _writer.Dispose();
            _waveIn.Dispose();
        }

        // Проверяем качество записи
        var fileInfo = new FileInfo(file);
        if (fileInfo.Length < 1000) // Слишком маленький файл = проблема
        {
            Console.WriteLine("⚠️ Запись слишком тихая. Проверьте микрофон.");
        }

        Console.WriteLine("✅ Запись завершена.");

        return file;
    }

    /// <summary>
    /// Запись с автоматическим определением конца речи (VAD-подобное).
    /// Записывает до тишины или максимального времени.
    /// </summary>
    public async Task<string> RecordWithVadAsync(int maxSeconds = 10, int silenceMs = 1500)
    {
        var folder = Path.Combine(
            Directory.GetCurrentDirectory(),
            "voice",
            "input");

        Directory.CreateDirectory(folder);

        var file = Path.Combine(folder, "record.wav");

        if (File.Exists(file))
            File.Delete(file);

        var waveFormat = new WaveFormat(16000, 16, 1);

        _waveIn = new WaveInEvent
        {
            WaveFormat = waveFormat,
            BufferMilliseconds = 50,
            NumberOfBuffers = 3,
            DeviceNumber = 0
        };

        _writer = new WaveFileWriter(file, waveFormat);

        var samples = new List<float>();
        var lastSpeechTime = DateTime.MinValue;
        bool hasSpeech = false;

        try
        {
            _waveIn.DataAvailable += (_, e) =>
            {
                // Конвертируем байты в float samples
                var sampleCount = e.BytesRecorded / 2; // 16-bit = 2 bytes
                for (int i = 0; i < sampleCount; i++)
                {
                    var sample = BitConverter.ToInt16(e.Buffer, i * 2) / 32768f;
                    samples.Add(sample);
                }

                // Вычисляем RMS
                var rms = Math.Sqrt(samples.Skip(Math.Max(0, samples.Count - 8000)).Average(s => s * s));

                // Если RMS выше порога — есть речь
                if (rms > 0.02) // ~-34 dBFS
                {
                    hasSpeech = true;
                    lastSpeechTime = DateTime.Now;
                }

                // Записываем в файл
                _writer.Write(e.Buffer, 0, e.BytesRecorded);
                _writer.Flush();
            };

            Console.WriteLine("🎤 Говорите... (авто-остановка при тишине)");

            _waveIn.StartRecording();
            lastSpeechTime = DateTime.Now;

            var startTime = DateTime.Now;
            while ((DateTime.Now - startTime).TotalSeconds < maxSeconds)
            {
                await Task.Delay(100);

                // Если уже была речь и теперь тишина long enough
                if (hasSpeech &&
                    (DateTime.Now - lastSpeechTime).TotalMilliseconds > silenceMs)
                {
                    Console.WriteLine("🔇 Обнаружена тишина, останавливаю запись...");
                    break;
                }
            }

            _waveIn.StopRecording();
            await Task.Delay(200);
        }
        finally
        {
            _writer.Dispose();
            _waveIn.Dispose();
        }

        if (!hasSpeech)
        {
            Console.WriteLine("⚠️ Речь не обнаружена. Проверьте микрофон.");
        }
        else
        {
            Console.WriteLine("✅ Запись завершена.");
        }

        return file;
    }

    public void Dispose()
    {
        _waveIn?.Dispose();
        _writer?.Dispose();
        GC.SuppressFinalize(this);
    }
}
