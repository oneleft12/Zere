using NAudio.Wave;

namespace ZERE.Voice.Audio;

/// <summary>
/// Непрерывный записывающий устройство с круговым буфером и VAD.
/// Не пересоздаёт WaveInEvent — одна запись на весь сеанс.
/// Адаптивный VAD: первый 2 сек замеряет шум, затем порог = шум × 2.5.
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

    // VAD — адаптивный порог
    private float _noiseFloor = 0.005f;    // Уровень шума (среднее за калибровку)
    private float _speechThreshold = 0.010f; // Порог = средний шум × 2
    private double _calibSum;               // Сумма RMS для среднего при калибровке
    private int _calibCount;                // Количество замеров при калибровке
    private bool _isSpeech;
    private bool _calibrated;
    private DateTime _speechStartTime;
    private DateTime _lastSpeechTime;

    // Быстрый RMS — инкрементальный расчёт без пересканирования буфера
    private double _rmsSum;
    private int _rmsWindowSamples;
    private const int RmsWindowMs = 400; // Окно RMS 400ms
    private DateTime _rmsWindowStart;

    // Состояние
    private volatile bool _isRecording;
    private volatile bool _disposed;

    // Слушатели аудио (streaming KWS): получают блок float сразу из callback'а
    // NAudio, поэтому обязаны быть мгновенными (копия в свой буфер), а их
    // исключение не должно ронять запись.
    private readonly List<Action<float[]>> _listeners = new();

    public bool IsRecording => _isRecording;
    public bool IsSpeechDetected => _isSpeech;
    public float LastRms { get; private set; }

    /// <summary>Частота записи (нужна слушателям для расчёта окон и hop).</summary>
    public int SampleRate => _waveIn?.WaveFormat.SampleRate ?? 16000;

    /// <summary>Регистрирует слушателя блоков аудио (float, 16 кГц, моно).</summary>
    public void AddListener(Action<float[]> listener)
    {
        lock (_listeners)
        {
            if (!_listeners.Contains(listener))
                _listeners.Add(listener);
        }
    }

    /// <summary>Снимает слушателя (повторное снятие безопасно).</summary>
    public void RemoveListener(Action<float[]> listener)
    {
        lock (_listeners)
            _listeners.Remove(listener);
    }

    private void NotifyListeners(float[] block)
    {
        Action<float[]>[] listeners;

        lock (_listeners)
            listeners = _listeners.ToArray();

        foreach (var listener in listeners)
        {
            try
            {
                listener(block);
            }
            catch
            {
                // Аудиозахват важнее слушателя: сбой KWS не должен глушить запись.
            }
        }
    }

    /// <summary>
    /// Запуск непрерывной записи в круговой буфер.
    /// </summary>
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
            _calibrated = false;
            _noiseFloor = 0.005f;
            _speechThreshold = 0.010f;
            _calibSum = 0;
            _calibCount = 0;

            // Сброс окна RMS
            _rmsSum = 0;
            _rmsWindowSamples = 0;
            _rmsWindowStart = DateTime.Now;

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

            try { _waveIn.StopRecording(); }
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
                result[i] = _ringBuffer[(readPos + i) % _bufferCapacity];

            return result;
        }
    }

    /// <summary>
    /// Извлекает аудио как byte[] (16-bit PCM) для WAV.
    /// </summary>
    public byte[] ExtractRecentAudioBytes(float seconds)
    {
        var samples = ExtractRecentAudio(seconds);
        if (samples.Length == 0) return Array.Empty<byte>();

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
    /// Сохраняет последние N секунд аудио в WAV-файл.
    /// </summary>
    public string SaveRecentAudio(float seconds, string? filePath = null)
    {
        var bytes = ExtractRecentAudioBytes(seconds);
        if (bytes.Length == 0) return string.Empty;

        var sampleRate = _waveIn?.WaveFormat.SampleRate ?? 16000;
        var waveFormat = new WaveFormat(sampleRate, 16, 1);

        filePath ??= Path.Combine(
            Directory.GetCurrentDirectory(), "voice", "input",
            $"wake_{DateTime.Now:yyyyMMdd_HHmmss}.wav");

        Directory.CreateDirectory(Path.GetDirectoryName(filePath)!);

        using (var writer = new WaveFileWriter(filePath, waveFormat))
            writer.Write(bytes, 0, bytes.Length);

        return filePath;
    }

    /// <summary>
    /// Ручная установка порога (перезаписывает адаптивный).
    /// </summary>
    public void SetThreshold(float threshold)
    {
        _speechThreshold = threshold;
        _calibrated = true; // Блокирует адаптивную подстройку
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs e)
    {
        if (_disposed || !_isRecording) return;

        var sampleCount = e.BytesRecorded / 2;
        var now = DateTime.Now;
        var samples = new float[sampleCount];

        lock (_lock)
        {
            // Пишем в круговой буфер + считаем инкрементальный RMS
            for (int i = 0; i < sampleCount; i++)
            {
                var sample = BitConverter.ToInt16(e.Buffer, i * 2) / 32768f;
                samples[i] = sample;
                _ringBuffer[_writePos] = sample;
                _writePos = (_writePos + 1) % _bufferCapacity;
                _totalSamplesWritten++;

                // Инкрементальный RMS
                _rmsSum += sample * sample;
                _rmsWindowSamples++;
            }
        }

        // Слушатели (streaming KWS) получают блок сразу, не дожидаясь окна RMS
        NotifyListeners(samples);

        // Проверяем окно RMS каждые ~400ms
        var elapsed = (now - _rmsWindowStart).TotalMilliseconds;
        if (elapsed < RmsWindowMs) return;

        float rms;
        lock (_lock)
        {
            rms = _rmsWindowSamples > 0
                ? (float)Math.Sqrt(_rmsSum / _rmsWindowSamples)
                : 0f;

            _rmsSum = 0;
            _rmsWindowSamples = 0;
            _rmsWindowStart = now;
        }

        LastRms = rms;

        // === Адаптивная калибровка (первые 2 сек — замер шума) ===
        if (!_calibrated && _totalSamplesWritten < 32000) // 2 сек при 16kHz
        {
            _calibSum += rms;
            _calibCount++;

            // После 2 сек устанавливаем порог по СРЕДНЕМУ шуму комнаты.
            // Максимум ломался на случайном всплеске → порог непроходимо высоким.
            if (_totalSamplesWritten >= 30000)
            {
                var meanNoise = _calibCount > 0 ? (float)(_calibSum / _calibCount) : 0.005f;
                _noiseFloor = meanNoise;
                _speechThreshold = Math.Clamp(meanNoise * 2.0f, 0.005f, 0.04f);
                _calibrated = true;
            }
            return; // Ещё калибруемся — не триггерим
        }

        // === VAD логика ===
        if (rms > _speechThreshold)
        {
            if (!_isSpeech)
            {
                _isSpeech = true;
                _speechStartTime = now;
            }
            _lastSpeechTime = now;
        }
        else if (_isSpeech && (now - _lastSpeechTime).TotalMilliseconds > 1500)
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
            _listeners.Clear();

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
