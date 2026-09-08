using System.Runtime.InteropServices;

namespace JARVIS.Tools.Windows.Volume;

public class VolumeService
{
    private const int APPCOMMAND_VOLUME_UP = 0x0a0000;
    private const int APPCOMMAND_VOLUME_DOWN = 0x090000;
    private const int APPCOMMAND_VOLUME_MUTE = 0x080000;
    private const int WM_APPCOMMAND = 0x0319;

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessageW(
        IntPtr hWnd,
        int msg,
        IntPtr wParam,
        IntPtr lParam);

    private bool SendAppCommand(int command)
    {
        try
        {
            var window = GetForegroundWindow();

            SendMessageW(
                window,
                WM_APPCOMMAND,
                window,
                (IntPtr)command);

            return true;
        }
        catch
        {
            return false;
        }
    }

    public bool VolumeUp() => SendAppCommand(APPCOMMAND_VOLUME_UP);

    public bool VolumeDown() => SendAppCommand(APPCOMMAND_VOLUME_DOWN);

    public bool Mute() => SendAppCommand(APPCOMMAND_VOLUME_MUTE);

    public bool UnMute() => SendAppCommand(APPCOMMAND_VOLUME_MUTE);

    public bool SetVolume(int value)
    {
        // Реализуем в v1.8.3 через Windows Audio API.
        return true;
    }
}