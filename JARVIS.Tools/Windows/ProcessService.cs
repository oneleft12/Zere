using System.Diagnostics;

namespace JARVIS.Tools.Windows.Processes;

public class ProcessService
{
    /// <summary>
    /// Системные процессы, которых нельзя касаться командами ассистента.
    /// </summary>
    private static readonly HashSet<string> ProtectedNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "system",
        "idle",
        "registry",
        "smss",
        "csrss",
        "wininit",
        "winlogon",
        "services",
        "lsass",
        "svchost",
        "memcompression",
        "memory compression"
    };

    /// <summary>
    /// Запрещено ли завершение процесса с таким именем
    /// (сравнение без учёта .exe и регистра).
    /// </summary>
    public static bool IsProtected(string name)
    {
        var normalized = Normalize(name);
        return normalized.Length > 0 && ProtectedNames.Contains(normalized);
    }

    private static string Normalize(string name)
    {
        var trimmed = (name ?? "").Trim();
        return trimmed.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
            ? trimmed[..^4]
            : trimmed;
    }

    public List<ProcessInfo> GetProcesses()
    {
        var list = new List<ProcessInfo>();

        foreach (var process in Process.GetProcesses())
        {
            try
            {
                list.Add(new ProcessInfo
                {
                    Id = process.Id,
                    Name = process.ProcessName,
                    MemoryMb = Math.Round(process.WorkingSet64 / 1024d / 1024d, 1),
                    Responding = process.Responding
                });
            }
            catch
            {
                // Некоторые процессы недоступны.
            }
            finally
            {
                // Не копим native-хэндлы при частых запросах.
                process.Dispose();
            }
        }

        return list.OrderByDescending(p => p.MemoryMb).ToList();
    }

    public List<ProcessInfo> Search(string name)
    {
        return GetProcesses()
            .Where(p => p.Name.Contains(name, StringComparison.OrdinalIgnoreCase))
            .ToList();
    }

    /// <summary>
    /// Точное совпадение имени (без учёта регистра и .exe) —
    /// тот же предикат, что и у <see cref="Kill"/>.
    /// </summary>
    public List<ProcessInfo> SearchExact(string name)
    {
        var normalized = Normalize(name);

        return GetProcesses()
            .Where(p => p.Name.Equals(normalized, StringComparison.OrdinalIgnoreCase))
            .ToList();
    }

    /// <summary>
    /// Завершает все процессы с точным именем (вместе с дочерними).
    /// Возвращает true только если завершён хотя бы один процесс.
    /// </summary>
    public bool Kill(string name)
    {
        if (IsProtected(name))
            return false;

        var processes = Process.GetProcessesByName(Normalize(name));

        if (processes.Length == 0)
            return false;

        var killed = 0;

        foreach (var process in processes)
        {
            try
            {
                process.Kill(true);
                killed++;
            }
            catch
            {
                // Процесс мог завершиться сам или нет прав — не считаем успехом.
            }
            finally
            {
                process.Dispose();
            }
        }

        return killed > 0;
    }
}
