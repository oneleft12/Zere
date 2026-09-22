"""Порт JARVIS.Core/Handlers/MemoryExtractor.cs."""

from __future__ import annotations

import re

from jarvis.memory.database.memory_repository import MemoryRepository


class MemoryExtractor:
    def __init__(self, memory: MemoryRepository) -> None:
        self._memory = memory

    def try_extract(self, message: str) -> bool:
        text = message.strip()

        name = re.match(r"^меня зовут\s+(.+)$", text, re.IGNORECASE)

        if name:
            self._memory.remember("имя", name.group(1).strip())
            return True

        project = re.match(r"^мой проект( называется)?\s+(.+)$", text, re.IGNORECASE)

        if project:
            self._memory.remember("проект", project.group(2).strip())
            return True

        gpu = re.match(
            r"^(у меня|я использую).*(rtx|gtx|rx)\s*([0-9a-z ]+)",
            text,
            re.IGNORECASE,
        )

        if gpu:
            self._memory.remember("видеокарта", gpu.group(0).strip())
            return True

        windows = re.match(r"^windows\s*(10|11)", text, re.IGNORECASE)

        if windows:
            self._memory.remember("windows", f"Windows {windows.group(1)}")
            return True

        return False
