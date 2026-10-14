using System.Text.RegularExpressions;

namespace ZERE.Voice.Text;

/// <summary>
/// Подготовка текста для озвучки: чистка от «нечитаемого» TTS-мусора
/// и разбивка на предложения (для попредначенного синтеза/воспроизведения).
/// </summary>
public static class SpeechText
{
    /// <summary>
    /// Убирает из текста всё, что TTS не должен произносить:
    /// эмодзи, текстовые смайлики, «ролевые» пометки (*улыбается*, (томно)),
    /// markdown-символы и Markdown-эмодзи вроде :smile:.
    /// Переводы строк заменяются пробелами: TTS не должен произносить их как паузы.
    /// </summary>
    public static string Clean(string text)
    {
        if (string.IsNullOrEmpty(text))
            return text;

        text = text.Replace('\r', ' ').Replace('\n', ' ');

        // Ролевые пометки в скобках: (улыбается), (смеётся), (задумчиво)
        text = Regex.Replace(text, @"\([^)]*[а-яёА-ЯЁ]{3,}[^)]*\)", " ");

        // Ролевые пометки в *звёздочках*: *улыбается*, *качает головой*
        text = Regex.Replace(text, @"\*[^*]*[а-яёА-ЯЁ]{3,}[^*]*\*", " ");

        // Markdown-эмодзи :smile:, :heart:
        text = Regex.Replace(text, @":[a-z_0-9]+:", " ");

        // Текстовые смайлики: :) ;) :D :( :P <3 =) и т.п.
        text = Regex.Replace(text, @"[:;=8][\-^']?[)(DPp/\\|]", " ");
        text = Regex.Replace(text, @"[)(DPp/\\|][\-^']?[:;=8]", " ");
        text = Regex.Replace(text, @"<3", " ");

        // Юникод-эмодзи и символы (суррогатные пары, Variation Selector, ZWJ)
        text = Regex.Replace(text,
            @"[\uD800-\uDBFF][\uDC00-\uDFFF]|\uFE0F|\u200D|[\u2600-\u27BF]|\u2190-\u21FF|\u2B00-\u2BFF|\u2700-\u27BF]",
            "");

        // Убираем markdown-разметку: **bold**, *italic*, `code`, ## заголовки
        text = Regex.Replace(text, @"[*_`#]{1,3}([^*_`#]+)[*_`#]{1,3}", "$1");
        text = Regex.Replace(text, @"[*_`#~>|-]{2,}", " ");

        // Схлопываем пробелы
        text = Regex.Replace(text, @"\s{2,}", " ").Trim();

        return text;
    }

    /// <summary>
    /// Разбивает текст на предложения — каждое уходит в синтез отдельной порцией
    /// и воспроизводится, пока следующее ещё готовится.
    /// Точка между цифрами предложением не считается: «3.5», «12.05.2026» и
    /// «1.2.3» остаются целыми — иначе число рвётся на две реплики и звучит
    /// как «три» + «пять» (паритет с Python-редакцией, speech_text.py).
    /// </summary>
    public static List<string> SplitSentences(string text)
    {
        var source = (text ?? string.Empty).Trim();

        if (source.Length == 0)
            return new List<string>();

        var parts = new List<string>();
        var start = 0;

        foreach (Match match in Regex.Matches(source, @"[.!?…]+(?!\d)"))
        {
            var end = match.Index + match.Length;

            // Закрывающие кавычки/скобки сразу после знака — часть предложения.
            while (end < source.Length && "»”\"')]".IndexOf(source[end]) >= 0)
                end++;

            var chunk = source.Substring(start, end - start).Trim();

            if (chunk.Length > 0)
                parts.Add(chunk);

            start = end;
        }

        var tail = source.Substring(start).Trim();

        if (tail.Length > 0)
            parts.Add(tail);

        return parts;
    }
}
