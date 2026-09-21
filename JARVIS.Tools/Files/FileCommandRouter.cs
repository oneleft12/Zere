namespace JARVIS.Tools.Files;

public class FileCommandRouter
{
    public (FileCommandType Type, string Value) Parse(string message)
    {
        var text = message.Trim();

        // === Удаление последнего файла ===
        if (text.Equals("удали его", StringComparison.OrdinalIgnoreCase) ||
            text.Equals("удалить его", StringComparison.OrdinalIgnoreCase))
        {
            return (FileCommandType.DeleteLastFile, "");
        }

        // === Создание папки ===
        if (text.StartsWith("создай папку ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFolder,
                text["создай папку ".Length..].Trim());

        if (text.StartsWith("создай директорию ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFolder,
                text["создай директорию ".Length..].Trim());

        if (text.StartsWith("новая папка ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFolder,
                text["новая папка ".Length..].Trim());

        if (text.StartsWith("замокай папку ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFolder,
                text["замокай папку ".Length..].Trim());

        if (text.StartsWith("папка ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFolder,
                text["папка ".Length..].Trim());

        // === Создание файла ===
        if (text.StartsWith("создай файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFile,
                text["создай файл ".Length..].Trim());

        if (text.StartsWith("новый файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFile,
                text["новый файл ".Length..].Trim());

        if (text.StartsWith("создай документ ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFile,
                text["создай документ ".Length..].Trim());

        if (text.StartsWith("замокай файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFile,
                text["замокай файл ".Length..].Trim());

        if (text.StartsWith("документ ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.CreateFile,
                text["документ ".Length..].Trim());

        // === Поиск файла ===
        if (text.StartsWith("найди файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.FindFile,
                text["найди файл ".Length..].Trim());

        if (text.StartsWith("найти файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.FindFile,
                text["найти файл ".Length..].Trim());

        if (text.StartsWith("поищи файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.FindFile,
                text["поищи файл ".Length..].Trim());

        if (text.StartsWith("где файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.FindFile,
                text["где файл ".Length..].Trim());

        if (text.StartsWith("розыск файла ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.FindFile,
                text["розыск файла ".Length..].Trim());

        // === Удаление файла ===
        if (text.StartsWith("удали файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.DeleteFile,
                text["удали файл ".Length..].Trim());

        if (text.StartsWith("удали ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.DeleteFile,
                text["удали ".Length..].Trim());

        if (text.StartsWith("убери файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.DeleteFile,
                text["убери файл ".Length..].Trim());

        if (text.StartsWith("удалить файл ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.DeleteFile,
                text["удалить файл ".Length..].Trim());

        if (text.StartsWith("стереть ", StringComparison.OrdinalIgnoreCase))
            return (
                FileCommandType.DeleteFile,
                text["стереть ".Length..].Trim());

        return (FileCommandType.None, "");
    }
}
