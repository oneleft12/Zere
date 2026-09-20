using System.Diagnostics;

namespace JARVIS.Tools.Windows;

public class SafeActionManager
{
    private PendingAction _pending = PendingAction.None;

    public void Request(PendingAction action)
    {
        _pending = action;
    }

    public bool Confirm()
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

    public void Cancel()
    {
        _pending = PendingAction.None;
    }
}