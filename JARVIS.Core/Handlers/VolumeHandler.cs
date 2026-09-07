using JARVIS.Tools.Windows.Volume;

namespace JARVIS.Core.Handlers;

public class VolumeHandler : IJarvisHandler
{
    private readonly VolumeService _service = new();
    private readonly VolumeCommandRouter _router = new();

    public bool CanHandle(string message)
    {
        var lower = message.ToLower();

        return lower.StartsWith("громкость") ||
               lower == "сделай громче" ||
               lower == "сделай тише" ||
               lower == "выключи звук" ||
               lower == "включи звук";
    }

    public Task<string> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var command = _router.Parse(message);

        return command.Type switch
        {
            VolumeCommandType.SetVolume =>
                _service.SetVolume(command.Value)
                    ? $"Громкость установлена на {command.Value}%."
                    : "Не удалось изменить громкость.",

            VolumeCommandType.VolumeUp =>
                _service.VolumeUp()
                    ? "Громкость увеличена."
                    : "Не удалось увеличить громкость.",

            VolumeCommandType.VolumeDown =>
                _service.VolumeDown()
                    ? "Громкость уменьшена."
                    : "Не удалось уменьшить громкость.",

            VolumeCommandType.Mute =>
                _service.Mute()
                    ? "Звук выключен."
                    : "Не удалось выключить звук.",

            VolumeCommandType.UnMute =>
                _service.UnMute()
                    ? "Звук включён."
                    : "Не удалось включить звук.",

            _ => "Команда громкости не распознана."
        };
    }
}