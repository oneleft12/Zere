"""Порт ZERE.Core/Context/RuntimeContext.cs.

Флаги рантайма, общие для консоли, панели и AI-хендлера.

voice_mode (анализ S5 / этап 1): когда ответ этой реплики будет озвучен
голосом, AIHandler добавляет в system-промпт требование короткого ответа
и ограничивает генерацию config.llm_max_tokens — голос не должен
проговаривать простыни.
"""

from __future__ import annotations


class RuntimeContext:
    """Аналог C# RuntimeContext — один инстанс на процесс (DI-синглтон)."""

    def __init__(self) -> None:
        self._voice_mode = False

    @property
    def voice_mode(self) -> bool:
        return self._voice_mode

    @voice_mode.setter
    def voice_mode(self, value: bool) -> None:
        self._voice_mode = bool(value)
