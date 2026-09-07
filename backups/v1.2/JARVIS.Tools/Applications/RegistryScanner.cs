using Microsoft.Win32;

namespace JARVIS.Tools.Applications;

public class RegistryScanner
{
    public Dictionary<string, string> ScanInstalledPrograms()
    {
        var apps = new Dictionary<string, string>();

        ScanHive(Registry.LocalMachine,
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            apps);

        ScanHive(Registry.LocalMachine,
            @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            apps);

        ScanHive(Registry.CurrentUser,
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            apps);

        return apps;
    }

    private void ScanHive(RegistryKey hive, string path, Dictionary<string, string> apps)
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

            string? displayName = subKey.GetValue("DisplayName") as string;
            string? displayIcon = subKey.GetValue("DisplayIcon") as string;

            if (string.IsNullOrWhiteSpace(displayName) ||
                string.IsNullOrWhiteSpace(displayIcon))
            {
                continue;
            }

            string executable = displayIcon.Split(',')[0].Trim('"');
            
            apps[displayName.ToLowerInvariant()] = executable;
        }
        catch
        {
            // Игнорируем повреждённые записи.
        }
    }
}
}