"""Управление питанием (порт System/PowerController.cs)."""

from __future__ import annotations

import ctypes
import subprocess


class PowerController:
    def shutdown(self) -> None:
        # Process.Start("shutdown", "/s /t 0", CreateNoWindow, !UseShellExecute)
        subprocess.Popen(
            ["shutdown", "/s", "/t", "0"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def restart(self) -> None:
        # Process.Start("shutdown", "/r /t 0", CreateNoWindow, !UseShellExecute)
        subprocess.Popen(
            ["shutdown", "/r", "/t", "0"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def sleep(self) -> None:
        # Process.Start("rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0", ...)
        subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def lock(self) -> None:
        # [DllImport("user32.dll")] private static extern bool LockWorkStation();
        ctypes.windll.user32.LockWorkStation()
