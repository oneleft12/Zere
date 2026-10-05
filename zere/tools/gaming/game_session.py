"""Сессия игры (порт GameSession.cs)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class GameSession:
    game_name: str = ""
    start_time: datetime = datetime.min  # default(DateTime)
    is_active: bool = False

    @property
    def duration(self) -> timedelta:
        """Текущая длительность сессии (TimeSpan.Zero, если не активна)."""
        return datetime.now() - self.start_time if self.is_active else timedelta(0)
