using NAudio.Wave;
using NAudio.Wave.SampleProviders;

namespace JARVIS.Voice.Audio;

/// <summary>
/// Предобработка аудио для Whisper STT.
/// Убирает шум, выравнивает громкость, фильтрует частоты.
/// </summary>
public static class AudioPreprocessor
{
    /// <summary>
    /// Подготавливает WAV-файл для Whisper: ресемплинг → шумоподавление → нормализация.
    /// Возвращает путь к обработанному файлу (или исходному при ошибке).
    /// </summary>
    public static string ProcessForWhisper(string inputWavPath)
    {
        try
        {
            if (!File.Exists(inputWavPath))
                return inputWavPath;

            var outputDir = Path.GetDirectoryName(inputWavPath) ?? Path.GetTempPath();
            var outputPath = Path.Combine(outputDir,
                $"whisper_input_{Path.GetFileName(inputWavPath)}");

            using var reader = new AudioFileReader(inputWavPath);
            var format = reader.WaveFormat;

            ISampleProvider chain = reader;

            // === 1. Ресемплинг до 16 kHz (стандарт Whisper) ===
            if (format.SampleRate != 16000)
            {
                var targetFormat = new WaveFormat(16000, format.BitsPerSample, format.Channels);
                var resampler = new MediaFoundationResampler(reader, targetFormat);
                resampler.ResamplerQuality = 60;
                chain = new WaveToSampleProvider(resampler);
            }

            // === 2. Шумовой门: убираем фон и шум питания ===
            chain = new NoiseGateFilter(chain, 16000,
                gateThresholdDb: -40.0,
                attackMs: 1.0,
                releaseMs: 50.0);

            // === 3. AGC (Automatic Gain Control) ===
            chain = new AgcFilter(chain, 16000,
                targetLevelDb: -3.0,
                maxGainDb: 30.0,
                attackMs: 5.0,
                releaseMs: 200.0);

            // === 4. Эквализация для речи ===
            chain = new PeakingEqFilter(chain, 16000, 1000.0, 2.0, 1.0);

            // === 5. Лимитер: предотвращаем клиппинг ===
            chain = new SoftLimiterSampleProvider(chain, ceilingDb: -1.0);

            // Запись в 16-bit mono 16kHz (стандарт Whisper)
            var outputFormat = new WaveFormat(16000, 16, 1);
            using (var writer = new WaveFileWriter(outputPath, outputFormat))
            {
                var floatBuffer = new float[4096];
                int samplesRead;
                while ((samplesRead = chain.Read(floatBuffer, 0, floatBuffer.Length)) > 0)
                {
                    var shortBuffer = new short[samplesRead];
                    for (int i = 0; i < samplesRead; i++)
                    {
                        var clamped = Math.Clamp(floatBuffer[i], -1.0f, 1.0f);
                        shortBuffer[i] = (short)(clamped * short.MaxValue);
                    }
                    writer.WriteSamples(shortBuffer, 0, shortBuffer.Length);
                }
            }

            return outputPath;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[AudioPreprocessor] Ошибка: {ex.Message}");
            return inputWavPath;
        }
    }
}

/// <summary>
/// Шумовой门 (Noise Gate) — пропускает сигнал выше порога, блокирует тишину/шум.
/// </summary>
internal class NoiseGateFilter : ISampleProvider
{
    private readonly ISampleProvider _source;
    private readonly float _threshold;
    private readonly float _attackCoeff;
    private readonly float _releaseCoeff;
    private float _envelope;
    private bool _gateOpen;

    public WaveFormat WaveFormat => _source.WaveFormat;

    public NoiseGateFilter(ISampleProvider source, int sampleRate,
        double gateThresholdDb, double attackMs, double releaseMs)
    {
        _source = source;
        _threshold = (float)Math.Pow(10, gateThresholdDb / 20.0);
        _attackCoeff = (float)Math.Exp(-1.0 / (attackMs * 0.001 * sampleRate));
        _releaseCoeff = (float)Math.Exp(-1.0 / (releaseMs * 0.001 * sampleRate));
    }

