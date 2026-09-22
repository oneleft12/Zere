"""Порт JARVIS.Core/Context/ContextItem.cs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from jarvis.core.context.context_type import ContextType


@dataclass
class ContextItem:
    type: ContextType = ContextType.None_
    name: str = ""
    value: str = ""
    time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # DateTime.UtcNow
