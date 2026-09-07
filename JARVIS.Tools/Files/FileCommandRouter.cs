namespace JARVIS.Tools.Files;

public class FileCommandRouter
{
    public (FileCommandType Type, string Value) Parse(string message)
    {
        var text = message.Trim();

        if (text.Equals("удали его", StringComparison.OrdinalIgnoreCase) ||
        text.Equals("удалить его", StringComparison.OrdinalIgnoreCase))
{
    return (FileCommandType.DeleteLastFile, "");
}

        if (text.StartsWith("создай папку ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFolder,
                text["создай папку ".Length..].Trim());

        if (text.StartsWith("создай файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFile,
                text["создай файл ".Length..].Trim());

        if (text.StartsWith("найди файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.FindFile,
                text["найди файл ".Length..].Trim());

        if (text.StartsWith("удали файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.DeleteFile,
                text["удали файл ".Length..].Trim());

        return (FileCommandType.None, "");
    }
}