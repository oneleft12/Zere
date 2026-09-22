"""Подтверждение опасных действий (порт Windows/SafeActionManager.cs)."""

from __future__ import annotations

import subprocess
import threading

from jarvis.tools.windows.pending_action import PendingAction


class SafeActionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: PendingAction = PendingAction.NONE

    def request(self, action: PendingAction) -> None:
        with self._lock:
            self._pending = action

    def confirm(self) -> bool:
        with self._lock:
            if self._pending is PendingAction.SHUTDOWN:
                subprocess.Popen(
                    ["shutdown", "/s", "/t", "0"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            elif self._pending is PendingAction.RESTART:
                subprocess.Popen(
                    ["shutdown", "/r", "/t", "0"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            elif self._pending is PendingAction.SLEEP:
                subprocess.Popen(
                    ["rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                return False

            self._pending = PendingAction.NONE
            return True

    def cancel(self) -> None:
        with self._lock:
            self._pending = PendingAction.NONE
