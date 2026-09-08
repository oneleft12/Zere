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
                Process.Start("shutdown", "/s /t 0");
                break;

            case PendingAction.Restart:
                Process.Start("shutdown", "/r /t 0");
                break;

            case PendingAction.Sleep:
                Process.Start("rundll32.exe",
                    "powrprof.dll,SetSuspendState 0,1,0");
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