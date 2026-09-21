using NAudio.Wave;

namespace JARVIS.Voice.Audio;

/// <summary>
/// Предобработка аудио для Whisper STT.
/// Убирает шум, выравнивает громкость, фильтрует частоты.
/// </summary>
public static class AudioPreprocessor
{
    /// <summary>
    /// Подготавливает WAV-файл для Whisper: ресемплинг → шумоподавление → нормализация.
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

            // Читаем все сэмплы как float через AudioFileReader
            using var reader = new AudioFileReader(inputWavPath);
            var inputRate = reader.WaveFormat.SampleRate;
            var samples = ReadAllFloat(reader);

            // Ресемплинг до 16 kHz (линейная интерполяция — достаточно для речи)
            if (inputRate != 16000)
                samples = Resample(samples, inputRate, 16000);

            // Noise Gate
            ApplyNoiseGate(samples, 16000, thresholdDb: -40.0);

            // AGC
            ApplyAgc(samples, targetLevelDb: -3.0, maxGainDb: 30.0);

            // EQ: усиление полосы речи
            // (пропускаем — для in-memory Biquad нужна отдельная реализация)

            // Soft Limiter
            ApplySoftLimiter(samples, ceilingDb: -1.0);

            // Нормализация
            Normalize(samples, targetPeakDb: -1.0);

            // Запись в 16-bit mono 16kHz
            var outputFormat = new WaveFormat(16000, 16, 1);
            using (var writer = new WaveFileWriter(outputPath, outputFormat))
            {
                for (int i = 0; i < samples.Length; i++)
                {
                    var clamped = Math.Clamp(samples[i], -1.0f, 1.0f);
                    writer.WriteSample(clamped);
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

    private static float[] ReadAllFloat(ISampleProvider source)
    {
        using var ms = new MemoryStream();
        var buf = new float[4096];
        int read;
        while ((read = source.Read(buf, 0, buf.Length)) > 0)
        {
            var bytes = new byte[read * sizeof(float)];
            Buffer.BlockCopy(buf, 0, bytes, 0, read * sizeof(float));
            ms.Write(bytes, 0, bytes.Length);
        }
        ms.Position = 0;
        var result = new float[ms.Length / sizeof(float)];
        var raw = new byte[ms.Length];
        ms.Read(raw, 0, raw.Length);
        Buffer.BlockCopy(raw, 0, result, 0, raw.Length);
        return result;
    }

    private static float[] Resample(float[] input, int fromRate, int toRate)
    {
        if (fromRate == toRate) return input;

        var ratio = (double)fromRate / toRate;
        var outputLength = (int)(input.Length / ratio);
        var output = new float[outputLength];

        for (int i = 0; i < outputLength; i++)
        {
            var pos = i * ratio;
            var idx = (int)pos;
            var frac = (float)(pos - idx);

            if (idx + 1 < input.Length)
                output[i] = input[idx] * (1 - frac) + input[idx + 1] * frac;
            else
                output[i] = input[idx];
        }
        return output;
    }

    private static void ApplyNoiseGate(float[] samples, int sampleRate, double thresholdDb)
    {
        var threshold = (float)Math.Pow(10, thresholdDb / 20.0);
        var attackCoeff = (float)Math.Exp(-1.0 / (0.001 * sampleRate));
        var releaseCoeff = (float)Math.Exp(-1.0 / (0.050 * sampleRate));
        float envelope = 0;
        bool gateOpen = false;

        for (int i = 0; i < samples.Length; i++)
        {
            var abs = Math.Abs(samples[i]);
            var coeff = abs > envelope ? attackCoeff : releaseCoeff;
            envelope = coeff * envelope + (1 - coeff) * abs;

            if (envelope > threshold) gateOpen = true;
            else if (envelope < threshold * 0.5f) gateOpen = false;

            if (!gateOpen) samples[i] *= 0.01f;
        }
    }

    private static void ApplyAgc(float[] samples, double targetLevelDb, double maxGainDb)
    {
        var target = (float)Math.Pow(10, targetLevelDb / 20.0);
        var maxGain = (float)Math.Pow(10, maxGainDb / 20.0);
        float gain = 1.0f;
        float envelope = 0;

        for (int i = 0; i < samples.Length; i++)
        {
            var abs = Math.Abs(samples[i]);
            envelope = 0.999f * envelope + 0.001f * abs;

            if (envelope > 0.001f)
            {
                var desired = Math.Min(target / envelope, maxGain);
                gain = 0.998f * gain + 0.002f * desired;
            }

            samples[i] *= gain;
        }
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
                samples[i] = sign * (float)(Math.Tanh(abs / ceiling * 2.0) * ceiling);
            }
        }
    }

    private static void Normalize(float[] samples, double targetPeakDb)
    {
        var target = (float)Math.Pow(10, targetPeakDb / 20.0);
        var peak = float.Epsilon;
        for (int i = 0; i < samples.Length; i++)
        {
            var abs = Math.Abs(samples[i]);
            if (abs > peak) peak = abs;
        }
        if (peak < float.Epsilon) return;
        var gain = target / peak;
        for (int i = 0; i < samples.Length; i++)
            samples[i] *= gain;
    }
}
