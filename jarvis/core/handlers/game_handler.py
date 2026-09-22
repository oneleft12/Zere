"""Порт JARVIS.Core/Handlers/GameHandler.cs."""

from __future__ import annotations

from datetime import timedelta

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.tools.gaming.game_guardian import GameGuardian
from jarvis.tools.gaming.game_tracker import GameTracker


class GameHandler(IJarvisHandler):
    def __init__(self, guardian: GameGuardian, tracker: GameTracker) -> None:
        self._guardian = guardian
        self._tracker = tracker

    def can_handle(self, message: str) -> bool:
        lower = message.lower()

        return (
            lower == "игры"
            or lower == "игровая статистика"
            or lower == "сбросить игровую статистику"
        )

    def handle(self, message: str) -> str:
        lower = message.lower()

        if lower == "игры":
            games = self._guardian.get_running_games()

            if len(games) == 0:
                return "Сейчас игры не запущены."

            return "Сейчас запущены игры:\n\n" + "\n".join([f"• {g}" for g in games])

        if lower == "игровая статистика":
            stats = self._tracker.today_stats()

            if len(stats) == 0:
                return "Сегодня игр не обнаружено."

            return "Сегодня вы играли:\n\n" + "\n".join(
                [f"• {s.game_name} — {self._format_time(s.today_time)}" for s in stats]
            )

        if lower == "сбросить игровую статистику":
            self._tracker.reset_today()
            return "Игровая статистика очищена."

        return "Игровая команда не распознана."

    @staticmethod
    def _format_time(value: object) -> str:
        """Формат TimeSpan 'HH:mm:ss' из C# ($"{s.TodayTime:HH\\:mm\\:ss}")."""
        if isinstance(value, timedelta):
            total = int(value.total_seconds())
            hours, remainder = divmod(total, 3600)
            minutes, seconds = divmod(remainder, 60)
            # В C# компонент часов TimeSpan (0-23)
            return f"{hours % 24:02d}:{minutes:02d}:{seconds:02d}"

        return str(value)
