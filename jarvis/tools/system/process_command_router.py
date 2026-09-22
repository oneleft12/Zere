"""Парсер команд процессов ядра (порт System/ProcessCommandRouter.cs)."""

from __future__ import annotations

from typing import NamedTuple

from jarvis.tools.system.process_command_type import ProcessCommandType


class ParsedProcessCommand(NamedTuple):
    """C#-кортеж (ProcessCommandType Type, string Value)."""

    type: ProcessCommandType
    value: str


class ProcessCommandRouter:
    def parse(self, message: str) -> ParsedProcessCommand:
        text = message.strip()
        lower = text.lower()

        if lower == "что сейчас запущено":
            return ParsedProcessCommand(ProcessCommandType.LIST_PROCESSES, "")

        prefix = "найди процесс "
        if lower.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.FIND_PROCESS, text[len(prefix):].strip())

        prefix = "закрой "
        if lower.startswith(prefix):
            value = text[len(prefix):].strip()

            if value.lower() == "его":
                return ParsedProcessCommand(ProcessCommandType.KILL_LAST_PROCESS, "")

            return ParsedProcessCommand(ProcessCommandType.KILL_PROCESS, value)

        return ParsedProcessCommand(ProcessCommandType.NONE, "")
