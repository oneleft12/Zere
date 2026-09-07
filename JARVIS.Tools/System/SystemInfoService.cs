using System.Management;
using System.Diagnostics;

namespace JARVIS.Tools.System;

public class SystemInfoService
{
    public string GetCpu()
    {
        return QuerySingle("Win32_Processor", "Name");
    }

    public string GetGpu()
    {
        return QuerySingle("Win32_VideoController", "Name");
    }

    public string GetRam()
    {
        using var searcher = new ManagementObjectSearcher(
            "SELECT TotalPhysicalMemory FROM Win32_ComputerSystem");

        foreach (ManagementObject obj in searcher.Get())
        {
            var bytes = Convert.ToDouble(obj["TotalPhysicalMemory"]);

            var gb = Math.Round(bytes / 1024 / 1024 / 1024);

            return $"{gb} ГБ";
        }

        return "Не удалось определить RAM.";
    }

    public string GetWindowsVersion()
    {
        return Environment.OSVersion.VersionString;
    }

    public List<string> GetRunningProcesses(int limit = 15)
    {
       return Process.GetProcesses()
        .OrderBy(p => p.ProcessName)
        .Take(limit)
        .Select(p => p.ProcessName)
        .ToList();
    }

    private string QuerySingle(string className, string property)
    {
        using var searcher =
            new ManagementObjectSearcher(
                $"SELECT {property} FROM {className}");

        foreach (ManagementObject obj in searcher.Get())
        {
            return obj[property]?.ToString() ?? "Не найдено.";
        }

        return "Не найдено.";
    }
}