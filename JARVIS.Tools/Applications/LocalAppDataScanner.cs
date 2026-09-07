using JARVIS.Tools.Applications.Indexing;

namespace JARVIS.Tools.Applications;

public class LocalAppDataScanner : IAppScanner
{
    private readonly string[] _roots =
    {
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
    };

    private readonly string[] _targets =
    {
        "Discord",
        "Telegram Desktop",
        "Spotify",
        "Cursor",
        "Code",
        "Riot Client"
    };

    public IEnumerable<AppInfo> Scan()
    {
        var apps = new List<AppInfo>();

        foreach (var root in _roots)
        {
            foreach (var folder in _targets)
            {
                var path = Path.Combine(root, folder);

                if (!Directory.Exists(path))
                    continue;

                try
                {
                    var exe = Directory.GetFiles(
                        path,
                        "*.exe",
                        SearchOption.AllDirectories)
                        .OrderBy(f => f.Length)
                        .FirstOrDefault();

                    if (exe == null)
                        continue;

                    apps.Add(new AppInfo
                    {
                        Name = folder,
                        ExecutablePath = exe,
                        Source = "LocalAppData",
                        Priority = 100,
                        Category = GuessCategory(folder),
                        Aliases = AppAliasProvider.GetAliases(folder)
                    });
                }
                catch
                {
                }
            }
        }

        return apps;
    }

    private string GuessCategory(string name)
    {
        return name switch
        {
            "Discord" => "Messenger",
            "Telegram Desktop" => "Messenger",
            "Spotify" => "Media",
            "Cursor" => "IDE",
            "Code" => "IDE",
            "Riot Client" => "Game Launcher",
            _ => "Application"
        };
    }
}