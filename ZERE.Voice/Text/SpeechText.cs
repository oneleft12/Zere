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
    /// Переводы строк заменяются пробелами: в stdin piper каждая строка — отдельное предложение.
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
    /// </summary>
    public static List<string> SplitSentences(string text)
    {
        var parts = Regex.Matches(text, @"[^.!?…]+[.!?…]+[»""']*\s*|[^.!?…]+$")
            .Select(m => m.Value.Trim())
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .ToList();

        return parts.Count > 0 ? parts : new List<string> { text.Trim() };
    }
}
