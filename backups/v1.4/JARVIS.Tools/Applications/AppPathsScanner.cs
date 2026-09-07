using Microsoft.Win32;
using JARVIS.Tools.Applications.Indexing;

namespace JARVIS.Tools.Applications;

public class AppPathsScanner : IAppScanner
{
    public IEnumerable<AppInfo> Scan()
    {
        var apps = new List<AppInfo>();

        ScanHive(Registry.LocalMachine, apps);
        ScanHive(Registry.CurrentUser, apps);

        return apps;
    }

    private void ScanHive(RegistryKey hive, List<AppInfo> apps)
    {
        using var key = hive.OpenSubKey(
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths");

        if (key == null)
            return;

        foreach (var subKeyName in key.GetSubKeyNames())
        {
            try
            {
                using var subKey = key.OpenSubKey(subKeyName);

                var exe = subKey?.GetValue("") as string;

                if (string.IsNullOrWhiteSpace(exe))
                    continue;

                var name = Path.GetFileNameWithoutExtension(subKeyName);

                apps.Add(new AppInfo
                {
                    Name = name,
                    ExecutablePath = exe.Trim('"'),
                    Source = "App Paths",
                    Priority = 95,
                    Category = "Application",
                    Aliases = AppAliasProvider.GetAliases(name)
                });
            }
            catch
            {
            }
        }
    }
}