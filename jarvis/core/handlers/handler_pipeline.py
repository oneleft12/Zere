"""Порт JARVIS.Core/Handlers/HandlerPipeline.cs."""

from __future__ import annotations

from typing import Iterable, List, Optional

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.core.logging.log_service import log_error


class HandlerPipeline:
    def __init__(self, handlers: Iterable[IJarvisHandler]) -> None:
        self._handlers: List[IJarvisHandler] = list(handlers)

    def handle(self, message: str) -> Optional[str]:
        for handler in self._handlers:
            try:
                if handler.can_handle(message):
                    return handler.handle(message)
            except Exception as ex:
                # Ошибка обработчика не должна ронять конвейер:
                # логируем в errors.log и пробуем следующий обработчик.
                log_error(type(handler).__name__, str(ex))
                print(
                    f"[Pipeline] Ошибка в обработчике "
                    f"{type(handler).__name__}: {ex}"
                )

        return None
