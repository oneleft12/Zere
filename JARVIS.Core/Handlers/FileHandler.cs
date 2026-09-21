using JARVIS.Tools.Files;
using JARVIS.Tools.Windows;

namespace JARVIS.Core.Handlers;

public class FileHandler : IJarvisHandler
{
    private readonly FileManager _files;
    private readonly FileCommandRouter _router = new();
    private readonly SafeActionManager _safeActions;

    public FileHandler(FileManager files, SafeActionManager safeActions)
    {
        _files = files;
        _safeActions = safeActions;
    }

    public bool CanHandle(string message)
    {
        var lower = message.ToLower();

        return lower.StartsWith("создай папку") ||
               lower.StartsWith("создай директорию") ||
               lower.StartsWith("новая папка") ||
               lower.StartsWith("замокай папку") ||
               lower.StartsWith("папка ") ||
               lower.StartsWith("создай файл") ||
               lower.StartsWith("новый файл") ||
               lower.StartsWith("создай документ") ||
               lower.StartsWith("замокай файл") ||
               lower.StartsWith("документ ") ||
               lower.StartsWith("найди файл") ||
               lower.StartsWith("найти файл") ||
               lower.StartsWith("поищи файл") ||
               lower.StartsWith("где файл") ||
               lower.StartsWith("розыск файла") ||
               lower.StartsWith("удали файл") ||
               lower.StartsWith("убери файл") ||
               lower.StartsWith("удалить файл") ||
               lower.StartsWith("стереть ") ||
               lower.StartsWith("удали ") ||
               lower.StartsWith("удали его") ||
               lower.StartsWith("удалить его");
    }

    public Task<string> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var command = _router.Parse(message);

        switch (command.Type)
        {
            case FileCommandType.CreateFolder:
                return _files.CreateFolder(command.Value);

            case FileCommandType.CreateFile:
                return _files.CreateFile(command.Value);

            case FileCommandType.FindFile:
                return _files.FindFile(command.Value);

            case FileCommandType.DeleteFile:
                _safeActions.Request(PendingAction.None);

                return _files.DeleteFile(command.Value)
                    ? $"Файл \"{command.Value}\" удалён."
                    : $"Файл \"{command.Value}\" не найден.";
        }

        return "Команда файлов не распознана.";
    }
}
