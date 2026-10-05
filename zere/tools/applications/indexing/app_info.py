"""Информация о приложении (порт AppInfo.cs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AppInfo:
    """DTO приложения, как в ZERE.Tools.Applications.Indexing.AppInfo."""

    name: str = ""
    executable_path: str = ""
    source: str = ""
    category: str = "Application"
    priority: int = 50
    aliases: list[str] = field(default_factory=list)
    last_seen: datetime = field(default_factory=datetime.now)
