"""Порт JARVIS.Core/Handlers/MemoryHandler.cs."""

from __future__ import annotations

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.memory.database.memory_repository import MemoryRepository


class MemoryHandler(IJarvisHandler):
    def __init__(self, memory: MemoryRepository) -> None:
        self._memory = memory

    def can_handle(self, message: str) -> bool:
        lower = message.lower().strip()

        return (
            lower.startswith("запомни")
            or lower.startswith("сохрани")
            or lower.startswith("не забудь")
            or lower.startswith("запиши")
            or lower.startswith("remember")
            or lower.startswith("обнови память")
            or lower.startswith("измени память")
            or lower.startswith("забудь")
            or lower.startswith("забыть")
            or lower.startswith("очисти запись")
            or lower.startswith("удали из памяти")
            or lower == "покажи память"
            or lower == "что ты помнишь"
            or lower == "что помнишь"
            or lower == "воспоминания"
            or lower == "все воспоминания"
            or lower == "память"
            or lower == "очисти память"
            or lower == "очистить память"
            or lower == "сбрось память"
            or lower == "reset memory"
        )

    def handle(self, message: str) -> str:
        lower = message.lower().strip()

        # === Показать память ===
        if (
            lower == "покажи память"
            or lower == "что ты помнишь"
            or lower == "что помнишь"
            or lower == "воспоминания"
            or lower == "все воспоминания"
            or lower == "память"
        ):
            memories = self._memory.get_all()

            if len(memories) == 0:
                return "Я пока ничего не запомнил."

            return "Вот что я помню:\n\n" + "\n".join(
                [f"• {m.key} = {m.value}" for m in memories]
            )

        # === Очистить память ===
        if (
            lower == "очисти память"
            or lower == "очистить память"
            or lower == "сбрось память"
            or lower == "reset memory"
        ):
            self._memory.clear()
            return "Память полностью очищена."

        # === Забыть конкретное ===
        if lower.startswith("забудь ") or lower.startswith("забыть "):
            if "забудь " in lower:
                key = lower[len("забудь ") :].strip()
            else:
                key = lower[len("забыть ") :].strip()

            deleted = self._memory.forget(key)

            return f"Я забыл информацию: {key}." if deleted else f"Я не нашёл запись «{key}»."

        if lower.startswith("очисти запись "):
            key = lower[len("очисти запись ") :].strip()
            deleted = self._memory.forget(key)
            return f"Запись «{key}» удалена из памяти." if deleted else f"Запись «{key}» не найдена."

        if lower.startswith("удали из памяти "):
            key = lower[len("удали из памяти ") :].strip()
            deleted = self._memory.forget(key)
            return f"Удалил из памяти: {key}." if deleted else f"Не нашёл в памяти: «{key}»."

        if lower.startswith("забудь") or lower.startswith("забыть"):
            return "Укажите, что забыть. Например: забудь имя"

        # === Обновить память ===
        if lower.startswith("обнови память ") or lower.startswith("измени память "):
            prefix = "обнови память " if lower.startswith("обнови память ") else "измени память "
            text = message[len(prefix) :].strip()

            if "=" not in text:
                return "Например: обнови память проект = AI VOCALPLUS"

            parts = text.split("=", 1)

            key = parts[0].strip().lower()
            value = parts[1].strip()

            self._memory.remember(key, value)

            return f"Память обновлена: {key} = {value}"

        # === Запомнить ===
        text_to_remember = ""

        if lower.startswith("запомни"):
            text_to_remember = message[len("запомни") :].strip()
        elif lower.startswith("сохрани"):
            text_to_remember = message[len("сохрани") :].strip()
        elif lower.startswith("не забудь"):
            text_to_remember = message[len("не забудь") :].strip()
        elif lower.startswith("запиши"):
            text_to_remember = message[len("запиши") :].strip()
        elif lower.startswith("remember"):
            text_to_remember = message[len("remember") :].strip()

        if text_to_remember is None or text_to_remember.strip() == "":
            return "Укажите, что запомнить. Например: запомни имя Dan"

        for prefix in ["мое ", "мой ", "моя ", "что "]:
            if text_to_remember.lower().startswith(prefix):  # OrdinalIgnoreCase
                text_to_remember = text_to_remember[len(prefix) :].strip()
                break

        memory_key: str
        memory_value: str

        if "=" in text_to_remember:
            parts = text_to_remember.split("=", 1)

            memory_key = parts[0].strip().lower()
            memory_value = parts[1].strip()
        else:
            words = [w for w in text_to_remember.split(" ") if w != ""]

            if len(words) < 2:
                return "Например: запомни имя Dan"

            memory_key = words[0].strip().lower()
            memory_value = " ".join(words[1:])

        self._memory.remember(memory_key, memory_value)

        return f"Запомнил: {memory_key} = {memory_value}"
