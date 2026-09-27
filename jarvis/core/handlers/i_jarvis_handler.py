"""Порт JARVIS.Core/Handlers/IJarvisHandler.cs."""

from __future__ import annotations

import abc
from typing import Optional


class IJarvisHandler(abc.ABC):
    @abc.abstractmethod
    def can_handle(self, message: str) -> bool:
        ...

    @abc.abstractmethod
    def handle(self, message: str) -> Optional[str]:
        """Обработать сообщение.

        None = обработчик не смог ответить — конвейер передаёт сообщение
        следующему обработчику.
        """
        ...
