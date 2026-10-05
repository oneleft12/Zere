using ZERE.Tools.Applications;
using ZERE.Tools.Windows;

namespace ZERE.Core.Handlers;

public class WindowsHandler : IZereHandler
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

        // Отмена ожидающего действия — всегда наша команда.
        if (lower == "нет")
            return true;

        // Отрицания («не выключай компьютер») не считаем командами
        // питания — ответ отдаёт LLM.
        var power = !WindowsCommandRouter.IsNegated(lower) && (
               lower.Contains("выключи компьютер") ||
               lower.Contains("выключить компьютер") ||
               lower.Contains("выруби компьютер") ||
               lower.Contains("выключай компьютер") ||
               lower.Contains("выключи комп") ||
               lower.Contains("выключить комп") ||
               lower.Contains("выруби комп") ||
               lower.Contains("выключай комп") ||
               lower.Contains("заверши работу") ||
               lower.Contains("shutdown") ||
               lower.Contains("power off") ||
               lower.Contains("выключи пк") ||
               lower.Contains("выключить пк") ||
               lower.Contains("выруби пк") ||
               // Restart
               lower.Contains("перезагрузи компьютер") ||
               lower.Contains("перезагрузить компьютер") ||
               lower.Contains("перезагрузи комп") ||
               lower.Contains("перезагрузить комп") ||
               lower == "перезагрузка" ||
               lower.StartsWith("перезагрузка ") ||
               lower.Contains("reboot") ||
               lower.Contains("restart") ||
               lower.Contains("рестарт") ||
               lower.Contains("перезагрузи пк") ||
               lower.Contains("перезагрузить пк") ||
               lower.Contains("перезапусти компьютер") ||
               lower.Contains("перезапусти комп") ||
               // Sleep
               lower == "сон" ||
               lower.Contains("режим сна") ||
               lower.Contains("спящий режим") ||
               lower.Contains("компьютер в сон") ||
               lower.Contains("комп в сон") ||
               lower.Contains("заморозь") ||
               lower.Contains("hibernate") ||
               lower.Contains("уходи спать"));

        return lower.StartsWith("открой ") ||
               lower == "обнови индекс" ||
               lower == "сколько приложений" ||
               // «найди файл …» — зона FileHandler (он идёт после нас):
               // без этого исключения файловый поиск был бы недостижим.
               (lower.StartsWith("найди ") && !lower.StartsWith("найди файл")) ||
               power ||
               // Confirmations
               lower == "да" ||
               lower == "подтверди" ||
               lower == "выполни" ||
               lower == "сделай" ||
               lower == "выполняй";
    }

    public Task<string?> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var lower = message.ToLower().Trim();

        if (lower == "да" || lower == "подтверди" || lower == "выполни" || lower == "сделай" || lower == "выполняй")
        {
            return _safeActions.Confirm() switch
            {
                ConfirmOutcome.Executed => "Выполняю команду.",
                ConfirmOutcome.Expired =>
                    $"Время подтверждения истекло ({SafeActionManager.ConfirmTtlSeconds} секунд) — команда сброшена. Повторите команду.",
                ConfirmOutcome.Failed => "Не удалось выполнить команду.",
                _ => "Нет команды для подтверждения."
            };
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

        if (lower.StartsWith("найди ") && !lower.StartsWith("найди файл"))
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
                return $"Вы уверены, что хотите выключить компьютер? Напишите «да» или «нет» (подтверждение действует {SafeActionManager.ConfirmTtlSeconds} секунд).";

            case WindowsCommandType.Restart:
                _safeActions.Request(PendingAction.Restart);
                return $"Вы уверены, что хотите перезагрузить компьютер? Напишите «да» или «нет» (подтверждение действует {SafeActionManager.ConfirmTtlSeconds} секунд).";

            case WindowsCommandType.Sleep:
                _safeActions.Request(PendingAction.Sleep);
                return $"Перевести компьютер в сон? Напишите «да» или «нет» (подтверждение действует {SafeActionManager.ConfirmTtlSeconds} секунд).";
        }

        return "Команда Windows не распознана.";
    }
}
