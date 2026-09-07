namespace JARVIS.Tools.System;

public class ProcessCommandRouter
{
    public (ProcessCommandType Type, string Value) Parse(string message)
    {
        var text = message.Trim();

        if (text.Equals("что сейчас запущено", StringComparison.OrdinalIgnoreCase))
            return (ProcessCommandType.ListProcesses, "");

        if (text.StartsWith("найди процесс ", StringComparison.OrdinalIgnoreCase))
            return (
                ProcessCommandType.FindProcess,
                text["найди процесс ".Length..].Trim());

        if (text.StartsWith("закрой ", StringComparison.OrdinalIgnoreCase))
        {
            var value = text["закрой ".Length..].Trim();

            if (value.Equals("его", StringComparison.OrdinalIgnoreCase))
                return (ProcessCommandType.KillLastProcess, "");

            return (ProcessCommandType.KillProcess, value);
        }

        return (ProcessCommandType.None, "");
    }
}