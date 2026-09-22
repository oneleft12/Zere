"""Отслеживание времени в играх (порт GameTracker.cs)."""

from __future__ import annotations

from datetime import datetime

from jarvis.tools.gaming.game_guardian import GameGuardian
from jarvis.tools.gaming.models.game_stat import GameStat


class GameTracker:
    def __init__(self) -> None:
        self._guardian = GameGuardian()
        self._stats: dict[str, GameStat] = {}
        self._started: dict[str, datetime] = {}

    def update(self) -> None:
        running = self._guardian.get_running_games()

        for game in running:
            if game not in self._started:
                self._started[game] = datetime.now()

        for game in list(self._started.keys()):
            if game not in running:
                played = datetime.now() - self._started[game]

                if game not in self._stats:
                    self._stats[game] = GameStat(game_name=game)

                self._stats[game].today_time += played
                self._stats[game].last_played = datetime.now()
                self._stats[game].is_running = False

                del self._started[game]

        for game in running:
            if game not in self._stats:
                self._stats[game] = GameStat(game_name=game)

            self._stats[game].is_running = True

    def today_stats(self) -> list[GameStat]:
        self.update()
        # OrderByDescending(x => x.TodayTime)
        return sorted(
            self._stats.values(),
            key=lambda stat: stat.today_time,
            reverse=True,
        )

    def reset_today(self) -> None:
        self._stats.clear()
        self._started.clear()
