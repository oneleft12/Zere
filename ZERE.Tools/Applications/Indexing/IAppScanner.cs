namespace ZERE.Tools.Applications.Indexing;

public interface IAppScanner
{
    IEnumerable<AppInfo> Scan();
}