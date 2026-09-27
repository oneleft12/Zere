"""Порт JARVIS.Core/AI/ContextBuilder.cs."""

from __future__ import annotations

from jarvis.memory.database.conversation_repository import ConversationRepository
from jarvis.memory.database.memory_repository import MemoryRepository


class ContextBuilder:
    def __init__(self, memory: MemoryRepository, history: ConversationRepository) -> None:
        self._memory = memory
        self._history = history

    def build_memory(self) -> str:
        memories = self._memory.get_all()

        if len(memories) == 0:
            return ""

        lines: list[str] = []

        for item in memories:
            lines.append(f"{item.key}: {item.value}\n")

        return "".join(lines)

    def build_history(self, count: int = 5) -> str:
        history = self._history.get_last(count)

        if len(history) == 0:
            return ""

        # get_last отдаёт новые первыми (ORDER BY Id DESC) — для контекста
        # диалог должен читаться от старых сообщений к новым.
        history.reverse()

        lines: list[str] = []

        for item in history:
            lines.append(f"Пользователь: {item.user_message}\n")
            lines.append(f"Ассистент: {item.jarvis_response}\n")
            lines.append("\n")

        return "".join(lines)
