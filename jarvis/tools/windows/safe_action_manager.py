"""Подтверждение опасных действий (порт Windows/SafeActionManager.cs).

Ожидающее действие живёт ограниченное время (TTL) — «да», сказанное спустя
долгое время, ничего не выполнит.
"""

from __future__ import annotations

import subprocess
import threading
import time
from enum import Enum

from jarvis.tools.files.file_manager import FileManager
from jarvis.tools.windows.pending_action import PendingAction
from jarvis.tools.windows.process_service import ProcessService


class ConfirmOutcome(Enum):
    """Результат подтверждения ожидающего действия."""

    # Действие выполнено.
    EXECUTED = "executed"
    # Нет ожидающего действия.
    NO_PENDING = "no_pending"
    # Срок подтверждения истёк — действие сброшено.
    EXPIRED = "expired"
    # Действие не удалось выполнить.
    FAILED = "failed"


class SafeActionManager:
    # Срок жизни подтверждения, секунд.
    CONFIRM_TTL_SECONDS = 60

    def __init__(self, process_service: ProcessService, files: FileManager) -> None:
        self._lock = threading.Lock()
        self._process_service = process_service
        self._files = files
        self._pending: PendingAction = PendingAction.NONE
        self._target: str = ""
        self._requested_at: float = 0.0

    def request(self, action: PendingAction, target: str = "") -> None:
        with self._lock:
            self._pending = action
            self._target = target
            self._requested_at = time.monotonic()

    def cancel(self) -> None:
        with self._lock:
            self._pending = PendingAction.NONE
            self._target = ""

    def confirm(self) -> ConfirmOutcome:
        with self._lock:
            if self._pending is PendingAction.NONE:
                return ConfirmOutcome.NO_PENDING

            # Подтверждение имеет срок действия: «да», сказанное позже,
            # не выполняет опасную команду.
            if time.monotonic() - self._requested_at > self.CONFIRM_TTL_SECONDS:
                self._pending = PendingAction.NONE
                self._target = ""
                return ConfirmOutcome.EXPIRED

            action = self._pending
            target = self._target
            self._pending = PendingAction.NONE
            self._target = ""

            try:
                return (
                    ConfirmOutcome.EXECUTED
                    if self._execute(action, target)
                    else ConfirmOutcome.FAILED
                )
            except Exception as ex:
                print(f"[SafeActionManager] Ошибка выполнения: {ex}")
                return ConfirmOutcome.FAILED

    def _execute(self, action: PendingAction, target: str) -> bool:
        if action is PendingAction.SHUTDOWN:
            return self._start(["shutdown", "/s", "/t", "0"])
        if action is PendingAction.RESTART:
            return self._start(["shutdown", "/r", "/t", "0"])
        if action is PendingAction.SLEEP:
            return self._start(
                ["rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0"]
            )
        if action is PendingAction.KILL_PROCESS:
            return self._process_service.kill(target)
        if action is PendingAction.DELETE_FILE:
            return self._files.delete_file(target)
        return False

    @staticmethod
    def _start(argv: list[str]) -> bool:
        subprocess.Popen(
            argv,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
