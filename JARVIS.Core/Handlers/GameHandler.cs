using JARVIS.Tools.Gaming;

namespace JARVIS.Core.Handlers;

public class GameHandler : IJarvisHandler
{
    private readonly GameGuardian _guardian = new();
    private readonly GameTracker _tracker = new();

    public bool CanHandle(string message)
    {
        var lower = message.ToLower();

        return lower == "игры" ||
               lower == "игровая статистика" ||
               lower == "сбросить игровую статистику";
    }

    public Task<string> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var lower = message.ToLower();

        if (lower == "игры")
        {
            var games = _guardian.GetRunningGames();

            if (games.Count == 0)
                return "Сейчас игры не запущены.";

            return "Сейчас запущены игры:\n\n" +
                   string.Join("\n", games.Select(g => $"• {g}"));
        }

        if (lower == "игровая статистика")
        {
            var stats = _tracker.TodayStats();

            if (stats.Count == 0)
                return "Сегодня игр не обнаружено.";

            return "Сегодня вы играли:\n\n" +
                   string.Join(
                       "\n",
                       stats.Select(s =>
                           $"• {s.GameName} — {s.TodayTime:hh\\:mm\\:ss}"));
        }

        if (lower == "сбросить игровую статистику")
        {
            _tracker.ResetToday();
            return "Игровая статистика очищена.";
        }

        return "Игровая команда не распознана.";
    }
}