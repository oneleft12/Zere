using ZERE.Voice.Audio;
using ZERE.Voice.Whisper;

namespace ZERE.Voice.WakeWord;

/// <summary>
/// Выбор движка слова-триггера (порт Python-фабрики
/// <c>zere/voice/wakeword/__init__.py</c>).
///
/// Модель KWS лежит в <c>ZERE.Voice/WakeWord/models/wake_&lt;слово&gt;.onnx</c>
/// (файл &lt; 1 МБ, поэтому коммитится: установщику не нужен ни download,
/// ни SHA — в отличие от GigaAM/Whisper). Модели нет → голосовой режим
/// работает на прежнем детекторе (VAD + STT), а не падает.
/// </summary>
public static class WakeWordFactory
{
    private static readonly Dictionary<char, string> TranslitMap = new()
    {
        ['а'] = "a", ['б'] = "b", ['в'] = "v", ['г'] = "g", ['д'] = "d",
        ['е'] = "e", ['ё'] = "e", ['ж'] = "zh", ['з'] = "z", ['и'] = "i",
        ['й'] = "y", ['к'] = "k", ['л'] = "l", ['м'] = "m", ['н'] = "n",
        ['о'] = "o", ['п'] = "p", ['р'] = "r", ['с'] = "s", ['т'] = "t",
        ['у'] = "u", ['ф'] = "f", ['х'] = "h", ['ц'] = "c", ['ч'] = "ch",
        ['ш'] = "sh", ['щ'] = "sch", ['ъ'] = "", ['ы'] = "y", ['ь'] = "",
        ['э'] = "e", ['ю'] = "yu", ['я'] = "ya"
    };

    /// <summary>Папка с моделями wake word (рядом с моделями STT).</summary>
    public static string ModelDir
    {
        get
        {
            // bin/Debug/net10.0/ → ../../../../ → корень решения, затем
            // ZERE.Voice/WakeWord/models (паритет с WhisperService/GigaAmService).
            var root = Path.GetFullPath(
                Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

            return Path.Combine(root, "ZERE.Voice", "WakeWord", "models");
        }
    }

    /// <summary>«зере» → «zere» (имя файла модели); не-буквы отбрасываются.</summary>
    public static string Transliterate(string word)
    {
        var result = new System.Text.StringBuilder();

        foreach (var raw in (word ?? string.Empty).Trim().ToLowerInvariant())
        {
            if (TranslitMap.TryGetValue(raw, out var mapped))
                result.Append(mapped);
            else if (raw is >= 'a' and <= 'z' or >= '0' and <= '9')
                result.Append(raw);
        }

        var text = result.ToString();

        return string.IsNullOrEmpty(text) ? "wake" : text;
    }

    /// <summary>Путь к модели по слову-триггеру: wake_&lt;транслит&gt;.onnx.</summary>
    public static string ModelPathFor(string word) =>
        Path.Combine(ModelDir, $"wake_{Transliterate(word)}.onnx");

    /// <summary>
    /// Находит модель: явный путь из конфига, иначе папка моделей.
    /// null — файла нет (движок откатится на прежний детектор).
    /// </summary>
    public static string? ResolveModelPath(VoiceConfig config)
    {
        var explicitPath = (config.WakeModelPath ?? string.Empty).Trim();

        if (!string.IsNullOrEmpty(explicitPath))
        {
            var full = Path.IsPathRooted(explicitPath)
                ? explicitPath
                : Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), explicitPath));

            return File.Exists(full) ? full : null;
        }

        var candidate = ModelPathFor(config.WakeWord ?? "зере");

        return File.Exists(candidate) ? candidate : null;
    }

    /// <summary>
    /// Имя движка, который выберет <see cref="Create"/> — без создания
    /// детектора (нужно статусу панели, поле wakeEngine).
    /// </summary>
    public static string DetectEngine(VoiceConfig config)
    {
        var engine = (config.WakeEngine ?? "auto").Trim().ToLowerInvariant();

        if (engine == "whisper")
            return "whisper";

        return ResolveModelPath(config) != null ? KwsWakeWordDetector.EngineName : "whisper";
    }

    /// <summary>
    /// Создаёт детектор по <see cref="VoiceConfig.WakeEngine"/>: KWS-модель,
    /// если она есть и загрузилась; иначе прежний детектор (VAD + STT).
    /// </summary>
    public static IWakeDetector Create(VoiceConfig config, WhisperService whisper)
    {
        var engine = (config.WakeEngine ?? "auto").Trim().ToLowerInvariant();

        if (engine == "whisper")
            return new WakeWordDetector(config, whisper);

        var modelPath = ResolveModelPath(config);

        if (modelPath == null)
        {
            Console.WriteLine(
                $"⚠️ Модель wake word не найдена ({config.WakeWord}) — работаю на прежнем " +
                "детекторе (STT). Обучить модель: python -m tools.wake_word.train");
            return new WakeWordDetector(config, whisper);
        }

        try
        {
            var detector = new KwsWakeWordDetector(config, modelPath);

            // Warmup создаёт ONNX-сессию; битая/несовместимая модель не должна
            // оставить голосовой режим без слова-триггера вообще.
            detector.Warmup();

            if (!detector.IsReady)
            {
                detector.Dispose();
                Console.WriteLine("⚠️ KWS-модель не загрузилась — откат на STT-детектор.");

                return new WakeWordDetector(config, whisper);
            }

            if (engine == "kws")
                Console.WriteLine($"[Voice] Wake word: KWS-модель {Path.GetFileName(modelPath)}");

            return detector;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"⚠️ KWS-детектор не запустился ({ex.Message}) — откат на STT-детектор.");

            return new WakeWordDetector(config, whisper);
        }
    }
}
