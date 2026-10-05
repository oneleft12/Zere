"""Порт ZERE.Core/Context/ContextService.cs."""

from __future__ import annotations

from zere.core.context.context_memory import ContextMemory


class ContextService:
    def __init__(self) -> None:
        self._memory = ContextMemory()

    @property
    def current(self) -> ContextMemory:
        return self._memory
