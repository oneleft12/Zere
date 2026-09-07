using System.Text.RegularExpressions;

namespace JARVIS.Tools.Windows.Volume;

public class VolumeCommandRouter
{
    public (VolumeCommandType Type, int Value) Parse(string message)
    {
        var text = message.ToLower().Trim();

        var match = Regex.Match(text, @"громкость\s+(\d{1,3})");

        if (match.Success)
        {
            var value = int.Parse(match.Groups[1].Value);
            value = Math.Clamp(value, 0, 100);

            return (VolumeCommandType.SetVolume, value);
        }

        if (text == "сделай громче")
            return (VolumeCommandType.VolumeUp, 10);

        if (text == "сделай тише")
            return (VolumeCommandType.VolumeDown, 10);

        if (text == "выключи звук")
            return (VolumeCommandType.Mute, 0);

        if (text == "включи звук")
            return (VolumeCommandType.UnMute, 0);

        return (VolumeCommandType.None, 0);
    }
}