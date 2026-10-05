"""Интерфейс сканера приложений (порт IAppScanner.cs)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from zere.tools.applications.indexing.app_info import AppInfo


class IAppScanner(ABC):
    """Сканер установленных приложений."""

    @abstractmethod
    def scan(self) -> list[AppInfo]:
        """Сканирует источник и возвращает найденные приложения."""
        ...
