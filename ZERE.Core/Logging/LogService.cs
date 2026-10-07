using ZERE.AI;

namespace ZERE.Core.Logging;

public class LogService
{
    private readonly string _logPath;
    private readonly object _lock = new();

    public LogService()
    {
        var folder = Path.Combine(
            Directory.GetCurrentDirectory(),
            "logs");

        Directory.CreateDirectory(folder);

        var timestamp = DateTime.Now.ToString("yyyy-MM-dd_HH-mm-ss");
        _logPath = Path.Combine(folder, $"zere_{timestamp}.log");
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
        // Ключ API не должен попасть в логи даже внутри текста исключения
        // (SecretRedactor — паритет с redact_secrets в Python-редакции).
        var line =
            $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] [{level}] {SecretRedactor.Redact(message)}";

        lock (_lock)
        {
            File.AppendAllText(_logPath, line + Environment.NewLine);
        }
    }
}