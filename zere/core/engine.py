"""Порт ZERE.Core/ZereEngine.cs."""

from __future__ import annotations

from zere.core.handlers.handler_pipeline import HandlerPipeline
from zere.core.handlers.memory_extractor import MemoryExtractor
from zere.core.logging.log_service import log_error
from zere.core.plugins.plugin_manager import PluginManager
from zere.memory.database.conversation_repository import ConversationRepository


class ZereEngine:
    def __init__(
        self,
        pipeline: HandlerPipeline,
        extractor: MemoryExtractor,
        plugin_manager: PluginManager,
        conversations: ConversationRepository,
    ) -> None:
        self._pipeline = pipeline
        self._extractor = extractor
        self._plugin_manager = plugin_manager
        self._conversations = conversations

    @property
    def plugin_manager(self) -> PluginManager:
        return self._plugin_manager

    def process(self, message: str) -> str:
        try:
            self._extractor.try_extract(message)

            result = self._pipeline.handle(message)

            answer = result if result is not None else "Команда не распознана."

            self._save_history(message, answer)

            return answer
        except Exception as ex:
            # Ошибка не должна ронять приложение — логируем и отвечаем текстом
            log_error("ZereEngine", str(ex))
            print(f"[ZereEngine] Ошибка: {ex}")
            return f"Произошла ошибка: {ex}"

    def _save_history(self, message: str, answer: str) -> None:
        """Сохраняет пару (запрос, ответ) в историю. Best-effort."""
        try:
            self._conversations.save(message, answer)
        except Exception as ex:
            log_error("ZereEngine", f"не удалось сохранить историю: {ex}")
