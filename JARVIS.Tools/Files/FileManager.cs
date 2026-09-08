namespace JARVIS.Tools.Files;

public class FileManager
{
    private readonly string _desktop;

    public FileManager()
    {
        var oneDriveDesktop = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "OneDrive",
            "Desktop");

        _desktop = Directory.Exists(oneDriveDesktop)
            ? oneDriveDesktop
            : Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
    }

    public string CreateFolder(string name)
    {
        var path = Path.Combine(_desktop, name);

        if (Directory.Exists(path))
            return $"Папка \"{name}\" уже существует.";

        Directory.CreateDirectory(path);

        return $"Папка \"{name}\" создана.";
    }

    public string CreateFile(string name)
    {
        var path = Path.Combine(_desktop, name);

        if (File.Exists(path))
            return $"Файл \"{name}\" уже существует.";

        File.WriteAllText(path, "");

        return $"Файл \"{name}\" создан.";
    }

    public string FindFile(string query)
    {
        var matches = Directory
            .EnumerateFiles(_desktop, "*", SearchOption.AllDirectories)
            .Where(file =>
            {
                var fileName = Path.GetFileName(file);
                var noExt = Path.GetFileNameWithoutExtension(file);

                return fileName.Contains(query, StringComparison.OrdinalIgnoreCase)
                    || noExt.Contains(query, StringComparison.OrdinalIgnoreCase);
            })
            .Take(10)
            .ToList();

        if (matches.Count == 0)
            return $"Файл \"{query}\" не найден.";

        return "Найденные файлы:\n\n" +
               string.Join("\n\n",
                    matches.Select(file =>
                        $"• {Path.GetFileName(file)}\n{file}"));
    }

    public bool DeleteFile(string name)
    {
        var file = Directory
            .EnumerateFiles(_desktop, "*", SearchOption.AllDirectories)
            .FirstOrDefault(f =>
                Path.GetFileName(f)
                    .Equals(name, StringComparison.OrdinalIgnoreCase));

        if (file == null)
            return false;

        File.Delete(file);

        return true;
    }
}