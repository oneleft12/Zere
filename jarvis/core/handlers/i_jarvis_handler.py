"""Порт JARVIS.Core/Handlers/IJarvisHandler.cs."""

from __future__ import annotations

import abc


class IJarvisHandler(abc.ABC):
    @abc.abstractmethod
    def can_handle(self, message: str) -> bool:
        ...

    @abc.abstractmethod
    def handle(self, message: str) -> str:
        ...
