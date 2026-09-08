namespace JARVIS.Tools.Windows;

public class WindowsCommandRouter
{
    public WindowsCommandType Parse(string message)
    {
        var text = message.ToLowerInvariant();

        // ===== ГРОМКОСТЬ =====

        if (text.Contains("увеличь громкость") || text.Contains("сделай громче"))
            return WindowsCommandType.VolumeUp;

        if (text.Contains("уменьши громкость") || text.Contains("сделай тише"))
            return WindowsCommandType.VolumeDown;

        if (text.Contains("выключи звук"))
            return WindowsCommandType.VolumeMute;

        if (text.Contains("включи звук"))
            return WindowsCommandType.VolumeUnmute;

        // ===== ПАПКИ =====

        if (text.Contains("загрузк"))
            return WindowsCommandType.OpenDownloads;

        if (text.Contains("рабочий стол"))
            return WindowsCommandType.OpenDesktop;

        if (text.Contains("документ"))
            return WindowsCommandType.OpenDocuments;

        // ===== ИНФОРМАЦИЯ О ПК =====

        if (text.Contains("процессор"))
            return WindowsCommandType.CpuInfo;

        if (text.Contains("видеокарта") || text.Contains("gpu"))
            return WindowsCommandType.GpuInfo;

        if (text.Contains("оперативной памяти") ||
            text.Contains("оперативка") ||
            text.Contains("ram"))
            return WindowsCommandType.RamInfo;

        if (text.Contains("какая версия windows"))
            return WindowsCommandType.WindowsInfo;

        if (text.Contains("что сейчас запущено") ||
            text.Contains("запущенные процессы"))
            return WindowsCommandType.RunningProcesses;

        // ===== ПИТАНИЕ =====

        if (text.Contains("выключи компьютер"))
            return WindowsCommandType.Shutdown;

        if (text.Contains("перезагрузи компьютер"))
            return WindowsCommandType.Restart;

        if (text.Contains("усыпи компьютер"))
            return WindowsCommandType.Sleep;

        if (text.Contains("заблокируй компьютер"))
            return WindowsCommandType.Lock;

        return WindowsCommandType.None;
    }
}