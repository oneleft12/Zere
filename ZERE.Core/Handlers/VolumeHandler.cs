using ZERE.Tools.Windows.Volume;

namespace ZERE.Core.Handlers;

public class VolumeHandler : IZereHandler
{
    private readonly VolumeService _service;
    private readonly VolumeCommandRouter _router = new();

    public VolumeHandler(VolumeService service)
    {
        _service = service;
    }

    public bool CanHandle(string message)
    {
        var lower = message.ToLower();

        return lower.StartsWith("громкость") ||
               lower.Contains("сделай громче") ||
               lower.Contains("сделай тише") ||
               lower.Contains("выключи звук") ||
               lower.Contains("включи звук") ||
               lower.Contains("громче") ||
               lower.Contains("тише") ||
               lower.Contains("прибавь") ||
               lower.Contains("убавь") ||
               lower.Contains("увеличь громкость") ||
               lower.Contains("уменьши громкость") ||
               lower.Contains("погромче") ||
               lower.Contains("потише") ||
               lower.Contains("замути") ||
               lower.Contains("размути") ||
               lower.Contains("приглуши") ||
               lower.Contains("mute") ||
               lower.Contains("unmute") ||
               lower.Contains("без звука") ||
               lower.Contains("верни звук") ||
               lower.Contains("звук вверх") ||
               lower.Contains("звук вниз") ||
               lower.Contains("громкость вверх") ||
               lower.Contains("громкость вниз") ||
               lower.Contains("больше звука") ||
               lower.Contains("меньше звука");
    }

    public Task<string?> HandleAsync(string message)
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
