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

    public bool UnMute()
    {
        try
        {
            var deviceEnumerator = (IMMDeviceEnumerator)new MMDeviceEnumerator();
            deviceEnumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia, out var device);

            var volumeInterface = device.Activate(typeof(IAudioEndpointVolume).GUID, 0, IntPtr.Zero, out var volumePtr);
            var volume = (IAudioEndpointVolume)Marshal.GetObjectForIUnknown(volumeInterface);

            volume.SetMute(false, Guid.Empty);

            Marshal.ReleaseComObject(volume);
            Marshal.ReleaseComObject(device);
            Marshal.ReleaseComObject(deviceEnumerator);

            return true;
        }
        catch
        {
            return false;
        }
    }

    public bool SetVolume(int value)
    {
        try
        {
            value = Math.Clamp(value, 0, 100);

            var deviceEnumerator = (IMMDeviceEnumerator)new MMDeviceEnumerator();
            deviceEnumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia, out var device);

            var volumeInterface = device.Activate(typeof(IAudioEndpointVolume).GUID, 0, IntPtr.Zero, out var volumePtr);
            var volume = (IAudioEndpointVolume)Marshal.GetObjectForIUnknown(volumeInterface);

            volume.SetMasterVolumeLevelScalar(value / 100.0f, Guid.Empty);

            Marshal.ReleaseComObject(volume);
            Marshal.ReleaseComObject(device);
            Marshal.ReleaseComObject(deviceEnumerator);

            return true;
        }
        catch
        {
            return false;
        }
    }

    [ComImport]
    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceEnumerator
    {
        [PreserveSig]
        int EnumAudioEndpoints(DataFlow dataFlow, int dwStateMask, out IMMDeviceCollection ppDevices);

        [PreserveSig]
        int GetDefaultAudioEndpoint(DataFlow dataFlow, Role role, out IMMDevice ppEndpoint);
    }

    [ComImport]
    [Guid("D666063F-1587-4E43-81F1-B948E807363F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDevice
    {
        [PreserveSig]
        int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
    }

    [ComImport]
    [Guid("5CDF2C82-841E-4546-9722-0CF74078229A")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioEndpointVolume
    {
        [PreserveSig]
        int NotImpl1();

        [PreserveSig]
        int NotImpl2();

        [PreserveSig]
        int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);

        [PreserveSig]
        int GetMasterVolumeLevelScalar(out float pfLevel);

        [PreserveSig]
        int NotImpl3();

        [PreserveSig]
        int NotImpl4();

        [PreserveSig]
        int SetMute([MarshalAs(UnmanagedType.Bool)] bool pbMute, Guid pguidEventContext);

        [PreserveSig]
        int GetMute([MarshalAs(UnmanagedType.Bool)] out bool pbMute);
    }

    [ComImport]
    [Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    private class MMDeviceEnumerator
    {
    }

    [ComImport]
    [Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceCollection
    {
    }

    private enum DataFlow
    {
        Render = 0,
        Capture = 1,
        All = 2
    }

    private enum Role
    {
        Console = 0,
        Multimedia = 1,
        Communications = 2
    }
}
