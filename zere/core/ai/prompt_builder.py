"""Порт ZERE.Core/AI/PromptBuilder.cs."""

from __future__ import annotations

from typing import List


class PromptBuilder:
    def __init__(self) -> None:
        self._builder: List[str] = []

    def system_prompt(self, system_prompt: str) -> "PromptBuilder":
        self._builder.append(system_prompt + "\n")
        self._builder.append("\n")

        return self

    def memory(self, memory: str) -> "PromptBuilder":
        if memory is not None and memory.strip() != "":
            self._builder.append("=== ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ ===\n")
            self._builder.append(memory + "\n")
            self._builder.append("\n")

        return self

    def history(self, history: str) -> "PromptBuilder":
        if history is not None and history.strip() != "":
            self._builder.append("=== ПОСЛЕДНИЙ ДИАЛОГ ===\n")
            self._builder.append(history + "\n")
            self._builder.append("\n")

        return self

    def user_message(self, message: str) -> "PromptBuilder":
        self._builder.append("=== СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ ===\n")
        self._builder.append(message + "\n")
        self._builder.append("\n")
        self._builder.append("=== ОТВЕТ АССИСТЕНТА ===\n")

        return self

    def build(self) -> str:
        return "".join(self._builder)

    def reset(self) -> None:
        self._builder.clear()
