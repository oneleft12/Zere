"""Порт JARVIS.Memory/Gaming/GameStat.cs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class GameStat:
    """Свойства C# переведены в атрибуты dataclass (snake_case)."""

    id: int = 0  # C#: long Id
    game: str = ""  # C#: string Game
    date: datetime = datetime.min  # C#: DateTime Date (default(DateTime))
    minutes: int = 0  # C#: int Minutes
