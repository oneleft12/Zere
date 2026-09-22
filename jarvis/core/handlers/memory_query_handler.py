"""Порт JARVIS.Core/Handlers/MemoryQueryHandler.cs."""

from __future__ import annotations

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.memory.database.memory_repository import MemoryRepository


class MemoryQueryHandler(IJarvisHandler):
    def __init__(self, memory: MemoryRepository) -> None:
        self._memory = memory

    def can_handle(self, message: str) -> bool:
        lower = message.lower().strip()

        return (
            "как меня зовут" in lower
            or "какой у меня проект" in lower
            or "что ты знаешь обо мне" in lower
            or "какая у меня видеокарта" in lower
            or "какая у меня windows" in lower
            or lower.startswith("что такое ")
            or lower.startswith("кто такой ")
            or lower.startswith("кто такая ")
        )

    def handle(self, message: str) -> str:
        lower = message.lower().strip()

        if "что ты знаешь обо мне" in lower:
            all_memories = self._memory.get_all()

            if len(all_memories) == 0:
                return "Я пока ничего не запомнил."

            return "Вот что я помню:\n\n" + "\n".join(
                [f"• {x.key} = {x.value}" for x in all_memories]
            )

        if "зовут" in lower:
            key = "имя"
        elif "проект" in lower:
            key = "проект"
        elif "видеокарта" in lower:
            key = "видеокарта"
        elif "windows" in lower:
            key = "windows"
        else:
            key = ""

        if key != "":
            memory = self._memory.get(key)

            if memory is not None:
                if key == "имя":
                    return f"Вас зовут {memory.value}."
                if key == "проект":
                    return f"Ваш проект называется {memory.value}."
                if key == "видеокарта":
                    return f"У вас видеокарта {memory.value}."
                if key == "windows":
                    return f"Вы используете {memory.value}."
                return memory.value

        search_query = self._extract_search_query(lower)

        if search_query != "":
            results = self._memory.search(search_query)

            if len(results) > 0:
                best = results[0]
                return f"Из памяти: {best.key} = {best.value}"

        return "Я пока не знаю ответ."

    @staticmethod
    def _extract_search_query(lower: str) -> str:
        prefixes = [
            "что такое ",
            "кто такой ",
            "кто такая ",
            "что значит ",
            "расскажи про ",
            "расскажи о ",
        ]

        for prefix in prefixes:
            if prefix in lower:
                idx = lower.find(prefix)
                return lower[idx + len(prefix) :].strip()

        return ""
