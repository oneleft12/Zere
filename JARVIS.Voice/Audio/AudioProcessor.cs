using NAudio.Wave;
using NAudio.Wave.SampleProviders;

namespace JARVIS.Voice.Audio;

/// <summary>
/// Профессиональная DSP-цепочка обработки голоса.
/// Делает звук «кинематографичным»: тёплый бас, чёткая подача, глубина.
/// </summary>
public static class AudioProcessor
{
    /// <summary>
    /// Полная обработка WAV-файла: ресемплинг → EQ → компрессия → нормализация → лимитер.
    /// Возвращает путь к обработанному файлу (или исходному при ошибке).
    /// </summary>
    public static string Process(string inputWavPath)
    {
        try
        {
            if (!File.Exists(inputWavPath))
                return inputWavPath;

            var outputDir = Path.GetDirectoryName(inputWavPath) ?? Path.GetTempPath();
            var outputPath = Path.Combine(outputDir,
                $"processed_{Path.GetFileName(inputWavPath)}");

            using var reader = new AudioFileReader(inputWavPath);
            var inputFormat = reader.WaveFormat;
            var outputSampleRate = inputFormat.SampleRate < 44100 ? 44100 : inputFormat.SampleRate;

            // === 1. Ресемплинг если нужно ===
            ISampleProvider chain = reader;
            if (inputFormat.SampleRate < 44100)
            {
                var targetFormat = new WaveFormat(44100, inputFormat.BitsPerSample, inputFormat.Channels);
                var resampler = new MediaFoundationResampler(reader, targetFormat);
                resampler.ResamplerQuality = 60;
                chain = SampleProviderConverters.ConvertWaveProviderSamples(resampler);
            }

            // === 2. Высокочастотный фильтр: убираем гул ниже 80 Гц ===
            chain = new HighPassFilter(chain, outputSampleRate, 80.0);

            // === 3. Параметрический EQ ===
            // Насыщенный бас (180 Гц) — тёплый «грудной» голос
            chain = new PeakingEqFilter(chain, outputSampleRate, 180.0, 3.5, 1.2);
            // Присутствие (3.2 кГц) — чёткость и разборчивость
            chain = new PeakingEqFilter(chain, outputSampleRate, 3200.0, 2.8, 1.5);
            // «Воздух» (10 кГц) — лёгкость и пространство
            chain = new PeakingEqFilter(chain, outputSampleRate, 10000.0, 1.5, 1.0);

            // === 4. Компрессор: выравниваем динамику ===
            chain = new CompressorSampleProvider(chain,
                thresholdDb: -18.0,
                ratio: 4.0,
                attackMs: 5.0,
                releaseMs: 100.0);

            // === 5. Читаем всё в память для нормализации ===
            var samples = ReadAllSamples(chain);

            // === 6. Нормализация: пик на -2 dBFS ===
            NormalizeSamples(samples, targetPeakDb: -2.0);

            // === 7. Мягкий лимитер ===
            ApplySoftLimiter(samples, ceilingDb: -0.5);

            // === 8. Запись в выходной файл ===
            var outputFormat = new WaveFormat(outputSampleRate, 16, 1);
            using (var writer = new WaveFileWriter(outputPath, outputFormat))
            {
                // Конвертируем float → short
                var shortBuffer = new short[samples.Length];
                for (int i = 0; i < samples.Length; i++)
                {
                    var clamped = Math.Clamp(samples[i], -1.0f, 1.0f);
                    shortBuffer[i] = (short)(clamped * short.MaxValue);
                }
                writer.WriteSamples(shortBuffer, 0, shortBuffer.Length);
            }

            return outputPath;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[AudioProcessor] Ошибка обработки: {ex.Message}");
            return inputWavPath;
        }
    }

    private static float[] ReadAllSamples(ISampleProvider source)
    {
        using var ms = new MemoryStream();
        var buffer = new float[4096];
        int read;
        while ((read = source.Read(buffer, 0, buffer.Length)) > 0)
        {
            var byteBuffer = new byte[read * sizeof(float)];
            Buffer.BlockCopy(buffer, 0, byteBuffer, 0, read * sizeof(float));
            ms.Write(byteBuffer, 0, byteBuffer.Length);
        }

        ms.Position = 0;
        var result = new float[ms.Length / sizeof(float)];
        var readBuffer = new byte[ms.Length];
        ms.Read(readBuffer, 0, readBuffer.Length);
        Buffer.BlockCopy(readBuffer, 0, result, 0, readBuffer.Length);
        return result;
    }

    private static void NormalizeSamples(float[] samples, double targetPeakDb)
    {
        var targetPeak = (float)Math.Pow(10, targetPeakDb / 20.0);
        var peak = float.Epsilon;
        for (int i = 0; i < samples.Length; i++)
        {
            var abs = Math.Abs(samples[i]);
            if (abs > peak) peak = abs;
        }

        if (peak < float.Epsilon) return;

        var gain = targetPeak / peak;
        for (int i = 0; i < samples.Length; i++)
            samples[i] *= gain;
    }

