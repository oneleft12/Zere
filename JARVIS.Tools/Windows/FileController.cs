using System.Diagnostics;

namespace JARVIS.Tools.Windows;

public class FileController
{
    private static void Open(string path)
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = path,
            UseShellExecute = true
        });
    }

    public void OpenDownloads()
    {
        Open(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "Downloads"));
    }

    public void OpenDesktop()
    {
        Open(Environment.GetFolderPath(
            Environment.SpecialFolder.Desktop));
    }

    public void OpenDocuments()
    {
        Open(Environment.GetFolderPath(
            Environment.SpecialFolder.MyDocuments));
    }
}