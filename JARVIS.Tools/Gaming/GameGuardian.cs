using System.Diagnostics;

namespace JARVIS.Tools.Gaming;

public class GameGuardian
{
    public List<string> GetRunningGames()
    {
        var running = new List<string>();

        foreach (var process in Process.GetProcesses())
        {
            try
            {
                var processName = process.ProcessName.ToLower();

                foreach (var game in GameCatalog.Games)
                {
                    if (processName.Contains(game.Key))
                    {
                        running.Add(game.Value);
                    }
                }
            }
            catch
            {
            }
        }

        return running.Distinct().ToList();
    }

    public bool IsGaming()
    {
        return GetRunningGames().Count > 0;
    }
}