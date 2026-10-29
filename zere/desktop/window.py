"""Окно приложения поверх панели ZERE (pywebview + WebView2).

UI остаётся один — та же SPA, что раздаёт локальный сервер (`panel/dist`).
Меняется оболочка: вместо вкладки браузера пользователь видит обычное окно
Windows, а вместо консоли — иконку в панели задач. Поэтому экраны, темы и
i18n не дублируются: правим один фронтенд.

pywebview — необязательная зависимость: без неё `run_window` бросает
`DesktopWindowUnavailable`, и вызывающий код честно уходит в браузер.
Импорт ленивый, чтобы тесты и Linux-CI не тянули WinForms/CLR.
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

__all__ = [
    "DesktopWindowUnavailable",
    "PanelWindowHost",
    "open_in_browser",
    "run_window",
]


class DesktopWindowUnavailable(RuntimeError):
    """Окно приложения открыть нельзя (нет pywebview/WebView2 или сбой старта)."""


def open_in_browser(url: str) -> None:
    """Фолбэк: панель в браузере (как было до desktop-режима)."""
    webbrowser.open(url)


def _storage_dir(storage_path: Optional[Path]) -> Optional[str]:
    if storage_path is None:
        return None

    path = Path(storage_path)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def run_window(
    url: str,
    *,
    title: str = "ZERE",
    icon: Any = None,
    on_ready: Optional[Callable[[], None]] = None,
    storage_path: Any = None,
    width: int = 1280,
    height: int = 840,
    debug: bool = False,
) -> None:
    """Открывает окно панели и блокирует поток до его закрытия.

    Вызывать из главного потока: pywebview ставит обработчик SIGINT, а это
    разрешено только в главном потоке (из фонового — ValueError, поэтому в
    консольном режиме окно открывает `PanelWindowHost` с откатом в браузер).
    """
    try:
        import webview  # noqa: PLC0415 — необязательная зависимость, импорт по месту
    except Exception as ex:  # noqa: BLE001 — нет пакета/сломанное окружение
        raise DesktopWindowUnavailable(
            "pywebview не установлен — окно приложения недоступно "
            "(pip install pywebview)"
        ) from ex

    try:
        webview.create_window(
            title,
            url,
            width=width,
            height=height,
            min_size=(980, 620),
            background_color="#05080d",
            text_select=True,
            confirm_close=False,
        )
    except Exception as ex:  # noqa: BLE001 — несовместимый pywebview
        raise DesktopWindowUnavailable(f"окно не создано: {ex}") from ex

    try:
        webview.start(
            func=on_ready,
            icon=str(icon) if icon is not None else None,
            # private_mode=True стирал бы тему/язык панели (localStorage) при
            # каждом запуске — профиль WebView2 живёт в data/webview.
            private_mode=False,
            storage_path=_storage_dir(storage_path),
            debug=debug,
        )
    except Exception as ex:  # noqa: BLE001 — нет WebView2 Runtime и т.п.
        raise DesktopWindowUnavailable(f"окно не открылось: {ex}") from ex


class PanelWindowHost:
    """Одно окно панели в фоне — для консольного режима (команда «панель»).

    В консоли `webview.start()` нельзя звать из главного потока: он занят
    чтением команд. Запускаем окно в фоновом потоке; если pywebview не может
    так (ValueError про SIGINT, нет WebView2), зовём `on_failure` — обычно это
    открытие панели в браузере, то есть прежнее поведение.
    """

    def __init__(
        self,
        url: str,
        logger: Any,
        *,
        icon: Any = None,
        storage_path: Any = None,
        on_failure: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._url = url
        self._logger = logger
        self._icon = icon
        self._storage_path = storage_path
        self._on_failure = on_failure
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._window: Any = None
        self._webview: Any = None

    def open(self) -> None:
        """Показывает существующее окно или открывает новое (не блокирует)."""
        with self._lock:
            if self._window is not None:
                try:
                    self._window.restore()
                    self._window.show()
                    return
                except Exception:  # noqa: BLE001 — окно уже закрыто
                    self._window = None

            if self._thread is not None and self._thread.is_alive():
                return

            self._thread = threading.Thread(target=self._run, daemon=True, name="zere-window")
            self._thread.start()

    def _run(self) -> None:
        try:
            import webview  # noqa: PLC0415 — импорт в потоке окна

            self._webview = webview
            self._window = webview.create_window(
                "ZERE",
                self._url,
                width=1280,
                height=840,
                min_size=(980, 620),
                background_color="#05080d",
                text_select=True,
            )
            webview.start(
                icon=str(self._icon) if self._icon is not None else None,
                private_mode=False,
                storage_path=_storage_dir(self._storage_path),
            )
        except Exception as ex:  # noqa: BLE001 — фолбэк в браузер, консоль жива
            self._logger.error(f"PanelWindow: {ex}")
            self._fail(self._url)
        finally:
            self._window = None

    def _fail(self, url: str) -> None:
        if self._on_failure is not None:
            self._on_failure(url)
        else:
            open_in_browser(url)
