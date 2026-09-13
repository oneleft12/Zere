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
               lower.StartsWith("создай файл") ||
               lower.StartsWith("найди файл") ||
               lower.StartsWith("удали файл");
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
