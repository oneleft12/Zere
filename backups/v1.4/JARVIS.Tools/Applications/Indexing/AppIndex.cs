namespace JARVIS.Tools.Applications.Indexing;

public class AppIndex
{
    public string SchemaVersion { get; set; } = "1.2.1";

    public DateTime CreatedAt { get; set; } = DateTime.Now;

    public List<AppInfo> Applications { get; set; } = new();
}