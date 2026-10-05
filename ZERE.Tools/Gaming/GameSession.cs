namespace ZERE.Tools.Gaming;

public class GameSession
{
    public string GameName { get; set; } = "";

    public DateTime StartTime { get; set; }

    public bool IsActive { get; set; }

    public TimeSpan Duration =>
        IsActive ? DateTime.Now - StartTime : TimeSpan.Zero;
}