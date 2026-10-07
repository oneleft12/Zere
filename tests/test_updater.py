"""Тесты обновления из GitHub (docs/UPDATE.md): настоящий git в temp-каталоге.

Сети нет: роль GitHub играет локальный bare-репозиторий, клонированный
рядом. Проверяем то, что нельзя проверить на фейке панели: сравнение с
удалённой веткой, fast-forward, отказ при незакоммиченных правках и при
расхождении веток, обновление зависимостей по изменившемуся
requirements.txt и разбор ошибок (нет git, нет репозитория, нет связи).

Запуск:
- `python3 tests/test_updater.py` — нужен только git;
- `pytest tests/ -q` — в CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Корень репозитория — чтобы запуск без установки пакета работал.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.test_panel_api import SPEC, assert_schema
from zere.core.update.updater import UpdateBusyError, UpdateService

# ── git в temp-каталоге ───────────────────────────────────────────

_ENV: dict[str, str] = dict(os.environ)
_ENV.update(
    {
        "GIT_AUTHOR_NAME": "ZERE Test",
        "GIT_AUTHOR_EMAIL": "zere-test@example.com",
        "GIT_COMMITTER_NAME": "ZERE Test",
        "GIT_COMMITTER_EMAIL": "zere-test@example.com",
        # Чужие ~/.gitconfig и системный конфиг в тестах не читаем:
        # identity задана переменными выше, ветка — явным --initial-branch.
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
)


def _git(cwd: Path, *args: str) -> str:
    """git-команда в тестовом репозитории; вывод — stdout (иначе тест падает)."""
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )

    assert completed.returncode == 0, f"git {' '.join(args)}: {completed.stdout}"
    return completed.stdout.strip()


class _Project:
    """Локальный «GitHub»: bare origin + рабочая копия + клон разработчика."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.origin = root / "origin"
        self.work = root / "work"
        self.dev = root / "dev"

    def create(self) -> "_Project":
        self.root.mkdir(parents=True, exist_ok=True)
        self.origin.mkdir()
        _git(self.origin, "init", "--bare", "--initial-branch=main")

        _git(self.root, "clone", str(self.origin), str(self.work))
        (self.work / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")
        (self.work / "app.py").write_text("print('v1')\n", encoding="utf-8")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-m", "Первый коммит")
        _git(self.work, "push", "-u", "origin", "main")

        _git(self.root, "clone", str(self.origin), str(self.dev))
        return self

    def publish(
        self,
        name: str,
        *,
        content: str = "print('v2')\n",
        change_requirements: bool = False,
    ) -> str:
        """Новый коммит «разработчика» в origin; возвращает его SHA."""
        (self.dev / name).write_text(content, encoding="utf-8")

        if change_requirements:
            (self.dev / "requirements.txt").write_text(
                "pyyaml\nrequests\n", encoding="utf-8"
            )

        _git(self.dev, "add", "-A")
        _git(self.dev, "commit", "-m", f"Обновление {name}")
        _git(self.dev, "push", "origin", "main")
        return _git(self.dev, "rev-parse", "HEAD")


def _assert_status(state: dict) -> None:
    """Состояние обязано совпадать с контрактом /api/update и сериализоваться."""
    assert_schema(SPEC["components"]["schemas"]["UpdateStatus"], state)
    json.dumps(state, ensure_ascii=False)


def _assert_outcome(outcome: dict) -> None:
    assert_schema(SPEC["components"]["schemas"]["UpdateOutcome"], outcome)
    json.dumps(outcome, ensure_ascii=False)


# ── Проверка и применение ─────────────────────────────────────────


def test_fresh_clone_has_no_updates() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        service = UpdateService(root=project.work)
        state = service.status()

        _assert_status(state)
        assert state["available"] is True
        assert state["branch"] == "main"
        assert state["remote"] == "origin"
        assert state["behind"] == 0
        assert state["ahead"] == 0
        assert state["commits"] == []
        assert state["updateAvailable"] is False
        assert state["canUpdate"] is False
        assert state["dirty"] is False
        assert state["error"] is None
        assert state["checkedAt"] is not None


def test_check_detects_new_commits_and_apply_fast_forwards() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        service = UpdateService(root=project.work)
        before = service.status()["current"]["hash"]

        published = project.publish("feature.txt")

        state = service.check()
        _assert_status(state)
        assert state["behind"] == 1
        assert state["ahead"] == 0
        assert state["updateAvailable"] is True
        assert state["canUpdate"] is True
        assert state["blockedReason"] is None
        assert state["target"]["hash"] == published
        assert state["commits"][0]["subject"] == "Обновление feature.txt"
        assert not (project.work / "feature.txt").exists()  # до применения

        outcome = service.apply(install_dependencies=False)

        _assert_outcome(outcome)
        assert outcome["ok"] is True
        assert outcome["pulled"] == 1
        assert outcome["fromHash"] == before
        assert outcome["toHash"] == published
        assert outcome["dependencies"] == "not-needed"
        assert outcome["restartRequired"] is True
        assert (project.work / "feature.txt").is_file()

        after = service.status()
        _assert_status(after)
        assert after["behind"] == 0
        assert after["updateAvailable"] is False
        assert after["canUpdate"] is False
        assert after["current"]["hash"] == published
        assert after["lastResult"]["ok"] is True


def test_dirty_work_tree_blocks_update() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        service = UpdateService(root=project.work)
        before = service.status()["current"]["hash"]
        project.publish("feature.txt")

        (project.work / "app.py").write_text("print('local')\n", encoding="utf-8")

        state = service.check()
        assert state["dirty"] is True
        assert state["behind"] == 1
        assert state["canUpdate"] is False
        assert state["blockedReason"] == "есть незакоммиченные изменения"

        outcome = service.apply(install_dependencies=False)
        _assert_outcome(outcome)
        assert outcome["ok"] is False
        assert "незакоммиченные" in outcome["message"]

        # Правки и история не тронуты: pull не выполнялся.
        assert (project.work / "app.py").read_text(encoding="utf-8") == "print('local')\n"
        assert not (project.work / "feature.txt").exists()
        assert service.status()["current"]["hash"] == before


def test_diverged_branch_is_not_merged() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        service = UpdateService(root=project.work)

        (project.work / "local.txt").write_text("локально\n", encoding="utf-8")
        _git(project.work, "add", "-A")
        _git(project.work, "commit", "-m", "Локальный коммит")
        project.publish("remote.txt")

        state = service.check()
        assert state["ahead"] == 1
        assert state["behind"] == 1
        assert state["canUpdate"] is False
        assert state["blockedReason"] == "ветки разошлись"

        outcome = service.apply(install_dependencies=False)
        _assert_outcome(outcome)
        assert outcome["ok"] is False
        assert "ручной разбор" in outcome["message"]
        assert not (project.work / "remote.txt").exists()


def test_nothing_to_apply_is_reported() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        service = UpdateService(root=project.work)

        outcome = service.apply(install_dependencies=False)
        _assert_outcome(outcome)
        assert outcome["ok"] is False
        assert outcome["pulled"] == 0
        assert outcome["restartRequired"] is False
        assert "Обновлений нет" in outcome["message"]
        assert service.status()["lastResult"]["ok"] is False


# ── Зависимости Python ────────────────────────────────────────────


def _marker_command(marker: Path) -> list[str]:
    return [
        sys.executable,
        "-c",
        "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('ok')",
        str(marker),
    ]


def test_requirements_change_runs_dependencies_command() -> None:
    with tempfile.TemporaryDirectory() as td:
        marker = Path(td) / "deps.called"
        project = _Project(Path(td) / "repo").create()
        service = UpdateService(
            root=project.work, dependencies_command=_marker_command(marker)
        )

        project.publish("feature.txt", change_requirements=True)
        service.check()

        outcome = service.apply()

        _assert_outcome(outcome)
        assert outcome["ok"] is True
        assert outcome["dependencies"] == "updated"
        assert marker.read_text(encoding="utf-8") == "ok"


def test_requirements_change_can_skip_dependencies() -> None:
    with tempfile.TemporaryDirectory() as td:
        marker = Path(td) / "deps.called"
        project = _Project(Path(td) / "repo").create()
        service = UpdateService(
            root=project.work, dependencies_command=_marker_command(marker)
        )

        project.publish("feature.txt", change_requirements=True)
        service.check()

        outcome = service.apply(install_dependencies=False)

        assert outcome["dependencies"] == "skipped"
        assert not marker.exists()
        assert "pip install -r requirements.txt" in outcome["message"]


def test_failed_dependencies_do_not_roll_back_code() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td) / "repo").create()
        service = UpdateService(
            root=project.work,
            dependencies_command=[sys.executable, "-c", "raise SystemExit(3)"],
        )

        project.publish("feature.txt", change_requirements=True)
        service.check()

        outcome = service.apply()

        _assert_outcome(outcome)
        assert outcome["ok"] is True  # код обновлён
        assert outcome["dependencies"] == "failed"
        assert "pip install -r requirements.txt" in outcome["message"]
        assert (project.work / "feature.txt").is_file()


