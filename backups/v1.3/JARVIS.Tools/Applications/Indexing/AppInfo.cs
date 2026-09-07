namespace JARVIS.Tools.Applications.Indexing;

public class AppInfo
{
    public string Name { get; set; } = "";

    public string ExecutablePath { get; set; } = "";

    public string Source { get; set; } = "";

    public string Category { get; set; } = "Application";

    public int Priority { get; set; } = 50;

    public List<string> Aliases { get; set; } = new();

    public DateTime LastSeen { get; set; } = DateTime.Now;
}