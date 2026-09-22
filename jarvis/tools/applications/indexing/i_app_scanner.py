"""Интерфейс сканера приложений (порт IAppScanner.cs)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.tools.applications.indexing.app_info import AppInfo


class IAppScanner(ABC):
    """Сканер установленных приложений."""

    @abstractmethod
    def scan(self) -> list[AppInfo]:
        """Сканирует источник и возвращает найденные приложения."""
        ...