    private static void ApplySoftLimiter(float[] samples, double ceilingDb)
    {
        var ceiling = (float)Math.Pow(10, ceilingDb / 20.0);
        for (int i = 0; i < samples.Length; i++)
        {
            var x = samples[i];
            var abs = Math.Abs(x);
            if (abs > ceiling)
            {
                var sign = x > 0 ? 1.0f : -1.0f;
                var normalized = abs / ceiling;
                var limited = (float)(Math.Tanh(normalized * 2.0) * ceiling);
                samples[i] = sign * limited;
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// DSP-компоненты (потоковые)
// ═══════════════════════════════════════════════════════════════

/// <summary>
/// Высокочастотный фильтр (HPF) — 1-порядковый, убирает низкочастотный гул.
/// </summary>
internal class HighPassFilter : ISampleProvider
{
    private readonly ISampleProvider _source;
    private readonly float _a;
    private float _prevInput, _prevOutput;

    public WaveFormat WaveFormat => _source.WaveFormat;

    public HighPassFilter(ISampleProvider source, int sampleRate, double cutoffHz)
    {
        _source = source;
        var rc = 1.0 / (2.0 * Math.PI * cutoffHz);
        var dt = 1.0 / sampleRate;
        _a = (float)(rc / (rc + dt));
    }

    public int Read(float[] buffer, int offset, int count)
    {
        var samplesRead = _source.Read(buffer, offset, count);
        for (int i = 0; i < samplesRead; i++)
        {
            var input = buffer[offset + i];
            var output = _a * (_prevOutput + input - _prevInput);
            _prevInput = input;
            _prevOutput = output;
            buffer[offset + i] = output;
        }
        return samplesRead;
    }
}

/// <summary>
/// Параметрический эквалайзер (peaking) — Biquad 2-го порядка.
/// </summary>
internal class PeakingEqFilter : ISampleProvider
{
    private readonly ISampleProvider _source;
    private double _x1, _x2, _y1, _y2;
    private readonly double _b0, _b1, _b2, _a1, _a2;

    public WaveFormat WaveFormat => _source.WaveFormat;

    public PeakingEqFilter(ISampleProvider source, int sampleRate,
        double centerHz, double gainDb, double q)
    {
        _source = source;
        var a = Math.Pow(10, gainDb / 40.0);
        var w0 = 2.0 * Math.PI * centerHz / sampleRate;
        var sinW0 = Math.Sin(w0);
        var cosW0 = Math.Cos(w0);
        var alpha = sinW0 / (2.0 * q);

        var b0 = 1.0 + alpha * a;
        var b1 = -2.0 * cosW0;
        var b2 = 1.0 - alpha * a;
        var a0 = 1.0 + alpha / a;
        var a1 = -2.0 * cosW0;
        var a2 = 1.0 - alpha / a;

        _b0 = b0 / a0; _b1 = b1 / a0; _b2 = b2 / a0;
        _a1 = a1 / a0; _a2 = a2 / a0;
    }

    public int Read(float[] buffer, int offset, int count)
    {
        var samplesRead = _source.Read(buffer, offset, count);
        for (int i = 0; i < samplesRead; i++)
        {
            var x = buffer[offset + i];
            var y = _b0 * x + _b1 * _x1 + _b2 * _x2 - _a1 * _y1 - _a2 * _y2;
            _x2 = _x1; _x1 = x;
            _y2 = _y1; _y1 = y;
            buffer[offset + i] = (float)y;
        }
        return samplesRead;
    }
}

/// <summary>
/// Динамический компрессор — выравнивает громкость, делает голос «плотнее».
/// </summary>
internal class CompressorSampleProvider : ISampleProvider
{
    private readonly ISampleProvider _source;
    private readonly double _threshold;
    private readonly double _ratio;
    private readonly double _attackCoeff;
    private readonly double _releaseCoeff;
    private double _envelope;

    public WaveFormat WaveFormat => _source.WaveFormat;

    public CompressorSampleProvider(ISampleProvider source,
        double thresholdDb, double ratio, double attackMs, double releaseMs)
    {
        _source = source;
        _threshold = Math.Pow(10, thresholdDb / 20.0);
        _ratio = ratio;
        var sr = source.WaveFormat.SampleRate;
        _attackCoeff = Math.Exp(-1.0 / (attackMs * 0.001 * sr));
        _releaseCoeff = Math.Exp(-1.0 / (releaseMs * 0.001 * sr));
    }

    public int Read(float[] buffer, int offset, int count)
    {
        var samplesRead = _source.Read(buffer, offset, count);
        for (int i = 0; i < samplesRead; i++)
        {
            var x = buffer[offset + i];
            var abs = Math.Abs(x);

            var coeff = abs > _envelope ? _attackCoeff : _releaseCoeff;
            _envelope = coeff * _envelope + (1.0 - coeff) * abs;

            if (_envelope > _threshold)
            {
                var gain = _threshold + (_envelope - _threshold) / _ratio;
                var appliedGain = _envelope > 0 ? gain / _envelope : 1.0;
                buffer[offset + i] = (float)(x * Math.Max(appliedGain, 0.1));
            }
        }
        return samplesRead;
    }
}
