using System.Diagnostics;
using System.Runtime.InteropServices;

namespace JARVIS.Tools.System;

public class PowerController
{
    [DllImport("user32.dll")]
    private static extern bool LockWorkStation();

    public void Shutdown()
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = "shutdown",
            Arguments = "/s /t 0",
            CreateNoWindow = true,
            UseShellExecute = false
        });
    }

    public void Restart()
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = "shutdown",
            Arguments = "/r /t 0",
            CreateNoWindow = true,
            UseShellExecute = false
        });
    }

    public void Sleep()
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = "rundll32.exe",
            Arguments = "powrprof.dll,SetSuspendState 0,1,0",
            CreateNoWindow = true,
            UseShellExecute = false
        });
    }

    public void Lock()
    {
        LockWorkStation();
    }
}