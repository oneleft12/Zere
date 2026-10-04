using NAudio.Wave;

namespace JARVIS.Voice.Audio;

/// <summary>
/// DSP-цепочка обработки голоса (TTS).
/// Делает звук плотнее и «кинематографичнее», но без артефактов: один мягкий
/// компрессор вместо каскада, без шумовых гейтов и без апсемплинга.
/// </summary>
public static class AudioProcessor
{
    /// <summary>
    /// Обработка WAV-файла: HPF → корректирующий EQ → EQ → компрессия →
    /// нормализация → мягкий лимитер.
    ///
    /// Ресемплинг здесь намеренно НЕ делается. Piper отдаёт 22050 Гц, а прежний
    /// апсемпл 22050→44100 линейной интерполяцией (без анти-imaging фильтра)
    /// добавлял зеркальную копию спектра выше 11 кГц — это и был «металлический»
    /// призвук. Частота сэмплирования сохраняется как есть, ресемплинг отдан
    /// аудио-движку Windows (он делает это с полноценным фильтром).
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
            var sampleRate = reader.WaveFormat.SampleRate;
            var samples = ReadAllFloat(reader);

            // === DSP-цепочка (баритон, без артефактов) ===

            // 1. HPF: убираем гул и комнатный румбл ниже 75 Гц
            ApplyHighPass(samples, sampleRate, 75.0);

            // 2. Чистка «эхо» и шума:
            //    - Срез боксовой резонансной составляющей (350 Гц -3 dB) — убирает «комнатность»
            //    - Десессер (6.5 кГц -2.5 dB) — убирает шипение/свист
            ApplyBiquadPeak(samples, sampleRate, 350.0, -3.0, 1.1);
            ApplyBiquadPeak(samples, sampleRate, 6500.0, -2.5, 1.6);

            // 3. Кинематографичный EQ (умеренный: без «бочки» и без шипения)
            ApplyCinematicEq(samples, sampleRate);

            // 4. ОДИН мягкий компрессор 2.5:1 @ -18 dBFS.
            //    Атака 20 мс (было 3 мс): на 3 мс усиление успевало промодулироваться
            //    внутри периода голоса (~8 мс), что и давало металлическую грязь.
            //    Раньше здесь стояли ДВА компрессора подряд (3:1 и 6:1) — это была
            //    та самая «перекомпрессия».
            ApplyCompressor(samples, sampleRate,
                thresholdDb: -18.0, ratio: 2.5, attackMs: 20.0, releaseMs: 250.0);

            // 5. Нормализация пика -3 dBFS: запас по динамике вместо «стены» на -1.5
            Normalize(samples, targetPeakDb: -3.0);

            // 6. Мягкий лимитер -0.5 dBFS
            ApplySoftLimiter(samples, ceilingDb: -0.5);

            // Запись в WAV на исходной частоте (без ресемплинга)
            var outputFormat = new WaveFormat(sampleRate, 16, 1);
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
        // Кинематографичный EQ: 4 полосы (гейны умеренные — громкость даёт
        // нормализация, а не подъём полос)
        var bands = new (double hz, double gainDb, double q)[]
        {
            (120.0,   2.0, 1.0),  // Низкий бас — «бархатистость»
            (250.0,   1.0, 1.2),  // Тепло — наполненность голоса
            (2800.0,  1.5, 1.4),  // Присутствие — чёткая дикция
            (9000.0,  0.5, 0.8)   // Воздух — лёгкость (умеренно, без шипения)
        };

        foreach (var (hz, gainDb, q) in bands)
            ApplyBiquadPeak(samples, sampleRate, hz, gainDb, q);
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

    /// <summary>
    /// Один мягкий компрессор с медленной атакой: выравнивает громкость фразы,
    /// но не трогает форму волны внутри периода голоса (иначе — «металл»).
    /// </summary>
    private static void ApplyCompressor(float[] samples, int sampleRate,
        double thresholdDb, double ratio, double attackMs, double releaseMs)
    {
        var threshold = Math.Pow(10, thresholdDb / 20.0);
        var attackCoeff = Math.Exp(-1.0 / (attackMs / 1000.0 * sampleRate));
        var releaseCoeff = Math.Exp(-1.0 / (releaseMs / 1000.0 * sampleRate));
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
