using System.Runtime.InteropServices;

namespace JARVIS.Tools.Windows;

public class AudioController
{
    private const int KEYEVENTF_KEYUP = 0x0002;

    private const byte VK_VOLUME_MUTE = 0xAD;
    private const byte VK_VOLUME_DOWN = 0xAE;
    private const byte VK_VOLUME_UP = 0xAF;

    [DllImport("user32.dll")]
    private static extern void keybd_event(
        byte bVk,
        byte bScan,
        int dwFlags,
        int dwExtraInfo);

    private void Press(byte key)
    {
        keybd_event(key, 0, 0, 0);
        keybd_event(key, 0, KEYEVENTF_KEYUP, 0);
    }

    public void VolumeUp()
    {
        for (int i = 0; i < 5; i++)
            Press(VK_VOLUME_UP);
    }

    public void VolumeDown()
    {
        for (int i = 0; i < 5; i++)
            Press(VK_VOLUME_DOWN);
    }

    public void ToggleMute()
    {
        Press(VK_VOLUME_MUTE);
    }
}