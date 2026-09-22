"""Типы команд процессов Windows (порт Windows/ProcessCommandRouter.cs, enum ProcessCommandType)."""

from __future__ import annotations

from enum import Enum


class ProcessCommandType(Enum):
    NONE = 0
    LIST = 1
    SEARCH = 2
    KILL = 3

    # Алиасы 1:1 с именами C#-членов (None в Python — зарезервировано).
    List = LIST
    Search = SEARCH
    Kill = KILL
