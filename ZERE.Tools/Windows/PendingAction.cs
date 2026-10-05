namespace ZERE.Tools.Windows;

public enum PendingAction
{
    None,
    Shutdown,
    Restart,
    Sleep,

    /// <summary>Завершение процессов — Target: имя процесса.</summary>
    KillProcess,

    /// <summary>Удаление файла — Target: имя файла на рабочем столе.</summary>
    DeleteFile
}
