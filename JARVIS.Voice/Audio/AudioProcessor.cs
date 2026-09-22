using NAudio.Wave;

namespace JARVIS.Voice.Audio;

/// <summary>
/// Профессиональная DSP-цепочка обработки голоса (TTS).
/// Делает звук «кинематографичным»: тёплый бас, чёткая подача, глубина.
/// </summary>
public static class AudioProcessor
{
    /// <summary>
    /// Полная обработка WAV-файла: ресемплинг → EQ → компрессия → нормализация → лимитер.
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
            var inputRate = reader.WaveFormat.SampleRate;
            var samples = ReadAllFloat(reader);

            // Ресемплинг до 44100 Hz если нужно
            var targetRate = inputRate < 44100 ? 44100 : inputRate;
            if (inputRate != targetRate)
                samples = Resample(samples, inputRate, targetRate);

            // === Кинематографичная DSP-цепочка (баритон) ===

            // 1. HPF: убираем гул и комнатный румбл ниже 75 Гц
            ApplyHighPass(samples, targetRate, 75.0);

            // 2. Шумовой гейт: подавляет шипение/фон в паузах (до нормализации)
            ApplyNoiseGate(samples, targetRate, thresholdDb: -42.0, reductionDb: 14.0);

            // 3. Чистка «эхо» и шума:
            //    - Срез боксовой резонансной составляющей (350 Гц -3 dB) — убирает «комнатность»
            //    - Десессер (6.5 кГц -2.5 dB) — убирает шипение/свист
            ApplyBiquadPeak(samples, targetRate, 350.0, -3.0, 1.1);
            ApplyBiquadPeak(samples, targetRate, 6500.0, -2.5, 1.6);

            // 4. Кинематографичный EQ:
            //    - Низкий бас (120 Гц +3.0 dB) — «бархатистость»
            //    - Тепло (250 Гц +1.5 dB) — наполненность
            //    - Присутствие (2.8 кГц +2.0 dB) — чёткая дикция
            //    - Воздух (9 кГц +0.5 dB) — лёгкость (снижено, меньше шипения)
            ApplyCinematicEq(samples, targetRate);

            // 5. Мульти-компрессор: два слоя для «давления»
            //    - Мягкий: 3:1, -20 dBFS (выравнивает)
            //    - Жёсткий: 6:1, -12 dBFS (сжимает пики)
            ApplyCompressor(samples, targetRate, thresholdDb: -20.0, ratio: 3.0);
            ApplyCompressor(samples, targetRate, thresholdDb: -12.0, ratio: 6.0);

            // 6. Нормализация пика -1.5 dBFS (максимальная громкость)
            Normalize(samples, targetPeakDb: -1.5);

            // 7. Мягкий лимитер -0.3 dBFS
            ApplySoftLimiter(samples, ceilingDb: -0.3);

            // 8. Гейт на выходе: добивает остаточный шип в тишине (после нормализации)
            ApplyNoiseGate(samples, targetRate, thresholdDb: -50.0, reductionDb: 18.0);

