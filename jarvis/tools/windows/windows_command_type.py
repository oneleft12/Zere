"""Типы команд питания Windows (порт Windows/WindowsCommandType.cs)."""

from __future__ import annotations

from enum import Enum


class WindowsCommandType(Enum):
    NONE = 0
    SHUTDOWN = 1
    RESTART = 2
    SLEEP = 3

    # Алиасы 1:1 с именами C#-членов (None в Python — зарезервировано).
    Shutdown = SHUTDOWN
    Restart = RESTART
    Sleep = SLEEP
