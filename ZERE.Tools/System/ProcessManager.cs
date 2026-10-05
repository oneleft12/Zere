using System.Diagnostics;

namespace ZERE.Tools.System;

public class ProcessManager
{
    public List<Process> GetProcesses()
    {
        return Process.GetProcesses()
            .OrderBy(p => p.ProcessName)
            .ToList();
    }

    public List<Process> Find(string name)
    {
        return Process.GetProcesses()
            .Where(p =>
                p.ProcessName.Contains(
                    name,
                    StringComparison.OrdinalIgnoreCase))
            .OrderBy(p => p.ProcessName)
            .ToList();
    }

    public bool Kill(string name)
    {
        var process = Process.GetProcesses()
            .FirstOrDefault(p =>
                p.ProcessName.Equals(
                    name,
                    StringComparison.OrdinalIgnoreCase));

        if (process == null)
            return false;

        try
        {
            process.Kill(true);
        }
        catch (InvalidOperationException)
        {
            return false;
        }

        return true;
    }
}