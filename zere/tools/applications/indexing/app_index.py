"""Метаданные индекса приложений (порт AppIndex.cs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from zere.tools.applications.indexing.app_info import AppInfo


@dataclass
class AppIndex:
    """Контейнер индекса приложений (schema version + список)."""

    schema_version: str = "1.2.1"
    created_at: datetime = field(default_factory=datetime.now)
    applications: list[AppInfo] = field(default_factory=list)
