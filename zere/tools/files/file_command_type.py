"""Типы файловых команд (порт FileCommandType.cs)."""

from __future__ import annotations

from enum import Enum


class FileCommandType(Enum):
    NONE = 0
    CREATE_FOLDER = 1
    CREATE_FILE = 2
    FIND_FILE = 3
    DELETE_FILE = 4
    DELETE_LAST_FILE = 5
    FIND_FOLDER = 6
    OPEN_FOLDER = 7

    # Алиасы 1:1 с именами C#-членов (None в Python — зарезервировано).
    CreateFolder = CREATE_FOLDER
    CreateFile = CREATE_FILE
    FindFile = FIND_FILE
    DeleteFile = DELETE_FILE
    DeleteLastFile = DELETE_LAST_FILE
    FindFolder = FIND_FOLDER
    OpenFolder = OPEN_FOLDER
