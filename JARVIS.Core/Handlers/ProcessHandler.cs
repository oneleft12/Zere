using JARVIS.Tools.Windows;
using JARVIS.Tools.Windows.Processes;

namespace JARVIS.Core.Handlers;

public class ProcessHandler : IJarvisHandler
{
    private readonly ProcessService _service;
    private readonly SafeActionManager _safeActions;
    private readonly ProcessCommandRouter _router = new();

    public ProcessHandler(ProcessService service, SafeActionManager safeActions)
    {
        _service = service;
        _safeActions = safeActions;
    }

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower == "процессы" ||
               lower == "список процессов" ||
               lower == "процессы системы" ||
               lower == "что запущено" ||
               lower == "задачи" ||
               lower == "список задач" ||
               lower == "task list" ||
               lower == "tasks" ||
               lower.StartsWith("найди процесс") ||
               lower.StartsWith("найти процесс") ||
               lower.StartsWith("поищи процесс") ||
               lower.StartsWith("есть ли процесс") ||
               lower.StartsWith("процесс ") ||
               lower.StartsWith("закрой процесс") ||
               lower.StartsWith("убей процесс") ||
               lower.StartsWith("заверши процесс") ||
               lower.StartsWith("останови процесс") ||
               lower.StartsWith("kill ") ||
               lower.StartsWith("закрой ") ||
               lower.StartsWith("убей ");
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

                // Завершение процессов — необратимое действие: сначала
                // защита системных процессов, затем явное подтверждение.
                if (ProcessService.IsProtected(command.Value))
                    return $"Процесс «{command.Value}» системный — его завершение запрещено.";

                var matches = _service.SearchExact(command.Value);

                if (matches.Count == 0)
                    return "Процесс не найден.";

                _safeActions.Request(PendingAction.KillProcess, command.Value);

                var pids = string.Join(", ", matches.Select(p => p.Id));

                return $"Найдено процесс(ов) «{command.Value}»: {matches.Count} (PID {pids}). " +
                       $"Завершить? Напишите «да» или «нет» (подтверждение действует " +
                       $"{SafeActionManager.ConfirmTtlSeconds} секунд).";
        }

        return "Команда процессов не распознана.";
    }
}
