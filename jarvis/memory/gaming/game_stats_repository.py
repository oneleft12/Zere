"""Порт JARVIS.Memory/Gaming/GameStatsRepository.cs."""

from __future__ import annotations

import datetime

from jarvis.memory.gaming.game_stat import GameStat
from jarvis.memory.gaming.game_stats_database import GameStatsDatabase


def _parse_datetime(value: str) -> datetime.datetime:
    # Аналог DateTime.Parse(value, CultureInfo.InvariantCulture).
    return datetime.datetime.fromisoformat(value)


class GameStatsRepository:
    def __init__(self) -> None:
        # C#: private readonly GameStatsDatabase _db = new();
        self._db = GameStatsDatabase()

    def add_minute(self, game: str) -> None:
        connection = self._db.create_connection()
        try:
            # C#: DateTime.Today.ToString("yyyy-MM-dd")
            today = datetime.date.today().strftime("%Y-%m-%d")
            connection.execute(
                """
        INSERT INTO GameStats(Game, Date, Minutes)
        VALUES($game, $date, 1)
        ON CONFLICT(Game, Date)
        DO UPDATE SET Minutes = Minutes + 1
        """,
                {"game": game, "date": today},
            )
        finally:
            connection.close()

    def get_today(self) -> list[GameStat]:
        connection = self._db.create_connection()
        try:
            cursor = connection.execute(
                """
        SELECT Id, Game, Date, Minutes
        FROM GameStats
        WHERE Date=$date
        ORDER BY Minutes DESC
        """,
                {"date": datetime.date.today().strftime("%Y-%m-%d")},
            )
            return [
                GameStat(
                    id=row[0],
                    game=row[1],
                    date=_parse_datetime(row[2]),
                    minutes=row[3],
                )
                for row in cursor
            ]
        finally:
            connection.close()

    def clear(self) -> None:
        connection = self._db.create_connection()
        try:
            connection.execute("DELETE FROM GameStats")
        finally:
            connection.close()
