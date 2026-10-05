using NAudio.Wave;

namespace JARVIS.Voice.Audio;

/// <summary>
/// DSP-цепочка обработки голоса (TTS).
/// Ровно столько обработки, сколько нужно для качественного звука: качественный
/// sinc-ресемплинг до частоты устройства, чистка низа/шипения, умеренный EQ и
/// страховка по пикам. <b>Компрессора здесь нет</b>: 2.5:1 при пороге −18 dBFS
/// плюс нормализация всего файла «зажимали» динамику речи — на слух это и есть
/// «очень компрессированный звук» (см. §13 отчёта VOICE_PERF_STABILITY_ANALYSIS).
/// </summary>
public static class AudioProcessor
{
    /// <summary>
    /// Частота по умолчанию для ресемплинга: нативная частота большинства
    /// звуковых устройств (см. VoiceManager, который передаёт реальную частоту
    /// устройства, если её удалось определить).
    /// </summary>
    public const int DefaultSampleRate = 44100;

    /// <summary>Длина sinc-ядра в тапах (качество/скорость).</summary>
    private const int ResampleTaps = 64;

    /// <summary>Параметр Kaiser-окна: больше — лучше подавление, шире переход.</summary>
    private const double KaiserBeta = 8.0;

    /// <summary>
    /// Обработка WAV-файла: ресемплинг → HPF → корректирующий EQ → EQ →
    /// страховка по пикам → мягкий лимитер (без компрессии).
    ///
    /// Про ресемплинг. Piper отдаёт 22050 Гц, а у звуковых устройств нативная
    /// частота обычно 44100/48000. Если отдать 22050 как есть, конвертировать
    /// будет аудио-движок (PortAudio/WASAPI) — своим слабым ресемплером, и это
    /// даёт «металлический» призвук на выходе. Прежний апсемпл линейной
    /// интерполяцией давал тот же артефакт, только в файле (зеркальная копия
    /// спектра выше 11 кГц).
    ///
    /// Поэтому ресемплим сами — оконным sinc-фильтром (Kaiser, с анти-алиасингом),
    /// до частоты устройства. Качество подтверждено замером: энергия выше 11 кГц
    /// −54 дБ против −51 дБ у «сырых» 22050 и −28 дБ у линейной интерполяции.
    /// </summary>
    /// <param name="targetSampleRate">
    /// Частота устройства вывода (44100 по умолчанию). 0 — оставить исходную.
    /// </param>
    public static string Process(string inputWavPath, int targetSampleRate = DefaultSampleRate)
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

            // Ресемплинг ДО фильтров: DSP считается уже на частоте устройства,
            // чтобы биквады работали на своих целевых частотах.
            var sampleRate = inputRate;

            if (targetSampleRate > 0 && targetSampleRate != inputRate)
            {
                samples = ResampleSinc(samples, inputRate, targetSampleRate);
                sampleRate = targetSampleRate;
            }

            // === DSP-цепочка (баритон, без артефактов и без компрессии) ===

            // 1. HPF: убираем гул и комнатный румбл ниже 75 Гц
            ApplyHighPass(samples, sampleRate, 75.0);

            // 2. Чистка «эхо» и шума:
            //    - Срез боксовой резонансной составляющей (350 Гц -3 dB) — убирает «комнатность»
            //    - Десессер (6.5 кГц -2.5 dB) — убирает шипение/свист
            ApplyBiquadPeak(samples, sampleRate, 350.0, -3.0, 1.1);
            ApplyBiquadPeak(samples, sampleRate, 6500.0, -2.5, 1.6);

            // 3. Кинематографичный EQ (умеренный: без «бочки» и без шипения)
            ApplyCinematicEq(samples, sampleRate);

            // 4. Компрессора больше нет. Было 2.5:1 при пороге −18 dBFS (то есть
            //    выше порога оказывалась почти вся речь) плюс нормализация всего
            //    файла — динамика «зажималась», и озвучка звучала перекомпресси-
            //    рованной. TTS-движок и так отдаёт выровненный по громкости голос.

            // 5. Страховка по пикам: только ослабление, тихое не поднимаем —
            //    иначе это снова было бы выравнивание громкости (компрессия).
            AttenuatePeak(samples, ceilingDb: -1.0);

