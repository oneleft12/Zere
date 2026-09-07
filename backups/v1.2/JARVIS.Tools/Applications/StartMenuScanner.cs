using JARVIS.Tools.Applications.Indexing;

namespace JARVIS.Tools.Applications;

public class StartMenuScanner : IAppScanner
{
    public IEnumerable<AppInfo> Scan()
    {
        var result = new List<AppInfo>();

        var folders = new[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.CommonStartMenu),
            Environment.GetFolderPath(Environment.SpecialFolder.StartMenu)
        };

        foreach (var folder in folders)
        {
            ScanFolder(folder, result);
        }

        return result;
    }

    private void ScanFolder(string folder, List<AppInfo> apps)
    {
        if (!Directory.Exists(folder))
            return;

        try
        {
            foreach (var shortcut in Directory.EnumerateFiles(folder, "*.lnk"))
            {
                apps.Add(new AppInfo
                {
                    Name = Path.GetFileNameWithoutExtension(shortcut),
                    ExecutablePath = shortcut,
                    Source = "Start Menu",
                    Priority = 80
                });
            }

            foreach (var subFolder in Directory.EnumerateDirectories(folder))
            {
                ScanFolder(subFolder, apps);
            }
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}