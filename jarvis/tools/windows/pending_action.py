"""Ожидающее действие подтверждения (порт Windows/PendingAction.cs)."""

from __future__ import annotations

from enum import Enum


class PendingAction(Enum):
    NONE = 0
    SHUTDOWN = 1
    RESTART = 2
    SLEEP = 3

    # Алиасы 1:1 с именами C#-членов (None в Python — зарезервировано).
    None_ = NONE
    Shutdown = SHUTDOWN
    Restart = RESTART
    Sleep = SLEEP
