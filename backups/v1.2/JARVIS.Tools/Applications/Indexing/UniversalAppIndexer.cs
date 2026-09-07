using System.Text.Json;

namespace JARVIS.Tools.Applications.Indexing;

public class UniversalAppIndexer
{
    private readonly List<IAppScanner> _scanners = new();

    private readonly Dictionary<string, AppInfo> _apps = new();

    private readonly string _indexPath;

    public UniversalAppIndexer()
    {
        var folder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JARVIS");

        Directory.CreateDirectory(folder);

        _indexPath = Path.Combine(folder, "app_index.json");
    }

    public void RegisterScanner(IAppScanner scanner)
    {
        _scanners.Add(scanner);
    }

    public int Count => _apps.Count;

    public IReadOnlyDictionary<string, AppInfo> GetApps()
    {
        return _apps;
    }

    public AppInfo? Find(string query)
    {
        query = query.ToLower().Trim();

        if (_apps.TryGetValue(query, out var exact))
            return exact;

        foreach (var app in _apps.Values.OrderByDescending(a => a.Priority))
        {
            if (app.Name.Contains(query, StringComparison.OrdinalIgnoreCase))
                return app;

            if (app.Aliases.Any(a =>
                    a.Equals(query, StringComparison.OrdinalIgnoreCase)))
                return app;
        }

        return null;
    }

    public void Build()
    {
        _apps.Clear();

        foreach (var scanner in _scanners)
        {
            foreach (var app in scanner.Scan())
            {
                _apps[app.Name.ToLower()] = app;
            }
        }

        Save();
    }

    public void Save()
    {
        var json = JsonSerializer.Serialize(
            _apps.Values,
            new JsonSerializerOptions
            {
                WriteIndented = true
            });

        File.WriteAllText(_indexPath, json);
    }

    public void Load()
    {
        if (!File.Exists(_indexPath))
            return;

        var json = File.ReadAllText(_indexPath);

        var apps = JsonSerializer.Deserialize<List<AppInfo>>(json);

        if (apps == null)
            return;

        _apps.Clear();

        foreach (var app in apps)
        {
            _apps[app.Name.ToLower()] = app;
        }
    }
}