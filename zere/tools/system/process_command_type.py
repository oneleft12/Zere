"""Типы команд процессов ядра (порт System/ProcessCommandType.cs)."""

from __future__ import annotations

from enum import Enum


class ProcessCommandType(Enum):
    NONE = 0
    LIST_PROCESSES = 1
    FIND_PROCESS = 2
    KILL_PROCESS = 3
    KILL_LAST_PROCESS = 4

    # Алиасы 1:1 с именами C#-членов (None в Python — зарезервировано).
    ListProcesses = LIST_PROCESSES
    FindProcess = FIND_PROCESS
    KillProcess = KILL_PROCESS
    KillLastProcess = KILL_LAST_PROCESS
