namespace JARVIS.Tools.Windows;

public class WindowsCommandRouter
{
    public WindowsCommandType Parse(string message)
    {
        var text = message.ToLower().Trim();

        // Команды звука не относятся к Windows Power.
if (text.Contains("звук") || text.Contains("громкость"))
    return WindowsCommandType.None;

        if (text.Contains("выключи компьютер") ||
            text.Contains("выключить компьютер"))
            return WindowsCommandType.Shutdown;

        if (text.Contains("перезагрузи компьютер") ||
            text.Contains("перезагрузить компьютер"))
            return WindowsCommandType.Restart;

        if (text == "сон" ||
            text.Contains("режим сна"))
            return WindowsCommandType.Sleep;

        return WindowsCommandType.None;
    }
}