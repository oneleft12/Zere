using System.Diagnostics;

namespace JARVIS.Tools.Windows;

public class ScreenCaptureService
{
    public string Capture()
    {
        var desktop = Environment.GetFolderPath(
            Environment.SpecialFolder.Desktop);

        var folder = Path.Combine(desktop, "JARVIS Screenshots");

        Directory.CreateDirectory(folder);

        var file = Path.Combine(
            folder,
            $"Screenshot_{DateTime.Now:yyyyMMdd_HHmmss}.png");

        var command =
            $"Add-Type -AssemblyName System.Windows.Forms;" +
            $"Add-Type -AssemblyName System.Drawing;" +
            "$bounds=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;" +
            "$bmp=New-Object System.Drawing.Bitmap($bounds.Width,$bounds.Height);" +
            "$g=[System.Drawing.Graphics]::FromImage($bmp);" +
            "$g.CopyFromScreen($bounds.Location,[System.Drawing.Point]::Empty,$bounds.Size);" +
            $"$bmp.Save('{file}');";

        Process.Start(new ProcessStartInfo
        {
            FileName = "powershell",
            Arguments = $"-NoProfile -ExecutionPolicy Bypass -Command \"{command}\"",
            CreateNoWindow = true,
            UseShellExecute = false
        })?.WaitForExit();

        return file;
    }
}