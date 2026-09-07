using JARVIS.Tools.Applications.Indexing;

namespace JARVIS.Tools.Applications;

public class StartMenuScanner : IAppScanner
{
    public IEnumerable<AppInfo> Scan()
    {
        var apps = new List<AppInfo>();

        var folders = new[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.CommonStartMenu),
            Environment.GetFolderPath(Environment.SpecialFolder.StartMenu)
        };

        foreach (var folder in folders)
        {
            ScanFolder(folder, apps);
        }

        return apps;
    }

    private void ScanFolder(string folder, List<AppInfo> apps)
    {
        if (!Directory.Exists(folder))
            return;

        try
        {
            foreach (var shortcut in Directory.EnumerateFiles(folder, "*.lnk"))
            {
                var name = Path.GetFileNameWithoutExtension(shortcut);

                apps.Add(new AppInfo
                {
                    Name = name,
                    ExecutablePath = shortcut,
                    Source = "Start Menu",
                    Priority = 80,
                    Category = "Application",
                    Aliases = AppAliasProvider.GetAliases(name)
                });
            }

            foreach (var subFolder in Directory.EnumerateDirectories(folder))
            {
                ScanFolder(subFolder, apps);
            }
        }
        catch
        {
        }
    }
}