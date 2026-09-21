using System.Diagnostics;

namespace JARVIS.Tools.Windows;

public class SafeActionManager
{
    private readonly object _lock = new();
    private PendingAction _pending = PendingAction.None;

    public void Request(PendingAction action)
    {
        lock (_lock)
        {
            _pending = action;
        }
    }

    public bool Confirm()
    {
        lock (_lock)
        {
            switch (_pending)
            {
                case PendingAction.Shutdown:
                    Process.Start(new ProcessStartInfo("shutdown", "/s /t 0")
                    {
                        UseShellExecute = false,
                        CreateNoWindow = true
                    });
                    break;

                case PendingAction.Restart:
                    Process.Start(new ProcessStartInfo("shutdown", "/r /t 0")
                    {
                        UseShellExecute = false,
                        CreateNoWindow = true
                    });
                    break;

                case PendingAction.Sleep:
                    Process.Start(new ProcessStartInfo("rundll32.exe",
                        "powrprof.dll,SetSuspendState 0,1,0")
                    {
                        UseShellExecute = false,
                        CreateNoWindow = true
                    });
                    break;

                default:
                    return false;
            }

            _pending = PendingAction.None;
            return true;
        }
    }

    public void Cancel()
    {
        lock (_lock)
        {
            _pending = PendingAction.None;
        }
    }
}