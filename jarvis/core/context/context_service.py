"""Порт JARVIS.Core/Context/ContextService.cs."""

from __future__ import annotations

from jarvis.core.context.context_memory import ContextMemory


class ContextService:
    def __init__(self) -> None:
        self._memory = ContextMemory()

    @property
    def current(self) -> ContextMemory:
        return self._memory
