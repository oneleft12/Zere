"""Тесты автозапуска ZERE вместе с Windows (zere/core/autostart.py).

Реестр не трогается: подменяются платформа и хранилище (FakeBackend), поэтому
тесты одинаково идут на Windows и в CI. Проверяется главное для пользователя:
включение пишет команду текущей установки, отключение удаляет запись,
устаревший путь виден и перезаписывается, а без лаунчера ничего не пишется.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import pytest

from zere.core.autostart import (
    LOCATION,
    VALUE_NAME,
    AutostartError,
    AutostartService,
    AutostartUnsupportedError,
    command_line,
    launch_command,
)


class FakeBackend:
    """Хранилище записи автозапуска в памяти (вместо winreg)."""

    def __init__(
        self,
        value: Optional[str] = None,
        *,
        read_error: Optional[AutostartError] = None,
        write_error: Optional[AutostartError] = None,
        delete_error: Optional[AutostartError] = None,
    ) -> None:
        self.value = value
        self.read_error = read_error
        self.write_error = write_error
        self.delete_error = delete_error
        self.writes: list[str] = []
        self.deletes = 0

    def read(self) -> Optional[str]:
        if self.read_error is not None:
            raise self.read_error
        return self.value

    def write(self, command: str) -> None:
        if self.write_error is not None:
            raise self.write_error
        self.writes.append(command)
        self.value = command

    def delete(self) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deletes += 1
        self.value = None


def make_service(
    root: Path,
    backend: Optional[FakeBackend] = None,
    *,
    platform: str = "win32",
) -> tuple[AutostartService, FakeBackend]:
    fake = backend if backend is not None else FakeBackend()
    return AutostartService(backend=fake, platform=platform, root=root), fake


def make_launcher(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    exe = root / "zere.exe"
    exe.write_bytes(b"MZ")
    return exe


# ── Команда запуска ───────────────────────────────────────────────


def test_launch_command_prefers_launcher(tmp_path: Path) -> None:
    exe = make_launcher(tmp_path)
    assert launch_command(tmp_path) == [str(exe)]


def test_launch_command_falls_back_to_pythonw(tmp_path: Path) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    pythonw = scripts / "pythonw.exe"
    pythonw.write_bytes(b"MZ")
    (tmp_path / "main.py").write_text("print('zere')", encoding="utf-8")

    assert launch_command(tmp_path) == [str(pythonw), str(tmp_path / "main.py"), "--desktop"]


def test_launch_command_without_app_returns_none(tmp_path: Path) -> None:
    assert launch_command(tmp_path) is None


def test_command_line_quotes_paths_with_spaces(tmp_path: Path) -> None:
    exe = make_launcher(tmp_path / "Zere App")
    line = command_line([str(exe)])
    assert line == f'"{exe}"'
    assert " " in line


# ── Состояние и переключение ──────────────────────────────────────


def test_status_disabled_when_no_entry(tmp_path: Path) -> None:
    make_launcher(tmp_path)
    service, _ = make_service(tmp_path)

    state = service.status()

    assert state.supported is True
    assert state.enabled is False
    assert state.command == ""
    assert state.location == LOCATION
    assert state.reason == ""
    assert state.expected_command.endswith("zere.exe")


def test_enable_writes_current_launcher(tmp_path: Path) -> None:
    exe = make_launcher(tmp_path)
    service, backend = make_service(tmp_path)

    state = service.set_enabled(True)

    expected = command_line([str(exe)])
    assert backend.writes == [expected]
    assert state.enabled is True
    assert state.command == expected
    assert state.outdated is False


def test_disable_removes_entry(tmp_path: Path) -> None:
    make_launcher(tmp_path)
    service, backend = make_service(tmp_path, FakeBackend(value='"C:\\Old\\zere.exe"'))

    state = service.set_enabled(False)

    assert backend.deletes == 1
    assert backend.value is None
    assert state.enabled is False
    assert state.command == ""


def test_disable_without_entry_is_not_an_error(tmp_path: Path) -> None:
    make_launcher(tmp_path)
    service, backend = make_service(tmp_path)

    state = service.set_enabled(False)

    assert state.enabled is False
    assert backend.deletes == 1


def test_outdated_entry_is_reported_and_rewritten(tmp_path: Path) -> None:
    exe = make_launcher(tmp_path)
    service, backend = make_service(tmp_path, FakeBackend(value='"C:\\Moved\\zere.exe"'))

    state = service.status()
    assert state.enabled is True
    assert state.outdated is True
    assert state.command == '"C:\\Moved\\zere.exe"'

    updated = service.set_enabled(True)
    assert backend.value == command_line([str(exe)])
    assert updated.outdated is False


def test_status_keeps_current_entry_even_if_launcher_missing(tmp_path: Path) -> None:
    """Запись есть, а zere.exe рядом нет: отключение всё равно работает."""
    service, backend = make_service(tmp_path, FakeBackend(value='"C:\\Old\\zere.exe"'))

    state = service.status()
    assert state.enabled is True
    assert state.expected_command == ""
    assert state.outdated is False  # не с чем сравнивать

    service.set_enabled(False)
    assert backend.value is None


def test_enable_without_launcher_raises_and_writes_nothing(tmp_path: Path) -> None:
    service, backend = make_service(tmp_path)

    with pytest.raises(AutostartError, match="команду запуска"):
        service.set_enabled(True)

    assert backend.writes == []


# ── Платформа и ошибки реестра ────────────────────────────────────


def test_unsupported_platform_is_read_only(tmp_path: Path) -> None:
    make_launcher(tmp_path)
    service, backend = make_service(tmp_path, platform="linux")

    state = service.status()
    assert state.supported is False
    assert state.enabled is False
    assert "только в Windows" in state.reason

    with pytest.raises(AutostartUnsupportedError):
        service.set_enabled(True)
    assert backend.writes == []


def test_read_error_is_reported_honestly(tmp_path: Path) -> None:
    make_launcher(tmp_path)
    service, _ = make_service(
        tmp_path,
        FakeBackend(read_error=AutostartError("Не удалось прочитать автозапуск: отказ")),
    )

    state = service.status()

    assert state.supported is True
    assert state.enabled is False
    assert "Не удалось прочитать" in state.reason


def test_write_error_propagates(tmp_path: Path) -> None:
    make_launcher(tmp_path)
    service, _ = make_service(
        tmp_path,
        FakeBackend(write_error=AutostartError("Не удалось включить автозапуск: отказ")),
    )

    with pytest.raises(AutostartError, match="включить"):
        service.set_enabled(True)


def test_unknown_platform_does_not_create_backend() -> None:
    service = AutostartService(platform="linux")
    assert service.backend is None
    assert service.supported is False


def test_state_dict_is_camel_case(tmp_path: Path) -> None:
    make_launcher(tmp_path)
    service, _ = make_service(tmp_path)

    payload = service.status().to_dict()

    assert set(payload) == {
        "supported",
        "enabled",
        "command",
        "expectedCommand",
        "outdated",
        "location",
        "reason",
    }
    assert payload["location"] == LOCATION


def test_value_name_is_stable_for_task_manager() -> None:
    """Имя записи видно в «Диспетчере задач» → «Автозагрузка»."""
    assert VALUE_NAME == "ZERE"
    assert LOCATION == r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"


def test_list2cmdline_matches_windows_quoting() -> None:
    # Та же функция, что уходит в реестр: путь с пробелом — в кавычках.
    assert subprocess.list2cmdline([r"C:\Zere\zere.exe"]) == r"C:\Zere\zere.exe"
