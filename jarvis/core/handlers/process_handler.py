"""Порт JARVIS.Core/Handlers/ProcessHandler.cs."""

from __future__ import annotations

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.tools.windows.process_command_router import ProcessCommandRouter
from jarvis.tools.windows.process_command_type import ProcessCommandType
from jarvis.tools.windows.process_service import ProcessService


class ProcessHandler(IJarvisHandler):
    def __init__(self, service: ProcessService) -> None:
        self._service = service
        self._router = ProcessCommandRouter()

    def can_handle(self, message: str) -> bool:
        lower = message.lower().strip()

        return (
            lower == "процессы"
            or lower == "список процессов"
            or lower == "процессы системы"
            or lower == "что запущено"
            or lower == "задачи"
            or lower == "список задач"
            or lower == "task list"
            or lower == "tasks"
            or lower.startswith("найди процесс")
            or lower.startswith("найти процесс")
            or lower.startswith("поищи процесс")
            or lower.startswith("есть ли процесс")
            or lower.startswith("процесс ")
            or lower.startswith("закрой процесс")
            or lower.startswith("убей процесс")
            or lower.startswith("заверши процесс")
            or lower.startswith("останови процесс")
            or lower.startswith("kill ")
            or lower.startswith("закрой ")
            or lower.startswith("убей ")
        )

    def handle(self, message: str) -> str:
        command = self._router.parse(message)

        if command.type == ProcessCommandType.List:
            processes = self._service.get_processes()[:15]

            return "Самые тяжёлые процессы:\n\n" + "\n".join(
                [f"• {p.name} — {p.memory_mb} MB" for p in processes]
            )

        if command.type == ProcessCommandType.Search:
            found = self._service.search(command.value)

            if len(found) == 0:
                return "Процесс не найден."

            return "\n".join(
                [f"• {p.name} (PID {p.id}) — {p.memory_mb} MB" for p in found]
            )

        if command.type == ProcessCommandType.Kill:
            return f"Процесс {command.value} закрыт." if self._service.kill(command.value) else "Процесс не найден."

        return "Команда процессов не распознана."
