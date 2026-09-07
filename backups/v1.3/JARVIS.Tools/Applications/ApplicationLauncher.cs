using System.Diagnostics;
using JARVIS.Tools.Applications.Indexing;

namespace JARVIS.Tools.Applications;

public class ApplicationLauncher
{
    private readonly UniversalAppIndexer _indexer = new();

    private readonly Dictionary<string, string> _systemApps = new()
    {
        { "калькулятор", "calc.exe" },
        { "блокнот", "notepad.exe" },
        { "проводник", "explorer.exe" },
        { "paint", "mspaint.exe" }
    };

    public ApplicationLauncher()
    {
        Console.WriteLine($"\n[Indexer] Загружено {_indexer.Count} приложений.\n");
    }

    public bool Launch(string appName)
    {
        appName = appName.ToLower().Trim();

        // Алиасы
        if (AppAliasProvider.Aliases.TryGetValue(appName, out var alias))
            appName = alias;

        Console.WriteLine($"[TOOLS] Поиск: {appName}");

        // Системные приложения
        if (_systemApps.TryGetValue(appName, out var systemExe))
        {
            Start(systemExe);
            return true;
        }

        // Ищем в новом индексаторе
        var app = _indexer.Find(appName);

        if (app == null)
        {
            Console.WriteLine("[TOOLS] Не найдено.");
            return false;
        }

        Console.WriteLine($"[TOOLS] {app.Name}");
        Console.WriteLine($"[TOOLS] Источник: {app.Source}");
        Console.WriteLine($"[TOOLS] Путь: {app.ExecutablePath}");

        Start(app.ExecutablePath);

        return true;
    }

    public void RebuildIndex()
    {
        _indexer.Build();
    }

    public IReadOnlyDictionary<string, AppInfo> GetInstalledApplications()
    {
        return _indexer.GetApps();
    }

    private static void Start(string executable)
    {
        // Discord
        if (Path.GetFileName(executable).Equals("Update.exe", StringComparison.OrdinalIgnoreCase)
            && executable.Contains("Discord", StringComparison.OrdinalIgnoreCase))
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = executable,
                Arguments = "--processStart Discord.exe",
                UseShellExecute = true
            });

            return;
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = true
        });
    }
}