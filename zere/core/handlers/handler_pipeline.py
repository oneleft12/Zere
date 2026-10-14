"""Порт ZERE.Core/Handlers/HandlerPipeline.cs."""

from __future__ import annotations

from typing import Iterable, List, Optional

from zere.core.handlers.i_zere_handler import IZereHandler
from zere.core.logging.log_service import log_error


class HandlerPipeline:
    def __init__(self, handlers: Iterable[IZereHandler]) -> None:
        self._handlers: List[IZereHandler] = list(handlers)

    @property
    def handlers(self) -> List[IZereHandler]:
        """Копия списка обработчиков (для панели и тестов)."""
        return list(self._handlers)

    def contains(self, handler_type: type) -> bool:
        """Есть ли в конвейере обработчик указанного типа."""
        return any(isinstance(handler, handler_type) for handler in self._handlers)

    def handle(self, message: str) -> Optional[str]:
        for handler in self._handlers:
            try:
                if handler.can_handle(message):
                    result = handler.handle(message)

                    # None = обработчик не смог ответить → следующий обработчик
                    # (например, память не знает ответа → вопрос уходит в LLM).
                    if result is not None:
                        return result
            except Exception as ex:
                # Ошибка обработчика не должна ронять конвейер:
                # логируем в errors.log и пробуем следующий обработчик.
                log_error(type(handler).__name__, str(ex))
                print(
                    f"[Pipeline] Ошибка в обработчике "
                    f"{type(handler).__name__}: {ex}"
                )

        return None