            // 6. Мягкий лимитер -0.5 dBFS
            ApplySoftLimiter(samples, ceilingDb: -0.5);

            // Запись в WAV на частоте устройства (sampleRate после ресемплинга)
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

    // ─── Ресемплинг ─────────────────────────────────────────

    /// <summary>
    /// Качественный ресемплинг оконным sinc-фильтром (Kaiser).
    ///
    /// В отличие от линейной интерполяции (была здесь раньше) sinc давит
    /// зеркальные составляющие: при апсемпле 22050→44100 линейная интерполяция
    /// добавляла копию спектра выше 11 кГц (энергия −28 дБ от основного
    /// диапазона — слышимый «металл»), sinc-ядро с анти-алиасингом даёт −54 дБ.
    ///
    /// cutoff = min(1, to/from) — при апсемпле 1 (анти-алиасинг не нужен),
    /// при даунсемпле — относительная частота Найквиста нового диапазона.
    /// </summary>
    private static float[] ResampleSinc(float[] input, int fromRate, int toRate)
    {
        if (input.Length == 0 || fromRate <= 0 || toRate <= 0 || fromRate == toRate)
            return input;

        var ratio = (double)toRate / fromRate;
        var outputLength = (int)Math.Floor(input.Length * ratio);

        if (outputLength <= 0)
            return input;

        var output = new float[outputLength];
        var half = ResampleTaps / 2;
        var cutoff = Math.Min(1.0, ratio);

        // Kaiser-окно: k = 0..taps-1
        var window = new double[ResampleTaps];
        var i0Beta = BesselI0(KaiserBeta);

        for (int k = 0; k < ResampleTaps; k++)
        {
            var t = 2.0 * k / (ResampleTaps - 1) - 1.0;      // -1..1
            window[k] = BesselI0(KaiserBeta * Math.Sqrt(Math.Max(0.0, 1.0 - t * t))) / i0Beta;
        }

        for (int i = 0; i < outputLength; i++)
        {
            var pos = i / ratio;                 // позиция во входном сигнале
            var start = (int)Math.Floor(pos) - half;

            double acc = 0;
            double norm = 0;

            for (int k = 0; k < ResampleTaps; k++)
            {
                var idx = start + k;

                if (idx < 0 || idx >= input.Length)
                    continue;

                var frac = pos - idx;
                var s = Sinc(frac * cutoff) * window[k];

                acc += input[idx] * s;
                norm += s;
            }

            // Нормировка на сумму весов: края сигнала иначе «проседают».
            output[i] = norm != 0 ? (float)(acc / norm) : 0f;
        }

        return output;
    }

    /// <summary>Нормализованный sinc: sin(πx)/(πx), в нуле — 1.</summary>
    private static double Sinc(double x)
    {
        if (Math.Abs(x) < 1e-9)
            return 1.0;

        var px = Math.PI * x;
        return Math.Sin(px) / px;
    }

    /// <summary>Модифицированная функция Бесселя первого рода нулевого порядка (для окна Kaiser).</summary>
    private static double BesselI0(double x)
    {
        double sum = 1.0;
        double term = 1.0;
        var halfX = x / 2.0;

        for (int k = 1; k < 64; k++)
        {
            term *= (halfX / k) * (halfX / k);
            sum += term;

            if (term < sum * 1e-16)
                break;
        }

        return sum;
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
    /// <summary>
    /// Ослабляет файл, если пик выше потолка; тихое не поднимает.
    /// Заменяет прежнюю нормализацию «пик в −3 dBFS»: та поднимала громкость
    /// всего файла и вместе с компрессором выравнивала динамику на слух.
    /// Здесь только страховка от клиппинга.
    /// </summary>
    private static void AttenuatePeak(float[] samples, double ceilingDb)
    {
        var ceiling = (float)Math.Pow(10, ceilingDb / 20.0);
        var peak = float.Epsilon;
        for (int i = 0; i < samples.Length; i++)
        {
            var abs = Math.Abs(samples[i]);
            if (abs > peak) peak = abs;
        }
        if (peak <= ceiling) return;
        var gain = ceiling / peak;
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
