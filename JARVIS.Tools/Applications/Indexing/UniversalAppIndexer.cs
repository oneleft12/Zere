using System.Text.Json;
using JARVIS.Tools.Applications;

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

        RegisterScanner(new StartMenuScanner());
        RegisterScanner(new RegistryScanner());
        RegisterScanner(new AppPathsScanner());
        RegisterScanner(new LocalAppDataScanner());

        Build();
    }

    public void RegisterScanner(IAppScanner scanner)
    {
        _scanners.Add(scanner);
    }

    public IReadOnlyDictionary<string, AppInfo> GetApps() => _apps;

    public int Count => _apps.Count;

    public void Build()
    {
        _apps.Clear();

        foreach (var scanner in _scanners)
        {
            foreach (var app in scanner.Scan())
            {
                _apps[app.Name.ToLowerInvariant()] = app;
            }
        }

        Save();
    }

    public void Save()
    {
        var json = JsonSerializer.Serialize(
            _apps.Values.OrderBy(a => a.Name).ToList(),
            new JsonSerializerOptions { WriteIndented = true });

        File.WriteAllText(_indexPath, json);
    }

    public AppInfo? Find(string query)
    {
        query = query.ToLowerInvariant().Trim();

        var candidates = new List<(AppInfo app, int score)>();

        foreach (var app in _apps.Values)
        {
            int score = 0;

            if (app.Name.Equals(query, StringComparison.OrdinalIgnoreCase))
                score = 100;

            else if (app.Aliases.Any(a =>
                a.Equals(query, StringComparison.OrdinalIgnoreCase)))
                score = 95;

            else if (app.Name.StartsWith(query, StringComparison.OrdinalIgnoreCase))
                score = 90;

            else if (app.Name.Contains(query, StringComparison.OrdinalIgnoreCase))
                score = 80;

            if (score > 0)
                candidates.Add((app, score));
        }

        return candidates
            .OrderByDescending(c => c.score)
            .ThenByDescending(c => c.app.Priority)
            .Select(c => c.app)
            .FirstOrDefault();
    }
}