"""Порт JARVIS.Memory/Models/MemoryItem.cs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MemoryItem:
    """Свойства C# переведены в атрибуты dataclass (snake_case)."""

    id: int = 0  # C#: long Id
    key: str = ""  # C#: string Key
    value: str = ""  # C#: string Value
    category: str = ""  # C#: string Category
    created_at: datetime = datetime.min  # C#: DateTime CreatedAt (default(DateTime))
