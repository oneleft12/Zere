"""Порт ZERE.Memory/Models/Conversation.cs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Conversation:
    """Свойства C# переведены в атрибуты dataclass (snake_case)."""

    id: int = 0  # C#: long Id
    user_message: str = ""  # C#: string UserMessage
    zere_response: str = ""  # C#: string ZereResponse
    timestamp: datetime = datetime.min  # C#: DateTime Timestamp (default(DateTime))
