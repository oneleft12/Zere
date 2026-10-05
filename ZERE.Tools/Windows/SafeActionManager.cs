using System.Diagnostics;
using ZERE.Tools.Files;
using ZERE.Tools.Windows.Processes;

namespace ZERE.Tools.Windows;

/// <summary>Результат подтверждения ожидающего действия.</summary>
public enum ConfirmOutcome
{
    /// <summary>Действие выполнено.</summary>
    Executed,
    /// <summary>Нет ожидающего действия.</summary>
    NoPending,
    /// <summary>Срок подтверждения истёк — действие сброшено.</summary>
    Expired,
    /// <summary>Действие не удалось выполнить.</summary>
    Failed
}

/// <summary>
/// Подтверждение опасных действий. Ожидающее действие живёт ограниченное время
/// (TTL) — «да», сказанное спустя долгое время, ничего не выполнит.
/// </summary>
public class SafeActionManager
{
    /// <summary>Срок жизни подтверждения, секунд.</summary>
    public const int ConfirmTtlSeconds = 60;

    private readonly object _lock = new();
    private readonly ProcessService _processService;
    private readonly FileManager _files;

    private PendingAction _pending = PendingAction.None;
    private string _target = "";
    private DateTimeOffset _requestedAt;

    public SafeActionManager(ProcessService processService, FileManager files)
    {
        _processService = processService;
        _files = files;
    }

    public void Request(PendingAction action, string target = "")
    {
        lock (_lock)
        {
            _pending = action;
            _target = target;
            _requestedAt = DateTimeOffset.UtcNow;
        }
    }

    public void Cancel()
    {
        lock (_lock)
        {
            _pending = PendingAction.None;
            _target = "";
        }
    }

    public ConfirmOutcome Confirm()
    {
        lock (_lock)
        {
            if (_pending == PendingAction.None)
                return ConfirmOutcome.NoPending;

            // Подтверждение имеет срок действия: «да», сказанное позже,
            // не выполняет опасную команду.
            if ((DateTimeOffset.UtcNow - _requestedAt).TotalSeconds > ConfirmTtlSeconds)
            {
                _pending = PendingAction.None;
                _target = "";
                return ConfirmOutcome.Expired;
            }

            var action = _pending;
            var target = _target;
            _pending = PendingAction.None;
            _target = "";

            try
            {
                return Execute(action, target)
                    ? ConfirmOutcome.Executed
                    : ConfirmOutcome.Failed;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[SafeActionManager] Ошибка выполнения: {ex.Message}");
                return ConfirmOutcome.Failed;
            }
        }
    }

    private bool Execute(PendingAction action, string target)
    {
        switch (action)
        {
            case PendingAction.Shutdown:
                return Start("shutdown", "/s /t 0");

            case PendingAction.Restart:
                return Start("shutdown", "/r /t 0");

            case PendingAction.Sleep:
                return Start("rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0");

            case PendingAction.KillProcess:
                return _processService.Kill(target);

            case PendingAction.DeleteFile:
                return _files.DeleteFile(target);

            default:
                return false;
        }
    }

    private static bool Start(string fileName, string arguments)
    {
        using var process = Process.Start(new ProcessStartInfo(fileName, arguments)
        {
            UseShellExecute = false,
            CreateNoWindow = true
        });

        return process != null;
    }
}
