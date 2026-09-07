namespace JARVIS.Tools.FileManager;

public class FileCommandRouter
{
    public (FileCommandType Type, string Value) Parse(string message)
    {
        var text = message.Trim();

        if (text.StartsWith("создай папку ", StringComparison.OrdinalIgnoreCase))
            return (FileCommandType.CreateFolder,
                text.Substring("создай папку ".Length));

        if (text.StartsWith("создай файл ", StringComparison.OrdinalIgnoreCase))
            return (FileCommandType.CreateFile,
                text.Substring("создай файл ".Length));

        if (text.StartsWith("прочитай файл ", StringComparison.OrdinalIgnoreCase))
            return (FileCommandType.ReadFile,
                text.Substring("прочитай файл ".Length));

        if (text.StartsWith("найди файл ", StringComparison.OrdinalIgnoreCase))
            return (FileCommandType.SearchFile,
                text.Substring("найди файл ".Length));

        if (text.StartsWith("найди папку ", StringComparison.OrdinalIgnoreCase))
            return (FileCommandType.SearchFolder,
                text.Substring("найди папку ".Length));

        if (text.StartsWith("удали файл ", StringComparison.OrdinalIgnoreCase))
            return (FileCommandType.DeleteFile,
                text.Substring("удали файл ".Length));

        if (text.StartsWith("запиши в файл ", StringComparison.OrdinalIgnoreCase))
            return (FileCommandType.WriteFile,
                text.Substring("запиши в файл ".Length));

        return (FileCommandType.None, "");
    }
}