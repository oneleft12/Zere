namespace JARVIS.Tools.Windows;

public class SafeActionManager
{
    public PendingAction Pending { get; private set; } = PendingAction.None;

    public void Request(PendingAction action)
    {
        Pending = action;
    }

    public void Clear()
    {
        Pending = PendingAction.None;
    }

    public bool HasPending()
    {
        return Pending != PendingAction.None;
    }
}