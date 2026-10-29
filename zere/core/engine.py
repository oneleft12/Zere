"""Порт ZERE.Core/ZereEngine.cs."""

from __future__ import annotations

import threading

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

        # Конвейер вызывается из трёх потоков: консоль, панель (поток на
        # запрос) и цикл голосового режима. Состояние обработчиков
        # (GameTracker, DrawingService, ожидающее подтверждение) не рассчитано
        # на одновременный вход, а «да», сказанное в другом окне, могло
        # выполнить чужую команду. Сериализуем реплику целиком.
        # RLock: подтверждённая команда роутера исполняется внутри обработки
        # и может снова позвать engine.process в том же потоке.
        self._process_lock = threading.RLock()

    @property
    def plugin_manager(self) -> PluginManager:
        return self._plugin_manager

    @property
    def pipeline(self) -> HandlerPipeline:
        """Конвейер обработчиков.

        Нужен панели: `GET /api/plugins` проверяет по нему, подключены ли
        плагины-обработчики (`handlersConnected`), вместо прежнего жёсткого
        `false`.
        """
        return self._pipeline

    def process(self, message: str) -> str:
        with self._process_lock:
            return self._process_unlocked(message)

    def _process_unlocked(self, message: str) -> str:
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
