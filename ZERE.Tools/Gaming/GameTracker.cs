using ZERE.Tools.Gaming.Models;

namespace ZERE.Tools.Gaming;

public class GameTracker
{
    private readonly GameGuardian _guardian = new();

    private readonly Dictionary<string, GameStat> _stats = new();

    private readonly Dictionary<string, DateTime> _started = new();

    public void Update()
    {
        var running = _guardian.GetRunningGames();

        foreach (var game in running)
        {
            if (!_started.ContainsKey(game))
            {
                _started[game] = DateTime.Now;
            }
        }

        foreach (var game in _started.Keys.ToList())
        {
            if (!running.Contains(game))
            {
                var played = DateTime.Now - _started[game];

                if (!_stats.ContainsKey(game))
                    _stats[game] = new GameStat
                    {
                        GameName = game
                    };

                _stats[game].TodayTime += played;
                _stats[game].LastPlayed = DateTime.Now;
                _stats[game].IsRunning = false;

                _started.Remove(game);
            }
        }

        foreach (var game in running)
        {
            if (!_stats.ContainsKey(game))
                _stats[game] = new GameStat
                {
                    GameName = game
                };

            _stats[game].IsRunning = true;
        }
    }

    public List<GameStat> TodayStats()
    {
        Update();
        return _stats.Values.OrderByDescending(x => x.TodayTime).ToList();
    }

    public void ResetToday()
    {
        _stats.Clear();
        _started.Clear();
    }
}