"""Парсер файловых команд (порт FileCommandRouter.cs)."""

from __future__ import annotations

from typing import NamedTuple

from zere.tools.files.file_command_type import FileCommandType


class ParsedFileCommand(NamedTuple):
    """C#-кортеж (FileCommandType Type, string Value)."""

    type: FileCommandType
    value: str


class FileCommandRouter:
    def parse(self, message: str) -> ParsedFileCommand:
        text = message.strip()
        lower = text.lower()

        # === Удаление последнего файла ===
        if lower == "удали его" or lower == "удалить его":
            return ParsedFileCommand(FileCommandType.DELETE_LAST_FILE, "")

        # === Открытие папки на экране ===
        for prefix in (
            "открой папку ",
            "открыть папку ",
            "открой каталог ",
            "открыть каталог ",
            "открой директорию ",
            "открыть директорию ",
            "покажи папку ",
            "открой путь ",
        ):
            if lower.startswith(prefix):
                return ParsedFileCommand(
                    FileCommandType.OPEN_FOLDER, text[len(prefix):].strip())

        for phrase in (
            "открой папку",
            "открыть папку",
            "открой каталог",
            "открыть каталог",
            "открой директорию",
            "открыть директорию",
            "покажи папку",
            "открой путь",
            "открой её",
            "открой ее",
        ):
            if lower == phrase:
                return ParsedFileCommand(FileCommandType.OPEN_FOLDER, "")

        # === Поиск папки ===
        for prefix in (
            "найди папку ",
            "найти папку ",
            "поищи папку ",
            "где папка ",
            "розыск папки ",
            "поиск папки ",
        ):
            if lower.startswith(prefix):
                return ParsedFileCommand(
                    FileCommandType.FIND_FOLDER, text[len(prefix):].strip())

        if lower in (
            "найди папку",
            "найти папку",
            "поищи папку",
            "где папка",
            "розыск папки",
            "поиск папки",
        ):
            return ParsedFileCommand(FileCommandType.FIND_FOLDER, "")

        # === Создание папки ===
        prefix = "создай папку "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FOLDER, text[len(prefix):].strip())

        prefix = "создай директорию "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FOLDER, text[len(prefix):].strip())

        prefix = "новая папка "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FOLDER, text[len(prefix):].strip())

        prefix = "замокай папку "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FOLDER, text[len(prefix):].strip())

        prefix = "папка "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FOLDER, text[len(prefix):].strip())

        # === Создание файла ===
        prefix = "создай файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FILE, text[len(prefix):].strip())

        prefix = "новый файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FILE, text[len(prefix):].strip())

        prefix = "создай документ "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FILE, text[len(prefix):].strip())

        prefix = "замокай файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FILE, text[len(prefix):].strip())

        prefix = "документ "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.CREATE_FILE, text[len(prefix):].strip())

        # === Поиск файла ===
        prefix = "найди файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.FIND_FILE, text[len(prefix):].strip())

        prefix = "найти файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.FIND_FILE, text[len(prefix):].strip())

        prefix = "поищи файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.FIND_FILE, text[len(prefix):].strip())

        prefix = "где файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.FIND_FILE, text[len(prefix):].strip())

        prefix = "розыск файла "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.FIND_FILE, text[len(prefix):].strip())

        # === Удаление файла ===
        prefix = "удали файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.DELETE_FILE, text[len(prefix):].strip())

        prefix = "удали "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.DELETE_FILE, text[len(prefix):].strip())

        prefix = "убери файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.DELETE_FILE, text[len(prefix):].strip())

        prefix = "удалить файл "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.DELETE_FILE, text[len(prefix):].strip())

        prefix = "стереть "
        if lower.startswith(prefix):
            return ParsedFileCommand(
                FileCommandType.DELETE_FILE, text[len(prefix):].strip())

        return ParsedFileCommand(FileCommandType.NONE, "")
