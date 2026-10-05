namespace ZERE.Tools.Gaming.Models;

public class GameStat
{
    public string GameName { get; set; } = "";
    public TimeSpan TodayTime { get; set; }
    public DateTime LastPlayed { get; set; }
    public bool IsRunning { get; set; }
}
