"""Тесты SafeActionManager: подтверждение, TTL, исполнение и отмена.

Питание и завершение процессов не выполняются по-настоящему: методы
`_start`/`kill` подменяются, поэтому тест безопасен на любой машине.
"""

from __future__ import annotations

import pytest

from zere.tools.windows import safe_action_manager as module
from zere.tools.windows.pending_action import PendingAction
from zere.tools.windows.safe_action_manager import ConfirmOutcome, SafeActionManager


class FakeProcessService:
    def __init__(self) -> None:
        self.killed: list[str] = []
        self.result = True

    def kill(self, name: str) -> bool:
        self.killed.append(name)
        return self.result


class FakeFiles:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.result = True

    def delete_file(self, name: str) -> bool:
        self.deleted.append(name)
        return self.result


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch):
    processes = FakeProcessService()
    files = FakeFiles()
    instance = SafeActionManager(processes, files)  # type: ignore[arg-type]
    # Питание не должно реально выключать машину.
    started: list[list[str]] = []
    monkeypatch.setattr(
        SafeActionManager,
        "_start",
        staticmethod(lambda argv: started.append(list(argv)) or True),
    )
    return instance, processes, files, started


def test_confirm_without_pending_is_no_pending(manager) -> None:
    actions, _, _, _ = manager
    assert actions.confirm() is ConfirmOutcome.NO_PENDING


def test_confirm_executes_kill_once(manager) -> None:
    actions, processes, _, _ = manager

    actions.request(PendingAction.KILL_PROCESS, "discord")

    assert actions.confirm() is ConfirmOutcome.EXECUTED
    assert processes.killed == ["discord"]
    # Подтверждение одноразовое.
    assert actions.confirm() is ConfirmOutcome.NO_PENDING


def test_confirm_deletes_file(manager) -> None:
    actions, _, files, _ = manager

    actions.request(PendingAction.DELETE_FILE, "note.txt")

    assert actions.confirm() is ConfirmOutcome.EXECUTED
    assert files.deleted == ["note.txt"]


def test_failed_action_returns_failed(manager) -> None:
    actions, processes, _, _ = manager
    processes.result = False

    actions.request(PendingAction.KILL_PROCESS, "discord")

    assert actions.confirm() is ConfirmOutcome.FAILED


def test_power_actions_use_expected_commands(manager) -> None:
    actions, _, _, started = manager

    actions.request(PendingAction.SHUTDOWN)
    assert actions.confirm() is ConfirmOutcome.EXECUTED
    assert started[0][:2] == ["shutdown", "/s"]

    actions.request(PendingAction.RESTART)
    assert actions.confirm() is ConfirmOutcome.EXECUTED
    assert started[1][:2] == ["shutdown", "/r"]

    actions.request(PendingAction.SLEEP)
    assert actions.confirm() is ConfirmOutcome.EXECUTED
    assert "powrprof.dll,SetSuspendState 0,1,0" in started[2]


def test_expired_confirmation_is_dropped(manager, monkeypatch: pytest.MonkeyPatch) -> None:
    actions, processes, _, _ = manager
    clock = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    actions.request(PendingAction.KILL_PROCESS, "discord")
    clock[0] += SafeActionManager.CONFIRM_TTL_SECONDS + 1

    assert actions.confirm() is ConfirmOutcome.EXPIRED
    assert processes.killed == []
    assert actions.confirm() is ConfirmOutcome.NO_PENDING


def test_confirmation_within_ttl_still_works(manager, monkeypatch: pytest.MonkeyPatch) -> None:
    actions, processes, _, _ = manager
    clock = [500.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    actions.request(PendingAction.KILL_PROCESS, "discord")
    clock[0] += SafeActionManager.CONFIRM_TTL_SECONDS - 1

    assert actions.confirm() is ConfirmOutcome.EXECUTED
    assert processes.killed == ["discord"]


def test_cancel_drops_pending(manager) -> None:
    actions, processes, _, _ = manager

    actions.request(PendingAction.KILL_PROCESS, "discord")
    actions.cancel()

    assert actions.confirm() is ConfirmOutcome.NO_PENDING
    assert processes.killed == []


def test_router_command_executor(manager) -> None:
    actions, _, _, _ = manager
    actions.set_command_executor(lambda phrase: f"выполнено: {phrase}")

    actions.request(PendingAction.ROUTER_COMMAND, "очисти память")

    assert actions.confirm() is ConfirmOutcome.EXECUTED
    assert actions.last_result == "выполнено: очисти память"


def test_router_command_without_executor_fails(manager) -> None:
    actions, _, _, _ = manager
    actions.request(PendingAction.ROUTER_COMMAND, "очисти память")

    assert actions.confirm() is ConfirmOutcome.FAILED


def test_router_executor_returning_none_fails(manager) -> None:
    actions, _, _, _ = manager
    actions.set_command_executor(lambda phrase: None)
    actions.request(PendingAction.ROUTER_COMMAND, "что-то")

    assert actions.confirm() is ConfirmOutcome.FAILED
    assert actions.last_result is None


def test_unknown_action_does_not_execute(manager) -> None:
    actions, processes, files, started = manager
    actions.request(PendingAction.NONE)

    assert actions.confirm() is ConfirmOutcome.NO_PENDING
    assert processes.killed == [] and files.deleted == [] and started == []


def test_execute_exception_returns_failed(manager, monkeypatch: pytest.MonkeyPatch) -> None:
    actions, _, _, _ = manager

    def boom(argv):
        raise OSError("нет прав")

    monkeypatch.setattr(SafeActionManager, "_start", staticmethod(boom))
    actions.request(PendingAction.SHUTDOWN)

    assert actions.confirm() is ConfirmOutcome.FAILED
