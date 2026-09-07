namespace JARVIS.Tools.Windows.Processes;

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

        if (text == "процессы")
            return (ProcessCommandType.List, "");

        if (text.StartsWith("найди процесс "))
            return (
                ProcessCommandType.Search,
                message["найди процесс ".Length..].Trim());

        if (text.StartsWith("закрой процесс "))
            return (
                ProcessCommandType.Kill,
                message["закрой процесс ".Length..].Trim());

        return (ProcessCommandType.None, "");
    }
}