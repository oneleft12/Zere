"""Порт ZERE.Core/AI/PromptBuilder.cs."""

from __future__ import annotations

from typing import Dict, List

#: Заголовки блоков промпта. Английские — для language=en: модель получает
#: системное правило «answer only in English», и русские заголовки в самом
#: промпте тянули ответ обратно в русский.
_LABELS: Dict[str, tuple[str, str, str, str]] = {
    "ru": (
        "=== ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ ===\n",
        "=== ПОСЛЕДНИЙ ДИАЛОГ ===\n",
        "=== СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ ===\n",
        "=== ОТВЕТ АССИСТЕНТА ===\n",
    ),
    "en": (
        "=== USER MEMORY ===\n",
        "=== LAST DIALOG ===\n",
        "=== USER MESSAGE ===\n",
        "=== ASSISTANT ANSWER ===\n",
    ),
}


class PromptBuilder:
    def __init__(self, language: str = "ru") -> None:
        self._builder: List[str] = []
        self._labels = _LABELS.get(language, _LABELS["ru"])

    def system_prompt(self, system_prompt: str) -> "PromptBuilder":
        self._builder.append(system_prompt + "\n")
        self._builder.append("\n")

        return self

    def memory(self, memory: str) -> "PromptBuilder":
        if memory is not None and memory.strip() != "":
            self._builder.append(self._labels[0])
            self._builder.append(memory + "\n")
            self._builder.append("\n")

        return self

    def history(self, history: str) -> "PromptBuilder":
        if history is not None and history.strip() != "":
            self._builder.append(self._labels[1])
            self._builder.append(history + "\n")
            self._builder.append("\n")

        return self

    def user_message(self, message: str) -> "PromptBuilder":
        self._builder.append(self._labels[2])
        self._builder.append(message + "\n")
        self._builder.append("\n")
        self._builder.append(self._labels[3])

        return self

    def build(self) -> str:
        return "".join(self._builder)

    def reset(self) -> None:
        self._builder.clear()
