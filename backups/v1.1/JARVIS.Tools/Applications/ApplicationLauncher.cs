using System.Diagnostics;
using System.Linq;

namespace JARVIS.Tools.Applications;

public class ApplicationLauncher
{
    private readonly Dictionary<string, string> _systemApps = new()
    {
        { "калькулятор", "calc.exe" },
        { "блокнот", "notepad.exe" },
        { "проводник", "explorer.exe" },
        { "paint", "mspaint.exe" }
    };

    private readonly InstalledAppScanner _scanner = new();

    public ApplicationLauncher()
    {
        Console.WriteLine("\n===== ИНДЕКС ПРИЛОЖЕНИЙ JARVIS =====");

        foreach (var app in _scanner.GetAllApps().Take(20))
        {
            Console.WriteLine($"• {app.Key}");
        }

        Console.WriteLine("====================================\n");
    }
    public List<string> GetInstalledApplications()
    {
    return _scanner
        .GetAllApps()
        .Keys
        .OrderBy(x => x)
        .ToList();
    }
public void RebuildIndex()
    {
    _scanner.RebuildIndex();
    }
public bool Launch(string appName)
    {  
    appName = appName.ToLower().Trim();

    if (AppAliasProvider.Aliases.TryGetValue(appName, out var alias))
        appName = alias;

    Console.WriteLine($"[TOOLS] Ищу приложение: {appName}");

    // Системные приложения
    if (_systemApps.TryGetValue(appName, out var executable))
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = true
        });

        return true;
    }

    var path = _scanner.FindApplication(appName);

    if (path == null)
    {
        Console.WriteLine("[TOOLS] Не найдено.");
        return false;
    }

    Console.WriteLine($"[TOOLS] Найдено: {path}");

    // Discord устанавливается через Update.exe
    if (appName == "discord" && path.EndsWith("Update.exe", StringComparison.OrdinalIgnoreCase))
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = path,
            Arguments = "--processStart Discord.exe",
            UseShellExecute = true
        });

        return true;
    }

    Process.Start(new ProcessStartInfo
    {
        FileName = path,
        UseShellExecute = true
    });

    return true;
  }
}