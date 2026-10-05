"""Парсер команд процессов Windows (порт Windows/ProcessCommandRouter.cs)."""

from __future__ import annotations

from typing import NamedTuple

from zere.tools.windows.process_command_type import ProcessCommandType


class ParsedProcessCommand(NamedTuple):
    """C#-кортеж (ProcessCommandType Type, string Value)."""

    type: ProcessCommandType
    value: str


class ProcessCommandRouter:
    def parse(self, message: str) -> ParsedProcessCommand:
        text = message.strip().lower()

        # === Список процессов ===
        if (
            text == "процессы"
            or text == "список процессов"
            or text == "процессы системы"
            or text == "что запущено"
            or text == "задачи"
            or text == "список задач"
            or text == "task list"
            or text == "tasks"
        ):
            return ParsedProcessCommand(ProcessCommandType.LIST, "")

        # === Поиск процесса ===
        # Проверка по text (trim+lower), но срез — по исходному message,
        # ровно как в C#: message["...".Length..].Trim()
        prefix = "найди процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.SEARCH, message[len(prefix):].strip())

        prefix = "найти процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.SEARCH, message[len(prefix):].strip())

        prefix = "поищи процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.SEARCH, message[len(prefix):].strip())

        prefix = "есть ли процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.SEARCH, message[len(prefix):].strip())

        prefix = "процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.SEARCH, message[len(prefix):].strip())

        # === Закрытие процесса ===
        prefix = "закрой процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.KILL, message[len(prefix):].strip())

        prefix = "убей процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.KILL, message[len(prefix):].strip())

        prefix = "заверши процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.KILL, message[len(prefix):].strip())

        prefix = "останови процесс "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.KILL, message[len(prefix):].strip())

        prefix = "kill "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.KILL, message[len(prefix):].strip())

        prefix = "закрой "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.KILL, message[len(prefix):].strip())

        prefix = "убей "
        if text.startswith(prefix):
            return ParsedProcessCommand(
                ProcessCommandType.KILL, message[len(prefix):].strip())

        return ParsedProcessCommand(ProcessCommandType.NONE, "")
