using Microsoft.Win32;
using ZERE.Tools.Applications.Indexing;

namespace ZERE.Tools.Applications;

public class RegistryScanner : IAppScanner
{
    public IEnumerable<AppInfo> Scan()
    {
        var apps = new Dictionary<string, AppInfo>();

        ScanHive(
            Registry.LocalMachine,
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            apps);

        ScanHive(
            Registry.LocalMachine,
            @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            apps);

        ScanHive(
            Registry.CurrentUser,
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            apps);

        return apps.Values;
    }

    private void ScanHive(
        RegistryKey hive,
        string path,
        Dictionary<string, AppInfo> apps)
    {
        using RegistryKey? key = hive.OpenSubKey(path);

        if (key is null)
            return;

        foreach (string subKeyName in key.GetSubKeyNames())
        {
            try
            {
                using RegistryKey? subKey = key.OpenSubKey(subKeyName);

                if (subKey is null)
                    continue;

                string? name = subKey.GetValue("DisplayName") as string;
                string? icon = subKey.GetValue("DisplayIcon") as string;
                string? installLocation = subKey.GetValue("InstallLocation") as string;

                if (string.IsNullOrWhiteSpace(name))
                    continue;

                string? exe = ResolveExecutable(icon, installLocation);

                if (string.IsNullOrWhiteSpace(exe))
                    continue;

                apps[name.ToLowerInvariant()] = new AppInfo
                {
                    Name = name,
                    ExecutablePath = exe,
                    Source = "Registry",
                    Priority = 90,
                    Category = GuessCategory(name),
                    Aliases = AppAliasProvider.GetAliases(name)
                };
            }
            catch
            {
                // Пропускаем повреждённые записи реестра.
            }
        }
    }

    // ----------------------------
    // Умный поиск главного EXE
    // ----------------------------
    private string? ResolveExecutable(string? displayIcon, string? installLocation)
    {
        string? exe = null;

        // 1. Берём DisplayIcon
        if (!string.IsNullOrWhiteSpace(displayIcon))
        {
            exe = displayIcon.Split(',')[0].Trim('"');
        }

        // 2. Если путь существует и это НЕ служебный exe — используем сразу
        if (!string.IsNullOrWhiteSpace(exe) && File.Exists(exe))
        {
            string fileName = Path.GetFileName(exe).ToLowerInvariant();

            string[] badExecutables =
            {
                "uninstall.exe",
                "unins000.exe",
                "gameoverlayui.exe",
                "gameoverlayui64.exe",
                "crashhandler.exe",
                "updater.exe",
                "helper.exe"
            };

            if (!badExecutables.Contains(fileName))
                return exe;

            installLocation ??= Path.GetDirectoryName(exe);
        }

        // 3. Если есть папка установки — выбираем лучший exe
        if (!string.IsNullOrWhiteSpace(installLocation) &&
            Directory.Exists(installLocation))
        {
            var executables = Directory.GetFiles(
                installLocation,
                "*.exe",
                SearchOption.TopDirectoryOnly);

            if (executables.Length > 0)
            {
                return executables
                    .OrderByDescending(GetExecutableScore)
                    .First();
            }
        }

        return exe;
    }

    // ----------------------------
    // Рейтинг EXE файлов
    // ----------------------------
    private int GetExecutableScore(string exePath)
    {
        string name = Path.GetFileName(exePath).ToLowerInvariant();

        // Никогда не выбираем служебные процессы
        if (name.StartsWith("uninstall") ||
            name.StartsWith("unins") ||
            name.Contains("overlay") ||
            name.Contains("crash") ||
            name.Contains("helper") ||
            name.Contains("updater"))
        {
            return 0;
        }

        return name switch
        {
            "steam.exe" => 100,
            "discord.exe" => 100,
            "telegram.exe" => 100,
            "code.exe" => 100,
            "cursor.exe" => 100,
            "spotify.exe" => 100,
            "epicgameslauncher.exe" => 100,
            "riotclientservices.exe" => 100,
            "obs64.exe" => 100,

            _ => 50
        };
    }

    // ----------------------------
    // Категории приложений
    // ----------------------------
    private string GuessCategory(string name)
    {
        var n = name.ToLowerInvariant();

        if (n.Contains("steam") || n.Contains("epic") || n.Contains("riot"))
            return "Game Launcher";

        if (n.Contains("discord") || n.Contains("telegram"))
            return "Messenger";

        if (n.Contains("chrome") || n.Contains("edge") || n.Contains("firefox"))
            return "Browser";

        if (n.Contains("visual studio") || n.Contains("code") || n.Contains("cursor"))
            return "IDE";

        if (n.Contains("spotify"))
            return "Media";

        return "Application";
    }
}