# ── Ошибки окружения ──────────────────────────────────────────────


def test_not_a_git_repository_is_reported() -> None:
    with tempfile.TemporaryDirectory() as td:
        service = UpdateService(root=Path(td))
        state = service.status()

        _assert_status(state)
        assert state["available"] is False
        assert state["updateAvailable"] is False
        assert state["canUpdate"] is False
        assert ".git не найден" in state["error"]

        outcome = service.apply()
        _assert_outcome(outcome)
        assert outcome["ok"] is False
        assert outcome["pulled"] == 0
        assert outcome["restartRequired"] is False


def test_missing_git_binary_is_reported() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        service = UpdateService(root=project.work, git="git-которого-нет-9f3a")

        state = service.status()
        _assert_status(state)
        assert state["available"] is False
        assert "git не найден" in state["error"]
        assert state["canUpdate"] is False


def test_fetch_failure_is_reported_without_raising() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        _git(
            project.work,
            "remote",
            "set-url",
            "origin",
            str(Path(td) / "нет-такого-репозитория"),
        )

        service = UpdateService(root=project.work)
        state = service.check()

        _assert_status(state)
        assert state["available"] is True
        assert state["error"] is not None
        assert "git fetch" in state["error"]
        assert state["canUpdate"] is False

        outcome = service.apply()
        _assert_outcome(outcome)
        assert outcome["ok"] is False


def test_remote_url_credentials_are_redacted() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        _git(
            project.work,
            "remote",
            "set-url",
            "origin",
            "https://user:secret@example.com/oneleft12/Jarvis.git",
        )

        # __init__ читает локальное состояние (fetch не выполняется) — сети нет.
        state = UpdateService(root=project.work).status()

        _assert_status(state)
        assert state["remoteUrl"] == "https://example.com/oneleft12/Jarvis.git"
        assert "secret" not in state["remoteUrl"]


def test_parallel_operations_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        project = _Project(Path(td)).create()
        service = UpdateService(root=project.work)

        # Занимаем операционный замок так, как это делает идущая проверка.
        assert service._op_lock.acquire(blocking=False)
        try:
            for operation in (service.check, service.apply):
                try:
                    operation()
                except UpdateBusyError:
                    continue

                raise AssertionError(f"{operation.__name__} должен был упасть с UpdateBusyError")
        finally:
            service._op_lock.release()

        # После освобождения замка проверка снова работает.
        assert service.status()["checking"] is False
        assert service.check()["checkedAt"] is not None


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов обновления")


if __name__ == "__main__":
    main()
