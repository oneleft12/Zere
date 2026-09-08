using System.Text;

namespace JARVIS.Tools.FileManager;

public class FileManagerService
{
    private readonly string _desktop =
        Environment.GetFolderPath(Environment.SpecialFolder.Desktop);

    // ---------- СОЗДАНИЕ ----------

    public string CreateFolder(string name)
    {
        var path = Path.Combine(_desktop, name);

        Directory.CreateDirectory(path);

        return path;
    }

    public string CreateFile(string name)
    {
        var path = Path.Combine(_desktop, name);

        if (!File.Exists(path))
            File.WriteAllText(path, "");

        return path;
    }

    // ---------- ЧТЕНИЕ ----------

    public string ReadFile(string name)
    {
        var path = Path.Combine(_desktop, name);

        if (!File.Exists(path))
            return "Файл не найден.";

        return File.ReadAllText(path, Encoding.UTF8);
    }

    // ---------- ЗАПИСЬ ----------

    public string WriteFile(string command)
    {
        var firstSpace = command.IndexOf(' ');

        if (firstSpace < 0)
            return "Укажите текст.";

        var file = command[..firstSpace];
        var text = command[(firstSpace + 1)..];

        var path = Path.Combine(_desktop, file);

        File.AppendAllText(path, text + Environment.NewLine);

        return path;
    }

    // ---------- ПОИСК ----------

    public List<string> SearchFile(string name)
    {
        var results = new List<string>();

        SearchDirectory(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            name,
            results,
            true);

        return results.Take(20).ToList();
    }

    public List<string> SearchFolder(string name)
    {
        var results = new List<string>();

        SearchDirectory(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            name,
            results,
            false);

        return results.Take(20).ToList();
    }

    private void SearchDirectory(
        string directory,
        string name,
        List<string> results,
        bool files)
    {
        try
        {
            if (files)
            {
                foreach (var file in Directory.GetFiles(directory))
                {
                    if (Path.GetFileName(file)
                        .Contains(name, StringComparison.OrdinalIgnoreCase))
                        results.Add(file);
                }
            }
            else
            {
                foreach (var folder in Directory.GetDirectories(directory))
                {
                    if (Path.GetFileName(folder)
                        .Contains(name, StringComparison.OrdinalIgnoreCase))
                        results.Add(folder);
                }
            }

            foreach (var dir in Directory.GetDirectories(directory))
                SearchDirectory(dir, name, results, files);
        }
        catch
        {
        }
    }

    // ---------- УДАЛЕНИЕ ----------

    public bool DeleteFile(string path)
    {
        if (!File.Exists(path))
            return false;

        File.Delete(path);

        return true;
    }
}