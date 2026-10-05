"""Порт ZERE.Core/AI/ContextBuilder.cs."""

from __future__ import annotations

from zere.memory.database.conversation_repository import ConversationRepository
from zere.memory.database.memory_repository import MemoryRepository


class ContextBuilder:
    # Анализ S5 (этап 1): память без лимита уплывала в промпт целиком —
    # промпт рос, инференс замедлялся, контекст (num_ctx) переполнялся.
    _MAX_MEMORY_ITEMS = 30
    _MAX_MEMORY_CHARS = 1500

    def __init__(self, memory: MemoryRepository, history: ConversationRepository) -> None:
        self._memory = memory
        self._history = history

    def build_memory(self) -> str:
        memories = self._memory.get_all()

        if len(memories) == 0:
            return ""

        lines: list[str] = []
        used = 0
        truncated = False

        for item in memories:
            if len(lines) >= self._MAX_MEMORY_ITEMS:
                truncated = True
                break

            line = f"{item.key}: {item.value}\n"

            if used + len(line) > self._MAX_MEMORY_CHARS:
                truncated = True
                break

            lines.append(line)
            used += len(line)

        if truncated:
            lines.append("… (часть воспоминаний опущена — лимит контекста)\n")

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
            lines.append(f"Ассистент: {item.zere_response}\n")
            lines.append("\n")

        return "".join(lines)
