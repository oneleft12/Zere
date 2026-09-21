using JARVIS.Tools.Applications;
using JARVIS.Tools.Windows;

namespace JARVIS.Core.Handlers;

public class WindowsHandler : IJarvisHandler
{
    private readonly ApplicationLauncher _launcher;
    private readonly WindowsCommandRouter _router = new();
    private readonly SafeActionManager _safeActions;

    public WindowsHandler(ApplicationLauncher launcher, SafeActionManager safeActions)
    {
        _launcher = launcher;
        _safeActions = safeActions;
    }

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower.StartsWith("открой ") ||
               lower == "обнови индекс" ||
               lower == "сколько приложений" ||
               lower.StartsWith("найди ") ||
               lower == "выключи компьютер" ||
               lower == "перезагрузи компьютер" ||
               lower == "сон" ||
               lower == "да" ||
               lower == "нет" ||
               lower == "подтверди" ||
               lower == "выполни" ||
               lower == "сделай" ||
               lower == "выполняй";
    }

    public Task<string> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var lower = message.ToLower().Trim();

        if (lower == "да" || lower == "подтверди" || lower == "выполни" || lower == "сделай" || lower == "выполняй")
        {
            return _safeActions.Confirm()
                ? "Выполняю команду."
                : "Нет команды для подтверждения.";
        }

        if (lower == "нет")
        {
            _safeActions.Cancel();
            return "Команда отменена.";
        }

        if (lower == "обнови индекс")
        {
            _launcher.RebuildIndex();
            return "Индекс приложений успешно обновлён.";
        }

        if (lower == "сколько приложений")
        {
            return $"В индексе {_launcher.GetInstalledApplications().Count} приложений.";
        }

        if (lower.StartsWith("найди "))
        {
            var query = lower.Replace("найди ", "");

            var apps = _launcher.GetInstalledApplications()
                .Values
                .Where(a => a.Name.Contains(query, StringComparison.OrdinalIgnoreCase))
                .Take(10)
                .Select(a => $"• {a.Name}");

            var result = string.Join("\n", apps);

            return string.IsNullOrWhiteSpace(result)
                ? "Ничего не найдено."
                : result;
        }

        if (lower.StartsWith("открой "))
        {
            var app = message["открой".Length..].Trim();

            return _launcher.Launch(app)
                ? $"Открываю {app}."
                : $"Не удалось найти приложение «{app}».";
        }

        var command = _router.Parse(message);

        switch (command)
        {
            case WindowsCommandType.Shutdown:
                _safeActions.Request(PendingAction.Shutdown);
                return "Вы уверены, что хотите выключить компьютер? Напишите «да», «подтверди», «выполни» или «нет».";

            case WindowsCommandType.Restart:
                _safeActions.Request(PendingAction.Restart);
                return "Вы уверены, что хотите перезагрузить компьютер? Напишите «да», «подтверди», «выполни» или «нет».";

            case WindowsCommandType.Sleep:
                _safeActions.Request(PendingAction.Sleep);
                return "Перевести компьютер в сон? Напишите «да», «подтверди», «выполни» или «нет».";
        }

        return "Команда Windows не распознана.";
    }
}
