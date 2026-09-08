using JARVIS.Tools.Applications.Indexing;

namespace JARVIS.Tools.Applications.Indexing;

public interface IAppScanner
{
    IEnumerable<AppInfo> Scan();
}