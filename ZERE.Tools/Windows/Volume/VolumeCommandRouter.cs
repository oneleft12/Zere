using System.Text.RegularExpressions;

namespace ZERE.Tools.Windows.Volume;

public class VolumeCommandRouter
{
    public (VolumeCommandType Type, int Value) Parse(string message)
    {
        var text = message.ToLower().Trim();

        // === Установка конкретного значения ===
        // "громкость 50", "звука 75", "volume 80"
        var match = Regex.Match(text, @"(громкость|звук[а]?|volume)\s+(\d{1,3})");
        if (match.Success)
        {
            var value = int.Parse(match.Groups[2].Value);
            value = Math.Clamp(value, 0, 100);
            return (VolumeCommandType.SetVolume, value);
        }

        // === Увеличение громкости ===
        if (text.Contains("сделай громче") ||
            text.Contains("громче") ||
            text.Contains("прибавь звук") ||
            text.Contains("прибавь громкость") ||
            text.Contains("увеличь громкость") ||
            text.Contains("погромче") ||
            text.Contains("громкость вверх") ||
            text.Contains("звук вверх") ||
            text.Contains("больше звука"))
        {
            return (VolumeCommandType.VolumeUp, 10);
        }

        // === Уменьшение громкости ===
        if (text.Contains("сделай тише") ||
            text.Contains("тише") ||
            text.Contains("убавь звук") ||
            text.Contains("убавь громкость") ||
            text.Contains("уменьши громкость") ||
            text.Contains("потише") ||
            text.Contains("громкость вниз") ||
            text.Contains("звук вниз") ||
            text.Contains("меньше звука"))
        {
            return (VolumeCommandType.VolumeDown, 10);
        }

        // === Выключение звука ===
        if (text.Contains("выключи звук") ||
            text.Contains("замути") ||
            text.Contains("без звука") ||
            text.Contains("приглуши") ||
            text.Contains("mute") ||
            text.Contains("mute звук") ||
            text.Contains("выключи звуки"))
        {
            return (VolumeCommandType.Mute, 0);
        }

        // === Включение звука ===
        if (text.Contains("включи звук") ||
            text.Contains("размути") ||
            text.Contains("верни звук") ||
            text.Contains("включи звуки") ||
            text.Contains("unmute") ||
            text.Contains("unmute звук"))
        {
            return (VolumeCommandType.UnMute, 0);
        }

        return (VolumeCommandType.None, 0);
    }
}
