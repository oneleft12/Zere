"""Ожидающее действие подтверждения (порт Windows/PendingAction.cs)."""

from __future__ import annotations

from enum import Enum


class PendingAction(Enum):
    NONE = 0
    SHUTDOWN = 1
    RESTART = 2
    SLEEP = 3
    # Target: имя процесса
    KILL_PROCESS = 4
    # Target: имя файла на рабочем столе
    DELETE_FILE = 5

    # Алиасы 1:1 с именами C#-членов (None в Python — зарезервировано).
    None_ = NONE
    Shutdown = SHUTDOWN
    Restart = RESTART
    Sleep = SLEEP
    KillProcess = KILL_PROCESS
    DeleteFile = DELETE_FILE
