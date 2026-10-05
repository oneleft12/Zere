namespace ZERE.Tools.Windows.Processes;

public enum ProcessCommandType
{
    None,
    List,
    Search,
    Kill
}

public class ProcessCommandRouter
{
    public (ProcessCommandType Type, string Value) Parse(string message)
    {
        var text = message.Trim().ToLower();

        // === Список процессов ===
        if (text == "процессы" ||
            text == "список процессов" ||
            text == "процессы системы" ||
            text == "что запущено" ||
            text == "задачи" ||
            text == "список задач" ||
            text == "task list" ||
            text == "tasks")
        {
            return (ProcessCommandType.List, "");
        }

        // === Поиск процесса ===
        if (text.StartsWith("найди процесс "))
            return (
                ProcessCommandType.Search,
                message["найди процесс ".Length..].Trim());

        if (text.StartsWith("найти процесс "))
            return (
                ProcessCommandType.Search,
                message["найти процесс ".Length..].Trim());

        if (text.StartsWith("поищи процесс "))
            return (
                ProcessCommandType.Search,
                message["поищи процесс ".Length..].Trim());

        if (text.StartsWith("есть ли процесс "))
            return (
                ProcessCommandType.Search,
                message["есть ли процесс ".Length..].Trim());

        if (text.StartsWith("процесс "))
            return (
                ProcessCommandType.Search,
                message["процесс ".Length..].Trim());

        // === Закрытие процесса ===
        if (text.StartsWith("закрой процесс "))
            return (
                ProcessCommandType.Kill,
                message["закрой процесс ".Length..].Trim());

        if (text.StartsWith("убей процесс "))
            return (
                ProcessCommandType.Kill,
                message["убей процесс ".Length..].Trim());

        if (text.StartsWith("заверши процесс "))
            return (
                ProcessCommandType.Kill,
                message["заверши процесс ".Length..].Trim());

        if (text.StartsWith("останови процесс "))
            return (
                ProcessCommandType.Kill,
                message["останови процесс ".Length..].Trim());

        if (text.StartsWith("kill "))
            return (
                ProcessCommandType.Kill,
                message["kill ".Length..].Trim());

        if (text.StartsWith("закрой "))
            return (
                ProcessCommandType.Kill,
                message["закрой ".Length..].Trim());

        if (text.StartsWith("убей "))
            return (
                ProcessCommandType.Kill,
                message["убей ".Length..].Trim());

        return (ProcessCommandType.None, "");
    }
}
