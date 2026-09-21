using NAudio.Wave;
using System.Collections.Concurrent;

namespace JARVIS.Voice.Audio;

/// <summary>
/// Непрерывный записывающий устройство с круговым буфером и VAD.
/// Не пересоздаёт WaveInEvent — одна запись на весь сеанс.
/// Буфер хранит последние N секунд аудио для извлечения сегментов.
/// </summary>
public class ContinuousAudioRecorder : IDisposable
{
    private WaveInEvent? _waveIn;
    private readonly object _lock = new();

    // Круговой буфер: хранит float сэмплы (16kHz mono)
    private float[] _ringBuffer = Array.Empty<float>();
    private int _writePos;
    private int _totalSamplesWritten;
    private int _bufferCapacity;

    // VAD
    private float _speechThreshold = 0.015f; // ~-36 dBFS
    private bool _isSpeech;
    private DateTime _speechStartTime;
    private DateTime _lastSpeechTime;

    // Состояние
    private volatile bool _isRecording;
    private volatile bool _disposed;

    public bool IsRecording => _isRecording;
    public bool IsSpeechDetected => _isSpeech;

    /// <summary>
    /// Запуск непрерывной записи в круговой буфер.
    /// </summary>
    /// <param name="bufferSeconds">Размер буфера в секундах (по умолчанию 10)</param>
    /// <param name="sampleRate">Частота дискретизации (16kHz для Whisper)</param>
    public void StartContinuousRecording(int bufferSeconds = 10, int sampleRate = 16000)
    {
        lock (_lock)
        {
            if (_isRecording) return;

            _bufferCapacity = sampleRate * bufferSeconds;
            _ringBuffer = new float[_bufferCapacity];
            _writePos = 0;
            _totalSamplesWritten = 0;
            _isSpeech = false;

            var waveFormat = new WaveFormat(sampleRate, 16, 1);

            _waveIn = new WaveInEvent
            {
                WaveFormat = waveFormat,
                BufferMilliseconds = 50,
                NumberOfBuffers = 3,
                DeviceNumber = 0
            };

            _waveIn.DataAvailable += OnDataAvailable;
            _waveIn.RecordingStopped += OnRecordingStopped;

            _waveIn.StartRecording();
            _isRecording = true;
        }
    }

    /// <summary>
    /// Остановка непрерывной записи.
    /// </summary>
    public void StopContinuousRecording()
    {
        lock (_lock)
        {
            if (!_isRecording || _waveIn == null) return;

            try
            {
                _waveIn.StopRecording();
            }
            catch { }

            _isRecording = false;
        }
    }

    /// <summary>
    /// Извлекает последние N секунд аудио из кругового буфера.
    /// </summary>
    public float[] ExtractRecentAudio(float seconds)
    {
        lock (_lock)
        {
            if (_ringBuffer.Length == 0 || _totalSamplesWritten == 0)
                return Array.Empty<float>();

            var sampleRate = _waveIn?.WaveFormat.SampleRate ?? 16000;
            var samplesToExtract = Math.Min(
                (int)(sampleRate * seconds),
                Math.Min(_totalSamplesWritten, _bufferCapacity));

            var result = new float[samplesToExtract];
            var readPos = (_writePos - samplesToExtract + _bufferCapacity) % _bufferCapacity;

            for (int i = 0; i < samplesToExtract; i++)
            {
                result[i] = _ringBuffer[(readPos + i) % _bufferCapacity];
            }

            return result;
        }
    }

    /// <summary>
    /// Извлекает аудио как массив byte (WAV-формат) для сохранения в файл.
    /// </summary>
    public byte[] ExtractRecentAudioBytes(float seconds)
    {
        var samples = ExtractRecentAudio(seconds);
        if (samples.Length == 0) return Array.Empty<byte>();

        var sampleRate = _waveIn?.WaveFormat.SampleRate ?? 16000;

        // Конвертируем float[] в byte[] (16-bit PCM)
        var byteCount = samples.Length * 2;
        var bytes = new byte[byteCount];

        for (int i = 0; i < samples.Length; i++)
        {
            var clamped = Math.Clamp(samples[i], -1f, 1f);
            var sample16 = (short)(clamped * 32767);
            bytes[i * 2] = (byte)(sample16 & 0xFF);
            bytes[i * 2 + 1] = (byte)((sample16 >> 8) & 0xFF);
        }

        return bytes;
    }

    /// <summary>
    /// Сохраняет последние N секунд аудио в WAV-файл и возвращает путь.
    /// </summary>
    public string SaveRecentAudio(float seconds, string? filePath = null)
    {
        var bytes = ExtractRecentAudioBytes(seconds);
        if (bytes.Length == 0) return string.Empty;

        var sampleRate = _waveIn?.WaveFormat.SampleRate ?? 16000;
        var waveFormat = new WaveFormat(sampleRate, 16, 1);

        filePath ??= Path.Combine(
            Directory.GetCurrentDirectory(),
            "voice", "input",
            $"wake_{DateTime.Now:yyyyMMdd_HHmmss}.wav");

        Directory.CreateDirectory(Path.GetDirectoryName(filePath)!);

        using (var writer = new WaveFileWriter(filePath, waveFormat))
        {
            writer.Write(bytes, 0, bytes.Length);
        }

        return filePath;
    }

    /// <summary>
    /// Вычисляет RMS энергии последних N секунд.
    /// </summary>
    public float GetRecentEnergy(float seconds)
    {
        var samples = ExtractRecentAudio(seconds);
        if (samples.Length == 0) return 0f;

        double sum = 0;
        for (int i = 0; i < samples.Length; i++)
            sum += samples[i] * samples[i];

        return (float)Math.Sqrt(sum / samples.Length);
    }

    /// <summary>
    /// Порог能量 для определения речи.
    /// </summary>
    public float SpeechThreshold
    {
        get => _speechThreshold;
        set => _speechThreshold = value;
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs e)
    {
        if (_disposed || !_isRecording) return;

        var sampleCount = e.BytesRecorded / 2; // 16-bit = 2 bytes

        lock (_lock)
        {
            for (int i = 0; i < sampleCount; i++)
            {
                var sample = BitConverter.ToInt16(e.Buffer, i * 2) / 32768f;
                _ringBuffer[_writePos] = sample;
                _writePos = (_writePos + 1) % _bufferCapacity;
                _totalSamplesWritten++;
            }
        }

        // VAD: вычисляем RMS последних 500ms
        var rms = GetRecentEnergy(0.5f);

        if (rms > _speechThreshold)
        {
            if (!_isSpeech)
            {
                _isSpeech = true;
                _speechStartTime = DateTime.Now;
            }
            _lastSpeechTime = DateTime.Now;
        }
        else if (_isSpeech && (DateTime.Now - _lastSpeechTime).TotalMilliseconds > 1500)
        {
            _isSpeech = false;
        }
    }

    private void OnRecordingStopped(object? sender, StoppedEventArgs e)
    {
        _isRecording = false;
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;

        lock (_lock)
        {
            _isRecording = false;

            if (_waveIn != null)
            {
                try
                {
                    _waveIn.StopRecording();
                    _waveIn.DataAvailable -= OnDataAvailable;
                    _waveIn.RecordingStopped -= OnRecordingStopped;
                    _waveIn.Dispose();
                }
                catch { }

                _waveIn = null;
            }
        }

        GC.SuppressFinalize(this);
    }
}
