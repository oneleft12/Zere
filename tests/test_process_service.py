"""Тесты ProcessService: список, поиск и защита системных процессов.

Реальные процессы не завершаются: `psutil.process_iter` подменяется
фейковыми объектами, поэтому тест безопасен и на Linux, и на Windows.
"""

from __future__ import annotations

import types

import pytest

from zere.tools.windows import process_service as module
from zere.tools.windows.process_service import ProcessService


class FakeProcess:
    def __init__(self, pid: int, name: str, rss: int = 0) -> None:
        self.pid = pid
        self._name = name
        self._rss = rss
        self.killed = False

    def name(self) -> str:
        return self._name

    def memory_info(self) -> types.SimpleNamespace:
        return types.SimpleNamespace(rss=self._rss)

    def children(self, recursive: bool = False) -> list["FakeProcess"]:
        return []

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def fake_processes(monkeypatch: pytest.MonkeyPatch):
    processes = [
        FakeProcess(10, "chrome.exe", 300 * 1024 * 1024),
        FakeProcess(11, "discord.exe", 100 * 1024 * 1024),
        FakeProcess(12, "chrome.exe", 200 * 1024 * 1024),
    ]
    monkeypatch.setattr(module.psutil, "process_iter", lambda: iter(processes))

    by_pid = {process.pid: process for process in processes}

    def make_process(pid: int):
        if pid not in by_pid:
            raise module.psutil.NoSuchProcess(pid)
        return by_pid[pid]

    monkeypatch.setattr(module.psutil, "Process", make_process)
    return processes


def test_get_processes_sorted_by_memory(fake_processes) -> None:
    infos = ProcessService().get_processes()

    assert [info.id for info in infos] == [10, 12, 11]
    assert [info.name for info in infos] == ["chrome", "chrome", "discord"]
    assert infos[0].memory_mb == 300.0


def test_get_processes_skips_inaccessible(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        pid = 1

        def name(self):
            raise module.psutil.NoSuchProcess(1)

    monkeypatch.setattr(module.psutil, "process_iter", lambda: iter([Broken(), FakeProcess(2, "ok.exe", 1)]))

    infos = ProcessService().get_processes()

    assert [info.name for info in infos] == ["ok"]


def test_search_is_case_insensitive_and_partial(fake_processes) -> None:
    found = ProcessService().search("CHRO")

    assert [info.id for info in found] == [10, 12]


def test_search_exact_ignores_exe_and_case(fake_processes) -> None:
    service = ProcessService()

    assert [info.id for info in service.search_exact("Discord")] == [11]
    assert [info.id for info in service.search_exact("discord.exe")] == [11]
    assert service.search_exact("disc") == []


def test_kill_fake_process(fake_processes) -> None:
    service = ProcessService()

    assert service.kill("discord.exe") is True
    assert fake_processes[1].killed is True
    assert fake_processes[0].killed is False


def test_kill_missing_process_is_false(fake_processes) -> None:
    assert ProcessService().kill("no-such-process-zere") is False


@pytest.mark.parametrize(
    "name",
    [
        "svchost",
        "svchost.exe",
        "SVCHOST.EXE",
        "lsass",
        "csrss",
        "winlogon",
        "services",
        "System",
        "smss.exe",
        "memory compression",
    ],
)
def test_protected_processes_are_denied(name: str, fake_processes) -> None:
    assert ProcessService.is_protected(name) is True
    assert ProcessService().kill(name) is False
    assert all(not process.killed for process in fake_processes)


@pytest.mark.parametrize("name", ["discord", "chrome.exe", "", "  ", ".exe"])
def test_regular_processes_are_not_protected(name: str) -> None:
    assert ProcessService.is_protected(name) is False


def test_kill_pid_rejects_invalid_pid(fake_processes) -> None:
    service = ProcessService()

    assert service.kill_pid(0) is False
    assert service.kill_pid(-5) is False
    assert service.kill_pid(999_999) is False


def test_kill_pid_kills_matching_process(fake_processes) -> None:
    assert ProcessService().kill_pid(11) is True
    assert fake_processes[1].killed is True


def test_kill_pid_refuses_protected(fake_processes, monkeypatch: pytest.MonkeyPatch) -> None:
    protected = FakeProcess(4, "lsass.exe", 1)
    monkeypatch.setattr(module.psutil, "Process", lambda pid: protected)

    assert ProcessService().kill_pid(4) is False
    assert protected.killed is False
