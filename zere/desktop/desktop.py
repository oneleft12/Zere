"""Сценарий desktop-запуска: панель → окно → корректное завершение.

Консольный режим (`main.py` без флагов) остаётся для отладки; приложение —
это `zere.exe`, который передаёт `--desktop`. Оба режима поднимают один и
тот же сервер панели и один и тот же движок, поэтому поведение ассистента
не расходится.

Коды возврата нужны лаунчеру (`zere.exe`), чтобы не показывать второе окно
ошибки поверх уже показанного Python-стороной:

- 0 — обычный выход (пользователь закрыл окно);
- 2 — окно не открылось (диалог уже показан, панель ушла в браузер);
- 3 — панель не поднялась, вероятно ZERE уже запущен (диалог уже показан).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from zere.desktop.dialog import show_error
from zere.desktop.window import open_in_browser, run_window

__all__ = [
    "DESKTOP_FLAGS",
    "DesktopUi",
    "EXIT_ALREADY_RUNNING",
    "EXIT_OK",
    "EXIT_WINDOW_UNAVAILABLE",
    "desktop_requested",
    "port_from_argv",
    "run_desktop",
]

#: Флаги, включающие приложение (все — одно и то же, для привычки и скриптов).
DESKTOP_FLAGS = frozenset({"--desktop", "--app", "--gui"})

EXIT_OK = 0
EXIT_WINDOW_UNAVAILABLE = 2
EXIT_ALREADY_RUNNING = 3

def _already_running_text(port: int) -> str:
    """Текст про занятый порт — с тем портом, который реально не поднялся."""
    return (
        f"ZERE не запустился: порт {port} занят.\n\n"
        "Скорее всего, ZERE уже работает — закройте его окно (или завершите "
        "процесс pythonw.exe) и запустите снова.\n\n"
        "Если порт занят другой программой, укажите другой порт: "
        f"zere.exe --desktop --port {port + 1}"
    )

_WINDOW_UNAVAILABLE_TEXT = (
    "Окно приложения не открылось.\n\n"
    "Панель открыта в браузере — ZERE работает, но кнопка «Выход» в окне "
    "браузера не завершает ассистента: окно закроется только после нажатия "
    "«ОК» здесь.\n\n"
    "Чтобы вернуть окно приложения, установите pywebview и WebView2 Runtime:\n"
    "  pip install pywebview\n"
    "https://developer.microsoft.com/microsoft-edge/webview2/"
)


@dataclass
class DesktopUi:
    """Точки вывода desktop-режима (подменяются в тестах)."""

    window: Callable[..., None] = run_window
    error: Callable[[str, str], None] = show_error
    browser: Callable[[str], None] = open_in_browser


def desktop_requested(argv: list[str]) -> bool:
    """Запрошен ли режим приложения (флаг в любом месте строки запуска)."""
    return any(argument in DESKTOP_FLAGS for argument in argv)


def port_from_argv(argv: list[str], default: int) -> int:
    """Порт панели из `--port N` / `--port=N` (иначе default)."""
    for index, argument in enumerate(argv):
        value: Optional[str] = None

        if argument == "--port" and index + 1 < len(argv):
            value = argv[index + 1]
        elif argument.startswith("--port="):
            value = argument[len("--port=") :]

        if value is None:
            continue

        try:
            port = int(value)
        except ValueError:
            continue

        if 0 < port <= 65535:
            return port

    return default


def run_desktop(
    *,
    panel: Any,
    voice: Any,
    logger: Any,
    ui: Optional[DesktopUi] = None,
    on_ready: Optional[Callable[[], None]] = None,
    icon: Any = None,
    storage_path: Any = None,
) -> int:
    """Поднимает панель, открывает окно и ждёт его закрытия.

    `on_ready` вызывается pywebview после старта GUI — там тяжёлая часть
    (голос, прогрев модели), чтобы окно появлялось сразу.
    """
    ui = ui or DesktopUi()

    try:
        panel.start()
    except OSError as ex:
        logger.error(f"PanelServer: {ex}")
        ui.error("ZERE", _already_running_text(panel.port))
        return EXIT_ALREADY_RUNNING

    url = f"http://127.0.0.1:{panel.port}"
    logger.info(f"Панель: {url}")
    print(f"[Панель] {url}")

    try:
        try:
            ui.window(url, on_ready=on_ready, icon=icon, storage_path=storage_path)
        except Exception as ex:  # noqa: BLE001 — любой сбой окна (включая DesktopWindowUnavailable)
            logger.error(f"DesktopWindow: {ex}")
            ui.browser(url)
            ui.error("ZERE", _WINDOW_UNAVAILABLE_TEXT)
            return EXIT_WINDOW_UNAVAILABLE
    finally:
        # Окно закрыто (или не открылось) — гасим сервер и голос. Панель
        # останавливается до голоса: VoiceModeRunner держит микрофон.
        try:
            panel.stop()
        except Exception as ex:  # noqa: BLE001 — завершение не должно падать
            logger.error(f"PanelServer.stop: {ex}")

        try:
            voice.close()
        except Exception as ex:  # noqa: BLE001
            logger.error(f"Voice close: {ex}")

        logger.info("ZERE завершил работу.")
        print("[ZERE] Завершено.")

    return EXIT_OK