            // Запись в WAV
            var outputFormat = new WaveFormat(targetRate, 16, 1);
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
            Console.WriteLine($"[AudioProcessor] Ошибка обработки: {ex.Message}");
            return inputWavPath;
        }
    }

    // ─── Утилиты ────────────────────────────────────────────

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

    // ─── DSP-фильтры (in-memory) ────────────────────────────

    private static void ApplyHighPass(float[] samples, int sampleRate, double cutoffHz)
    {
        var rc = 1.0 / (2.0 * Math.PI * cutoffHz);
        var dt = 1.0 / sampleRate;
        var a = (float)(rc / (rc + dt));
        float prevIn = 0, prevOut = 0;

        for (int i = 0; i < samples.Length; i++)
        {
            var input = samples[i];
            var output = a * (prevOut + input - prevIn);
            prevIn = input;
            prevOut = output;
            samples[i] = output;
        }
    }

    private static void ApplyCinematicEq(float[] samples, int sampleRate)
    {
        // Кинематографичный EQ: 4 полосы для глубокого баритона
        var bands = new (double hz, double gainDb, double q)[]
        {
            (120.0,   3.0, 1.0),  // Низкий бас — «бархатистость»
            (250.0,   1.5, 1.2),  // Тепло — наполненность голоса
            (2800.0,  2.0, 1.4),  // Присутствие — чёткая дикция
            (9000.0,  0.5, 0.8)   // Воздух — лёгкость (умеренно, без шипения)
        };

        foreach (var (hz, gainDb, q) in bands)
            ApplyBiquadPeak(samples, sampleRate, hz, gainDb, q);
    }

    /// <summary>
    /// Шумовой гейт с плавной атакой/спадом — подавляет фон в паузах без щелчков.
    /// </summary>
    private static void ApplyNoiseGate(float[] samples, int sampleRate,
        double thresholdDb, double reductionDb)
    {
        var threshold = Math.Pow(10, thresholdDb / 20.0);
        var closedGain = Math.Pow(10, -reductionDb / 20.0);

        // Огибающая: быстрая атака 3ms, медленный спад 120ms (не режет хвосты слов)
        var envAttack = Math.Exp(-1.0 / (0.003 * sampleRate));
        var envRelease = Math.Exp(-1.0 / (0.120 * sampleRate));
        // Плавность гейта: открытие 5ms, закрытие 80ms (без щелчков)
        var openCoeff = Math.Exp(-1.0 / (0.005 * sampleRate));
        var closeCoeff = Math.Exp(-1.0 / (0.080 * sampleRate));

        double envelope = 0;
        double gain = 1.0;

        for (int i = 0; i < samples.Length; i++)
        {
            var abs = Math.Abs(samples[i]);
            var envCoeff = abs > envelope ? envAttack : envRelease;
            envelope = envCoeff * envelope + (1.0 - envCoeff) * abs;

            var targetGain = envelope >= threshold ? 1.0 : closedGain;
            var coeff = targetGain > gain ? openCoeff : closeCoeff;
            gain = coeff * gain + (1.0 - coeff) * targetGain;

            samples[i] = (float)(samples[i] * gain);
        }
    }

    private static void ApplyBiquadPeak(float[] samples, int sampleRate,
        double centerHz, double gainDb, double q)
    {
        var a = Math.Pow(10, gainDb / 40.0);
        var w0 = 2.0 * Math.PI * centerHz / sampleRate;
        var sinW0 = Math.Sin(w0);
        var cosW0 = Math.Cos(w0);
        var alpha = sinW0 / (2.0 * q);

        var b0 = (1.0 + alpha * a) / (1.0 + alpha / a);
        var b1 = (-2.0 * cosW0) / (1.0 + alpha / a);
        var b2 = (1.0 - alpha * a) / (1.0 + alpha / a);
        var a1 = (-2.0 * cosW0) / (1.0 + alpha / a);
        var a2 = (1.0 - alpha / a) / (1.0 + alpha / a);

        double x1 = 0, x2 = 0, y1 = 0, y2 = 0;

        for (int i = 0; i < samples.Length; i++)
        {
            var x = samples[i];
            var y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
            x2 = x1; x1 = x;
            y2 = y1; y1 = y;
            samples[i] = (float)y;
        }
    }

    private static void ApplyCompressor(float[] samples, int sampleRate,
        double thresholdDb, double ratio)
    {
        var threshold = Math.Pow(10, thresholdDb / 20.0);
        var attackCoeff = Math.Exp(-1.0 / (0.003 * sampleRate));  // Быстрый attack 3ms
        var releaseCoeff = Math.Exp(-1.0 / (0.250 * sampleRate)); // Медленный release 250ms — сохраняет хвост слов
        double envelope = 0;

        for (int i = 0; i < samples.Length; i++)
        {
            var x = samples[i];
            var abs = Math.Abs(x);

            var coeff = abs > envelope ? attackCoeff : releaseCoeff;
            envelope = coeff * envelope + (1.0 - coeff) * abs;

            if (envelope > threshold)
            {
                var gain = threshold + (envelope - threshold) / ratio;
                var applied = envelope > 0 ? gain / envelope : 1.0;
                samples[i] = (float)(x * Math.Max(applied, 0.1));
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
}
