"""Порт ZERE.Core/Context/ContextType.cs."""

from __future__ import annotations

import enum


class ContextType(enum.Enum):
    None_ = 0
    File = 1
    Folder = 2
    Application = 3
    Memory = 4
    Conversation = 5
