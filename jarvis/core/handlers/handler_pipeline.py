"""Порт JARVIS.Core/Handlers/HandlerPipeline.cs."""

from __future__ import annotations

from typing import Iterable, List, Optional

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler


class HandlerPipeline:
    def __init__(self, handlers: Iterable[IJarvisHandler]) -> None:
        self._handlers: List[IJarvisHandler] = list(handlers)

    def handle(self, message: str) -> Optional[str]:
        for handler in self._handlers:
            try:
                if handler.can_handle(message):
                    return handler.handle(message)
            except Exception as ex:
                print(
                    f"[Pipeline] Ошибка в обработчике "
                    f"{type(handler).__name__}: {ex}"
                )

        return None
