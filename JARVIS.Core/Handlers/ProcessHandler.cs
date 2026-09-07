using JARVIS.Tools.Windows.Processes;

namespace JARVIS.Core.Handlers;

public class ProcessHandler : IJarvisHandler
{
    private readonly ProcessService _service = new();
    private readonly ProcessCommandRouter _router = new();

    public bool CanHandle(string message)
    {
        var lower = message.ToLower();

        return lower == "процессы" ||
               lower.StartsWith("найди процесс") ||
               lower.StartsWith("закрой процесс");
    }

    public Task<string> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var command = _router.Parse(message);

        switch (command.Type)
        {
            case ProcessCommandType.List:

                var processes = _service.GetProcesses().Take(15);

                return "Самые тяжёлые процессы:\n\n" +
                       string.Join(
                           "\n",
                           processes.Select(p =>
                               $"• {p.Name} — {p.MemoryMb} MB"));

            case ProcessCommandType.Search:

                var found = _service.Search(command.Value);

                if (found.Count == 0)
                    return "Процесс не найден.";

                return string.Join(
                    "\n",
                    found.Select(p =>
                        $"• {p.Name} (PID {p.Id}) — {p.MemoryMb} MB"));

            case ProcessCommandType.Kill:

                return _service.Kill(command.Value)
                    ? $"Процесс {command.Value} закрыт."
                    : "Процесс не найден.";
        }

        return "Команда процессов не распознана.";
    }
}