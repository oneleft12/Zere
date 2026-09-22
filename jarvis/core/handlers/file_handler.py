"""Порт JARVIS.Core/Handlers/FileHandler.cs."""

from __future__ import annotations

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.tools.files.file_command_router import FileCommandRouter
from jarvis.tools.files.file_command_type import FileCommandType
from jarvis.tools.files.file_manager import FileManager
from jarvis.tools.windows.pending_action import PendingAction
from jarvis.tools.windows.safe_action_manager import SafeActionManager


class FileHandler(IJarvisHandler):
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

        if command.type == FileCommandType.DeleteFile:
            # PendingAction.None — чистит ожидающую команду (в исходнике: Request(PendingAction.None))
            self._safe_actions.request(PendingAction.None_)

            return (
                f'Файл "{command.value}" удалён.'
                if self._files.delete_file(command.value)
                else f'Файл "{command.value}" не найден.'
            )

        return "Команда файлов не распознана."
