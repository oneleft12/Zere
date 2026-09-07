using System.Diagnostics;

namespace JARVIS.Tools.Windows.Processes;

public class ProcessService
{
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
        }

        return list.OrderByDescending(p => p.MemoryMb).ToList();
    }

    public List<ProcessInfo> Search(string name)
    {
        return GetProcesses()
            .Where(p => p.Name.Contains(name, StringComparison.OrdinalIgnoreCase))
            .ToList();
    }

    public bool Kill(string name)
    {
        var processes = Process.GetProcessesByName(name);

        if (processes.Length == 0)
            return false;

        foreach (var process in processes)
        {
            try
            {
                process.Kill(true);
            }
            catch
            {
            }
        }

        return true;
    }
}