    public int Read(float[] buffer, int offset, int count)
    {
        var samplesRead = _source.Read(buffer, offset, count);
        for (int i = 0; i < samplesRead; i++)
        {
            var input = buffer[offset + i];
            var abs = Math.Abs(input);

            var coeff = abs > _envelope ? _attackCoeff : _releaseCoeff;
            _envelope = coeff * _envelope + (1.0f - coeff) * abs;

            if (_envelope > _threshold)
            {
                _gateOpen = true;
            }
            else if (_envelope < _threshold * 0.5f)
            {
                _gateOpen = false;
            }

            buffer[offset + i] = _gateOpen ? input : input * 0.01f;
        }
        return samplesRead;
    }
}

/// <summary>
/// AGC (Automatic Gain Control) — автоматическая регулировка усиления.
/// </summary>
internal class AgcFilter : ISampleProvider
{
    private readonly ISampleProvider _source;
    private readonly float _targetLevel;
    private readonly float _maxGain;
    private readonly float _attackCoeff;
    private readonly float _releaseCoeff;
    private float _currentGain;
    private float _envelope;

    public WaveFormat WaveFormat => _source.WaveFormat;

    public AgcFilter(ISampleProvider source, int sampleRate,
        double targetLevelDb, double maxGainDb, double attackMs, double releaseMs)
    {
        _source = source;
        _targetLevel = (float)Math.Pow(10, targetLevelDb / 20.0);
        _maxGain = (float)Math.Pow(10, maxGainDb / 20.0);
        _currentGain = 1.0f;
        _attackCoeff = (float)Math.Exp(-1.0 / (attackMs * 0.001 * sampleRate));
        _releaseCoeff = (float)Math.Exp(-1.0 / (releaseMs * 0.001 * sampleRate));
    }

    public int Read(float[] buffer, int offset, int count)
    {
        var samplesRead = _source.Read(buffer, offset, count);
        for (int i = 0; i < samplesRead; i++)
        {
            var input = buffer[offset + i];
            var abs = Math.Abs(input);

            var coeff = abs > _envelope ? _attackCoeff : _releaseCoeff;
            _envelope = coeff * _envelope + (1.0f - coeff) * abs;

            if (_envelope > 0.001f)
            {
                var desiredGain = _targetLevel / _envelope;
                desiredGain = Math.Min(desiredGain, _maxGain);

                var gainCoeff = abs > _targetLevel ? _attackCoeff : _releaseCoeff;
                _currentGain = gainCoeff * _currentGain + (1.0f - gainCoeff) * desiredGain;
            }

            buffer[offset + i] = input * _currentGain;
        }
        return samplesRead;
    }
}

/// <summary>
/// Мягкий лимитер — «тёплая» сатурация вместо жёсткого клиппинга.
/// </summary>
internal class SoftLimiterSampleProvider : ISampleProvider
{
    private readonly ISampleProvider _source;
    private readonly float _ceiling;

    public WaveFormat WaveFormat => _source.WaveFormat;

    public SoftLimiterSampleProvider(ISampleProvider source, double ceilingDb)
    {
        _source = source;
        _ceiling = (float)Math.Pow(10, ceilingDb / 20.0);
    }

    public int Read(float[] buffer, int offset, int count)
    {
        var samplesRead = _source.Read(buffer, offset, count);
        for (int i = 0; i < samplesRead; i++)
        {
            var x = buffer[offset + i];
            var abs = Math.Abs(x);

            if (abs > _ceiling)
            {
                var sign = x > 0 ? 1.0f : -1.0f;
                var normalized = abs / _ceiling;
                var limited = (float)(Math.Tanh(normalized * 2.0) * _ceiling);
                buffer[offset + i] = sign * limited;
            }
        }
        return samplesRead;
    }
}
