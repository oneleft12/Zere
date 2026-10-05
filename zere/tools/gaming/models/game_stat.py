"""Статистика по игре (порт Gaming/Models/GameStat.cs)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class GameStat:
    game_name: str = ""
    today_time: timedelta = timedelta(0)
    last_played: datetime = datetime.min  # default(DateTime)
    is_running: bool = False
