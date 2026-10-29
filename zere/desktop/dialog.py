"""Системные окна сообщений без зависимостей.

В desktop-режиме консоли нет: если сервер панели не поднялся или не открылось
окно, сообщить об этом нечем — пользователь видит «ничего не произошло».
Поэтому ошибки старта показываются окном Windows (`user32.MessageBoxW`), без
WinForms/`ctypes`-обвязок сверх одного вызова.

`MessageBoxW` блокирует вызывающий поток — это то, что нужно: сообщение
видно, пока приложение ещё живо (сервер панели в фоне продолжает отвечать).
"""

from __future__ import annotations

import sys

__all__ = ["show_error", "show_info"]

_MB_ICONERROR = 0x00000010
_MB_ICONINFORMATION = 0x00000040
_MB_SETFOREGROUND = 0x00010000
_MB_TOPMOST = 0x00040000


def _message_box(title: str, message: str, flags: int) -> None:
    if sys.platform != "win32":
        # На не-Windows (CI, разработка) окно не нужно — сообщение в поток.
        print(f"[{title}] {message}", file=sys.stderr)
        return

    try:
        import ctypes  # noqa: PLC0415 — Windows-only, импорт в момент вызова

        ctypes.windll.user32.MessageBoxW(None, message, title, flags)
    except Exception as ex:  # noqa: BLE001 — диалог не должен ронять приложение
        print(f"[{title}] {message} (окно: {ex})", file=sys.stderr)


def show_error(title: str, message: str) -> None:
    """Окно ошибки (красный значок), поверх остальных окон."""
    _message_box(title, message, _MB_ICONERROR | _MB_SETFOREGROUND | _MB_TOPMOST)


def show_info(title: str, message: str) -> None:
    """Информационное окно (синий значок)."""
    _message_box(title, message, _MB_ICONINFORMATION | _MB_SETFOREGROUND | _MB_TOPMOST)
