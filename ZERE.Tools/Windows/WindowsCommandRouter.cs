namespace ZERE.Tools.Windows;

public class WindowsCommandRouter
{
    /// <summary>Ключевые слова-стемы команд питания (для поиска отрицания перед ними).</summary>
    private static readonly string[] PowerStems =
    {
        "выключ", "выруб", "перезагруз", "перезапусти", "заверши",
        "заморозь", "уходи спать", "shutdown", "restart", "reboot", "рестарт"
    };

    /// <summary>
    /// Есть ли в сообщении отрицание команды питания: «не выключай компьютер»,
    /// «нет, перезагружай сам», «не надо shutdown». Такие фразы не должны
    /// распознаваться как команды.
    /// </summary>
    public static bool IsNegated(string text)
    {
        var tokens = text.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

        if (tokens.Length == 0)
            return false;

        // Отрицание в начале фразы: «не выключай…», «нет, вырубай сам».
        if (tokens[0] is "не" or "нет")
            return true;

        // Отрицание непосредственно перед ключевым словом:
        // «точно не выключай», «я бы не перезагружал».
        for (var i = 1; i < tokens.Length; i++)
        {
            if (tokens[i - 1] is not ("не" or "нет"))
                continue;

            foreach (var stem in PowerStems)
            {
                if (tokens[i].Contains(stem, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
        }

        return false;
    }

    public WindowsCommandType Parse(string message)
    {
        var text = message.ToLower().Trim();

        // Отрицания — не команды («не выключай компьютер» → None,
        // ответ отдаётся LLM).
        if (IsNegated(text))
            return WindowsCommandType.None;

        // Команды звука не относятся к Windows Power.
        if (text.Contains("звук") || text.Contains("громкость") ||
            text.Contains("громче") || text.Contains("тише") ||
            text.Contains("mute") || text.Contains("unmute"))
            return WindowsCommandType.None;

        // === Выключение ===
        if (text.Contains("выключи компьютер") ||
            text.Contains("выключить компьютер") ||
            text.Contains("выруби компьютер") ||
            text.Contains("выключай компьютер") ||
            text.Contains("выключи комп") ||
            text.Contains("выключить комп") ||
            text.Contains("выруби комп") ||
            text.Contains("выключай комп") ||
            text.Contains("заверши работу") ||
            text.Contains("shutdown") ||
            text.Contains("power off") ||
            text.Contains("выключи пк") ||
            text.Contains("выключить пк") ||
            text.Contains("выруби пк"))
        {
            return WindowsCommandType.Shutdown;
        }

        // === Перезагрузка ===
        if (text.Contains("перезагрузи компьютер") ||
            text.Contains("перезагрузить компьютер") ||
            text.Contains("перезагрузи комп") ||
            text.Contains("перезагрузить комп") ||
            // Существительное — только как самостоятельная команда,
            // иначе «после перезагрузки файлы сохранятся?» запрашивало рестарт.
            text == "перезагрузка" ||
            text.StartsWith("перезагрузка ") ||
            text.Contains("reboot") ||
            text.Contains("restart") ||
            text.Contains("рестарт") ||
            text.Contains("перезагрузи пк") ||
            text.Contains("перезагрузить пк") ||
            text.Contains("перезапусти компьютер") ||
            text.Contains("перезапусти комп"))
        {
            return WindowsCommandType.Restart;
        }

        // === Сон ===
        if (text == "сон" ||
            text.Contains("режим сна") ||
            text.Contains("спящий режим") ||
            text.Contains("компьютер в сон") ||
            text.Contains("комп в сон") ||
            text.Contains("заморозь") ||
            text.Contains("hibernate") ||
            text.Contains("hybernate") ||
            text.Contains("уходи спать"))
        {
            return WindowsCommandType.Sleep;
        }

        return WindowsCommandType.None;
    }
}
