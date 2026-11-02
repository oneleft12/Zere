"""Порт ZERE.Core/Handlers/FileHandler.cs."""

from __future__ import annotations

from zere.core.handlers.i_zere_handler import IZereHandler
from zere.tools.files.file_command_router import FileCommandRouter
from zere.tools.files.file_command_type import FileCommandType
from zere.tools.files.file_manager import FileManager
from zere.tools.windows.pending_action import PendingAction
from zere.tools.windows.safe_action_manager import SafeActionManager


class FileHandler(IZereHandler):
    def __init__(self, files: FileManager, safe_actions: SafeActionManager) -> None:
        self._files = files
        self._router = FileCommandRouter()
        self._safe_actions = safe_actions

    def can_handle(self, message: str) -> bool:
        lower = message.lower()

        return (
            lower.startswith("создай папку")
            or lower.startswith("создай директорию")
            or lower.startswith("новая папка")
            or lower.startswith("замокай папку")
            or lower.startswith("папка ")
            or lower.startswith("создай файл")
            or lower.startswith("новый файл")
            or lower.startswith("создай документ")
            or lower.startswith("замокай файл")
            or lower.startswith("документ ")
            or lower.startswith("найди файл")
            or lower.startswith("найти файл")
            or lower.startswith("поищи файл")
            or lower.startswith("где файл")
            or lower.startswith("розыск файла")
            or lower.startswith("найди папку")
            or lower.startswith("найти папку")
            or lower.startswith("поищи папку")
            or lower.startswith("где папка")
            or lower.startswith("розыск папки")
            or lower.startswith("поиск папки")
            or lower.startswith("открой папку")
            or lower.startswith("открыть папку")
            or lower.startswith("открой каталог")
            or lower.startswith("открыть каталог")
            or lower.startswith("открой директорию")
            or lower.startswith("открыть директорию")
            or lower.startswith("покажи папку")
            or lower.startswith("открой путь")
            or lower in ("открой её", "открой ее")
            or lower.startswith("удали файл")
            or lower.startswith("убери файл")
            or lower.startswith("удалить файл")
            or lower.startswith("стереть ")
            or lower.startswith("удали ")
            or lower.startswith("удали его")
            or lower.startswith("удалить его")
        )

    def handle(self, message: str) -> str:
        command = self._router.parse(message)

        if command.type == FileCommandType.CreateFolder:
            return self._files.create_folder(command.value)

        if command.type == FileCommandType.CreateFile:
            return self._files.create_file(command.value)

        if command.type == FileCommandType.FindFile:
            return self._files.find_file(command.value)

        if command.type == FileCommandType.FindFolder:
            return self._files.find_folders(command.value)

        if command.type == FileCommandType.OpenFolder:
            return self._files.open_folder(command.value)

        if command.type == FileCommandType.DELETE_LAST_FILE:
            last_name = self._files.last_created_name

            if last_name is None:
                return "Я не создавал файлов в этой сессии — нечего удалять."

            if not self._files.exists(last_name):
                return f"Файл «{last_name}» уже не существует."

            self._safe_actions.request(PendingAction.DELETE_FILE, last_name)

            ttl = SafeActionManager.CONFIRM_TTL_SECONDS
            return (
                f"Удалить последний созданный файл «{last_name}»? "
                f"Напишите «да» или «нет» (подтверждение действует {ttl} секунд)."
            )

        if command.type == FileCommandType.DELETE_FILE:
            # Удаление необратимо: подтверждение с TTL вместо мгновенного
            # удаления (раньше здесь был Request(PendingAction.None) — no-op).
            if not self._files.exists(command.value):
                return f'Файл "{command.value}" не найден.'

            self._safe_actions.request(PendingAction.DELETE_FILE, command.value)

            ttl = SafeActionManager.CONFIRM_TTL_SECONDS
            return (
                f"Удалить файл «{command.value}» с рабочего стола? "
                f"Напишите «да» или «нет» (подтверждение действует {ttl} секунд)."
            )

        return "Команда файлов не распознана."
