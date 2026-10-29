"""Тесты десктоп-режима: окно вместо консоли и браузера.

Что проверяется (без GUI и без pywebview — CI идёт на Linux):

- `ensure_std_streams` — у pythonw stdout/stderr = None; без подмены
  диагностика старта исчезает, а `flush()` падает;
- разбор флагов `--desktop`/`--app`/`--gui` и порта `--port`;
- сценарий `run_desktop`: панель поднимается, окно открывается, при закрытии
  сервер и голос гасятся; занятый порт и сбой окна дают честные коды и
  сообщения (по ним лаунчер решает, показывать ли второе окно ошибки);
- артефакты приложения: исходник лаунчера, собранный `zere.exe`, иконка.

Запуск: python tests/test_desktop.py
"""

from __future__ import annotations

import builtins
import contextlib
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zere import paths  # noqa: E402
from zere.desktop.desktop import (  # noqa: E402
    EXIT_ALREADY_RUNNING,
    EXIT_OK,
    EXIT_WINDOW_UNAVAILABLE,
    DesktopUi,
    desktop_requested,
    port_from_argv,
    run_desktop,
)
from zere.desktop.stdio import ensure_std_streams  # noqa: E402
from zere.desktop.window import DesktopWindowUnavailable, run_window  # noqa: E402


@contextlib.contextmanager
def _patch(owner: Any, name: str, value: Any) -> Iterator[None]:
    """Подменяет атрибут на время блока (аналог monkeypatch без pytest)."""
    original = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, original)


# ---------------------------------------------------------------------------
# Стандартный вывод (pythonw: консоли нет)
# ---------------------------------------------------------------------------


def test_stdio_redirects_missing_streams() -> None:
    """None-потоки уводятся в журнал: печать не теряется и не падает."""
    with tempfile.TemporaryDirectory(prefix="zere-desktop-") as tmp:
        log_path = Path(tmp) / "desktop.log"

        with _patch(sys, "stdout", None), _patch(sys, "stderr", None):
            assert ensure_std_streams(log_path) == log_path
            assert sys.stdout is not None and sys.stderr is not None

            print("ZERE стартует")
            sys.stdout.flush()

            assert "ZERE стартует" in log_path.read_text(encoding="utf-8")

            # Windows не даёт удалить открытый файл: закрываем до выхода.
            sys.stdout.close()


def test_stdio_keeps_console() -> None:
    """Когда консоль есть, подмена не включается (вывод остаётся на экране)."""
    with tempfile.TemporaryDirectory(prefix="zere-desktop-") as tmp:
        log_path = Path(tmp) / "desktop.log"

        assert ensure_std_streams(log_path) is None
        assert not log_path.exists()


# ---------------------------------------------------------------------------
# Разбор командной строки
# ---------------------------------------------------------------------------


def test_desktop_requested() -> None:
    for flag in ("--desktop", "--app", "--gui"):
        assert desktop_requested([flag]) is True
        assert desktop_requested(["main.py", flag, "--port", "8081"]) is True

    assert desktop_requested([]) is False
    assert desktop_requested(["--console"]) is False
    assert desktop_requested(["--port", "9000"]) is False


def test_port_from_argv() -> None:
    cases = [
        ([], 8080),
        (["--port", "8091"], 8091),
        (["--port=9000"], 9000),
        (["--port", "0"], 8080),
        (["--port", "70000"], 8080),
        (["--port", "не-число"], 8080),
        (["--desktop", "--port", "8123"], 8123),
    ]

    for argv, expected in cases:
        assert port_from_argv(argv, 8080) == expected, f"{argv} -> {expected}"


# ---------------------------------------------------------------------------
# Сценарий запуска
# ---------------------------------------------------------------------------


class FakeLogger:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.infos: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)


class FakePanel:
    def __init__(self, port: int = 8099, fail: Optional[Exception] = None) -> None:
        self._port = port
        self._fail = fail
        self.started = False
        self.stopped = False

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        self.started = True
        if self._fail is not None:
            raise self._fail

    def stop(self) -> None:
        self.stopped = True


class FakeVoice:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeUi:
    """Подменяет окно/браузер/диалог; окно «закрывается» сразу."""

    def __init__(self, window_error: Optional[Exception] = None) -> None:
        self._window_error = window_error
        self.window_calls: list[dict[str, Any]] = []
        self.browser_urls: list[str] = []
        self.errors: list[tuple[str, str]] = []
        self.ready_called = False

    def window(self, url: str, **kwargs: Any) -> None:
        self.window_calls.append({"url": url, **kwargs})
        on_ready = kwargs.get("on_ready")
        if on_ready is not None:
            self.ready_called = True
            on_ready()
        if self._window_error is not None:
            raise self._window_error

    def error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def browser(self, url: str) -> None:
        self.browser_urls.append(url)


