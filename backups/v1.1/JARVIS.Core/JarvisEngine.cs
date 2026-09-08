using JARVIS.AI;
using JARVIS.Core.Intent;
using JARVIS.Tools.Applications;

namespace JARVIS.Core;

public class JarvisEngine
{
    private readonly OllamaClient _ai = new();
    private readonly ApplicationLauncher _launcher = new();
    private readonly IntentRouter _router = new();

    public async Task<string> ProcessAsync(string message)
    {
        var lower = message.ToLower().Trim();

        // ==========================================
// FILE MANAGER
// ==========================================

var fileCommand = _fileRouter.Parse(message);

switch (fileCommand.Type)
{
    case FileCommandType.CreateFolder:
    {
        var path = _fileManager.CreateFolder(fileCommand.Value);
        return $"Папка создана:\n{path}";
    }

    case FileCommandType.CreateFile:
    {
        var path = _fileManager.CreateFile(fileCommand.Value);
        return $"Файл создан:\n{path}";
    }

    case FileCommandType.ReadFile:
    {
        return _fileManager.ReadFile(fileCommand.Value);
    }

    case FileCommandType.WriteFile:
    {
        var path = _fileManager.WriteFile(fileCommand.Value);
        return $"Записал текст в файл:\n{path}";
    }

    case FileCommandType.SearchFile:
    {
        var files = _fileManager.SearchFile(fileCommand.Value);

        if (files.Count == 0)
            return "Файлы не найдены.";

        return string.Join("\n", files);
    }

    case FileCommandType.SearchFolder:
    {
        var folders = _fileManager.SearchFolder(fileCommand.Value);

        if (folders.Count == 0)
            return "Папки не найдены.";

        return string.Join("\n", folders);
    }

    case FileCommandType.DeleteFile:
    {
        var files = _fileManager.SearchFile(fileCommand.Value);

        if (files.Count == 0)
            return "Файл не найден.";

        _pendingDeleteFile = files.First();

        return $"Удалить файл?\n{_pendingDeleteFile}\n\nНапишите «да» или «нет».";
    }
}

        // Новая команда
        if (lower == "покажи приложения")
        {
            var apps = _launcher.GetInstalledApplications();

            return "Найдено приложений: " + apps.Count +
                   "\n\n" +
                   string.Join("\n", apps.Take(40));
        }
            if (lower == "обнови индекс")
        {
    _launcher.RebuildIndex();
            return "Индекс приложений успешно обновлён.";
        }
                var intent = _router.Parse(message);

            switch (intent.Type)
        {
            case IntentType.OpenApplication:

                var success = _launcher.Launch(intent.Value);

                return success
                    ? $"Открываю {intent.Value}."
                    : $"Не удалось найти приложение «{intent.Value}».";

            default:
                return await _ai.GenerateAsync(message);
        }
    }
}