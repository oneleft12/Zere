namespace JARVIS.Tools.Windows;

public enum WindowsCommandType
{
    None,
    Screenshot,
    VolumeUp,
    VolumeDown,
    VolumeMute,
    VolumeUnmute,

    OpenDownloads,
    OpenDesktop,
    OpenDocuments,

    Shutdown,
    Restart,
    Sleep,
    Lock,

    CpuInfo,
    GpuInfo,
    RamInfo,
    WindowsInfo,
    RunningProcesses
}