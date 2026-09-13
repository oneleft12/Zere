using System.Text.RegularExpressions;
using JARVIS.Memory.Database;

namespace JARVIS.Core.Handlers;

public class MemoryExtractor
{
    private readonly MemoryRepository _memory;

    public MemoryExtractor(MemoryRepository memory)
    {
        _memory = memory;
    }

    public bool TryExtract(string message)
    {
        var text = message.Trim();

        var name = Regex.Match(
            text,
            @"меня зовут\s+(.+)$",
            RegexOptions.IgnoreCase);

        if (name.Success)
        {
            _memory.Remember("имя", name.Groups[1].Value.Trim());
            return true;
        }

        var project = Regex.Match(
            text,
            @"мой проект( называется)?\s+(.+)$",
            RegexOptions.IgnoreCase);

        if (project.Success)
        {
            _memory.Remember("проект", project.Groups[2].Value.Trim());
            return true;
        }

        var gpu = Regex.Match(
            text,
            @"(у меня|я использую).*(rtx|gtx|rx)\s*([0-9a-z ]+)",
            RegexOptions.IgnoreCase);

        if (gpu.Success)
        {
            _memory.Remember("видеокарта", gpu.Value.Trim());
            return true;
        }

        var windows = Regex.Match(
            text,
            @"windows\s*(10|11)",
            RegexOptions.IgnoreCase);

        if (windows.Success)
        {
            _memory.Remember("windows", $"Windows {windows.Groups[1].Value}");
            return true;
        }

        return false;
    }
}
