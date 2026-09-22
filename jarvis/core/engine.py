"""Порт JARVIS.Core/JarvisEngine.cs."""

from __future__ import annotations

from jarvis.core.handlers.handler_pipeline import HandlerPipeline
from jarvis.core.handlers.memory_extractor import MemoryExtractor
from jarvis.core.logging.log_service import log_error
from jarvis.core.plugins.plugin_manager import PluginManager


class JarvisEngine:
    def __init__(
        self,
        pipeline: HandlerPipeline,
        extractor: MemoryExtractor,
        plugin_manager: PluginManager,
    ) -> None:
        self._pipeline = pipeline
        self._extractor = extractor
        self._plugin_manager = plugin_manager

    @property
    def plugin_manager(self) -> PluginManager:
        return self._plugin_manager

    def process(self, message: str) -> str:
        try:
            self._extractor.try_extract(message)

            result = self._pipeline.handle(message)

            return result if result is not None else "Команда не распознана."
        except Exception as ex:
            # Ошибка не должна ронять приложение — логируем и отвечаем текстом
            log_error("JarvisEngine", str(ex))
            print(f"[JarvisEngine] Ошибка: {ex}")
            return f"Произошла ошибка: {ex}"