def test_run_desktop_opens_window_and_shuts_down() -> None:
    """Обычный путь: панель стартовала, окно открылось, после закрытия — стоп."""
    panel = FakePanel()
    voice = FakeVoice()
    logger = FakeLogger()
    ui = FakeUi()
    ready: list[str] = []

    code = run_desktop(
        panel=panel,
        voice=voice,
        logger=logger,
        ui=ui,
        on_ready=lambda: ready.append("ready"),
    )

    assert code == EXIT_OK
    assert ready == ["ready"], "on_ready должен вызываться после старта окна"
    assert panel.started and panel.stopped
    assert voice.closed
    assert ui.ready_called
    assert ui.window_calls[0]["url"] == "http://127.0.0.1:8099"
    assert any("Панель" in line for line in logger.infos)
    assert any("завершил" in line for line in logger.infos)


def test_run_desktop_reports_busy_port() -> None:
    """Порт занят (вероятно, ZERE уже запущен): диалог и код 3, без окна."""
    panel = FakePanel(fail=OSError("address already in use"))
    voice = FakeVoice()
    logger = FakeLogger()
    ui = FakeUi()

    code = run_desktop(panel=panel, voice=voice, logger=logger, ui=ui)

    assert code == EXIT_ALREADY_RUNNING
    assert ui.window_calls == []
    assert ui.errors and "8080" in ui.errors[0][1]
    assert logger.errors


def test_run_desktop_falls_back_to_browser() -> None:
    """Окно не открылось: панель в браузере, диалог, корректное завершение."""
    panel = FakePanel()
    voice = FakeVoice()
    logger = FakeLogger()
    ui = FakeUi(window_error=DesktopWindowUnavailable("нет WebView2"))

    code = run_desktop(panel=panel, voice=voice, logger=logger, ui=ui)

    assert code == EXIT_WINDOW_UNAVAILABLE
    assert ui.browser_urls == ["http://127.0.0.1:8099"]
    assert ui.errors
    # Сервер живёт, пока пользователь не закрыл диалог: панель в браузере
    # должна успеть ответить, поэтому stop — только после окна.
    assert panel.stopped and voice.closed


def test_desktop_ui_defaults_are_real_handlers() -> None:
    """DesktopUi по умолчанию — настоящие функции, а не заглушки."""
    ui = DesktopUi()
    assert callable(ui.window) and callable(ui.error) and callable(ui.browser)


# ---------------------------------------------------------------------------
# Окно без pywebview
# ---------------------------------------------------------------------------


def test_run_window_without_pywebview() -> None:
    """Без пакета окно не притворяется открытым — понятная ошибка."""
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "webview":
            raise ImportError("No module named 'webview'")
        return real_import(name, *args, **kwargs)

    with _patch(builtins, "__import__", fake_import):
        try:
            run_window("http://127.0.0.1:8080")
        except DesktopWindowUnavailable as error:
            assert "pywebview" in str(error)
        else:
            raise AssertionError("без pywebview окно не должно открываться")


# ---------------------------------------------------------------------------
# Артефакты приложения
# ---------------------------------------------------------------------------


def test_desktop_assets_exist() -> None:
    """Лаунчер, собранный exe и иконка лежат там, где их ждёт установщик."""
    assert (ROOT / "zere" / "desktop" / "launcher" / "ZereLauncher.cs").is_file()
    assert (ROOT / "zere.exe").is_file()
    assert (ROOT / "assets" / "zere.ico").is_file()


def test_paths_point_inside_repo() -> None:
    """Журнал приложения и профиль WebView2 — в своих каталогах, не в корне."""
    with tempfile.TemporaryDirectory(prefix="zere-desktop-") as tmp:
        with _patch(paths, "DATA_DIR", Path(tmp) / "data"):
            assert paths.desktop_log_path() == paths.LOGS_DIR / "desktop.log"
            assert paths.icon_path() == str(paths.ASSETS_DIR / "zere.ico")
            assert paths.webview_dir() == Path(tmp) / "data" / "webview"


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов десктоп-режима")


if __name__ == "__main__":
    sys.exit(main())
