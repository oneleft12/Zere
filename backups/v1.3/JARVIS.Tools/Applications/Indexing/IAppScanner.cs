namespace JARVIS.Tools.Applications.Indexing;

public interface IAppScanner
{
    IEnumerable<AppInfo> Scan();
}