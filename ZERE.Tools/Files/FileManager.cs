namespace ZERE.Tools.Files;

public class FileManager
{
    private readonly string _desktop;
    private string? _lastFile;

    /// <summary>Имя последнего созданного файла в этой сессии (для «удали его»).</summary>
    public string? LastCreatedName => _lastFile;

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

    /// <summary>
    /// Резолвит имя из реплики пользователя в путь внутри рабочего стола.
    /// Возвращает null, если путь выходит за пределы рабочего стола
    /// (абсолютный путь, "..", пустое имя) — защита от path traversal.
    /// </summary>
    private string? ResolvePath(string name)
    {
        if (string.IsNullOrWhiteSpace(name))
            return null;

        // Только относительные имена: абсолютные и drive-relative пути запрещены.
        if (Path.IsPathRooted(name))
            return null;

        var normalized = name.Replace('/', Path.DirectorySeparatorChar);
        var segments = normalized.Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries);

        if (segments.Any(s => s == ".." || s == "."))
            return null;

        try
        {
            var desktopFull = Path.GetFullPath(_desktop)
                .TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var full = Path.GetFullPath(Path.Combine(_desktop, name));

            // Итоговый путь обязан быть внутри рабочего стола.
            if (!full.StartsWith(desktopFull, StringComparison.OrdinalIgnoreCase))
                return null;

            return full;
        }
        catch (Exception)
        {
            return null;
        }
    }

    public string CreateFolder(string name)
    {
        var path = ResolvePath(name);

        if (path == null)
            return $"Недопустимый путь «{name}»: можно создавать только внутри рабочего стола.";

        if (Directory.Exists(path))
            return $"Папка \"{name}\" уже существует.";

        Directory.CreateDirectory(path);

        return $"Папка \"{name}\" создана.";
    }

    public string CreateFile(string name)
    {
        var path = ResolvePath(name);

        if (path == null)
            return $"Недопустимый путь «{name}»: можно создавать только внутри рабочего стола.";

        if (File.Exists(path))
            return $"Файл \"{name}\" уже существует.";

        File.WriteAllText(path, "");
        _lastFile = Path.GetFileName(path);

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

    /// <summary>Существует ли файл с таким именем внутри рабочего стола.</summary>
    public bool Exists(string name)
    {
        var path = ResolvePath(name);
        return path != null && File.Exists(path);
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