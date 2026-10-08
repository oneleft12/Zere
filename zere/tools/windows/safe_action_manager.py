"""Подтверждение опасных действий (порт Windows/SafeActionManager.cs).

Ожидающее действие живёт ограниченное время (TTL) — «да», сказанное спустя
долгое время, ничего не выполнит.
"""

from __future__ import annotations

import subprocess
import threading
import time
from enum import Enum
from typing import Callable, Optional

from zere.tools.files.file_manager import FileManager
from zere.tools.windows.pending_action import PendingAction
from zere.tools.windows.process_service import ProcessService


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
        # RLock, а не Lock: выполнение подтверждённой команды роутера идёт
        # внутри confirm() и может само запросить подтверждение (например,
        # «очисти память» → «закрой процесс»). Обычный Lock здесь дал бы
        # вечную блокировку на повторном request() из того же потока.
        self._lock = threading.RLock()
        self._process_service = process_service
        self._files = files
        self._pending: PendingAction = PendingAction.NONE
        self._target: str = ""
        self._requested_at: float = 0.0
        #: Исполнитель команд роутера интентов Jev (зовётся после «да»).
        self._command_executor: Optional[Callable[[str], Optional[str]]] = None
        self._last_result: Optional[str] = None

    def set_command_executor(
        self, executor: Optional[Callable[[str], Optional[str]]]
    ) -> None:
        """Кто выполняет подтверждённую команду роутера интентов.

        Менеджер не знает про пайплайн обработчиков: команду выполняет тот,
        кто её предложил (роутер), а менеджер держит подтверждение «да/нет»
        и срок его жизни — так же, как для питания и завершения процессов.
        """
        with self._lock:
            self._command_executor = executor

    @property
    def last_result(self) -> Optional[str]:
        """Ответ обработчика на последнее подтверждённое действие (или None)."""
        with self._lock:
            return self._last_result

    def request(self, action: PendingAction, target: str = "") -> None:
        with self._lock:
            self._pending = action
            self._target = target
            self._requested_at = time.monotonic()
            self._last_result = None

    def cancel(self) -> None:
        with self._lock:
            self._pending = PendingAction.NONE
            self._target = ""
            self._last_result = None

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
            self._last_result = None

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
        if action is PendingAction.ROUTER_COMMAND:
            executor = self._command_executor
            if executor is None:
                return False
            result = executor(target)
            # Ответ обработчика запоминаем: его покажет «да»-ветка WindowsHandler.
            self._last_result = result
            return result is not None
        return False

    @staticmethod
    def _start(argv: list[str]) -> bool:
        subprocess.Popen(
            argv,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
