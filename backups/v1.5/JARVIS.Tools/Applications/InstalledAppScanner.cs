using System.Text.Json;

namespace JARVIS.Tools.Applications;

public class InstalledAppScanner
{
    private readonly Dictionary<string, string> _apps = new();
    private readonly RegistryScanner _registryScanner = new();
    private readonly string _indexPath;

    public InstalledAppScanner()
    {
        var folder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JARVIS");

        Directory.CreateDirectory(folder);

        _indexPath = Path.Combine(folder, "app_index.json");

        if (File.Exists(_indexPath))
        {
            LoadIndex();
        }
        else
        {
            Console.WriteLine("[Scanner] Создаю индекс приложений...");

            ScanStartMenu();

            foreach (var app in _registryScanner.Scan())
        {
            _apps[app.Name.ToLower()] = app.ExecutablePath;
        }

            SaveIndex();
        }
    }

    private void ScanStartMenu()
    {
        var folders = new[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.CommonStartMenu),
            Environment.GetFolderPath(Environment.SpecialFolder.StartMenu)
        };

        foreach (var folder in folders)
        {
            ScanFolder(folder);
        }
    }

    private void ScanFolder(string folder)
    {
        if (!Directory.Exists(folder))
            return;

        try
        {
            foreach (var shortcut in Directory.EnumerateFiles(folder, "*.lnk"))
            {
                var name = Path.GetFileNameWithoutExtension(shortcut).ToLower();

                if (!_apps.ContainsKey(name))
                    _apps[name] = shortcut;
            }

            foreach (var subFolder in Directory.EnumerateDirectories(folder))
            {
                ScanFolder(subFolder);
            }
        }
        catch (UnauthorizedAccessException)
        {
            // Пропускаем папки без доступа.
        }
    }

    public string? FindApplication(string name)
    {
        name = name.ToLower().Trim();

        if (_apps.TryGetValue(name, out var exact))
            return exact;

        foreach (var app in _apps)
        {
            if (app.Key.Contains(name))
                return app.Value;
        }

        return null;
    }

    public IReadOnlyDictionary<string, string> GetAllApps() => _apps;

    private void SaveIndex()
    {
        var json = JsonSerializer.Serialize(_apps, new JsonSerializerOptions
        {
            WriteIndented = true
        });

        File.WriteAllText(_indexPath, json);

        Console.WriteLine($"[Scanner] Индекс сохранён ({_apps.Count} приложений).");
    }

    private void LoadIndex()
    {
        var json = File.ReadAllText(_indexPath);

        var apps = JsonSerializer.Deserialize<Dictionary<string, string>>(json);

        if (apps == null)
            return;

        foreach (var app in apps)
            _apps[app.Key] = app.Value;

        Console.WriteLine($"[Scanner] Загружено {_apps.Count} приложений.");
    }

    public void RebuildIndex()
    {
        _apps.Clear();

        ScanStartMenu();

        foreach (var app in _registryScanner.Scan())
    {
    _apps[app.Name.ToLower()] = app.ExecutablePath;
    }

        SaveIndex();
    }
}