namespace JARVIS.Core.Logging;

public class LogService
{
    private readonly string _logPath;

    public LogService()
    {
        var folder = Path.Combine(
            Directory.GetCurrentDirectory(),
            "logs");

        Directory.CreateDirectory(folder);

        var timestamp = DateTime.Now.ToString("yyyy-MM-dd_HH-mm-ss");
        _logPath = Path.Combine(folder, $"jarvis_{timestamp}.log");
    }

    public void Info(string message)
    {
        Write("INFO", message);
    }

    public void Warning(string message)
    {
        Write("WARN", message);
    }

    public void Error(string message)
    {
        Write("ERROR", message);
    }

    private void Write(string level, string message)
    {
        var line =
            $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] [{level}] {message}";

        File.AppendAllText(_logPath, line + Environment.NewLine);
    }
}