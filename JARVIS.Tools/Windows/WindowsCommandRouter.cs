namespace JARVIS.Tools.Windows;

public class WindowsCommandRouter
{
    public WindowsCommandType Parse(string message)
    {
        var text = message.ToLower().Trim();

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
            text.Contains("перезагрузка") ||
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
