"""Обновление ZERE из GitHub: проверка и fast-forward текущей ветки.

Механика (docs/UPDATE.md):

1. `git fetch` удалённой ветки — сеть трогаем только явной проверкой;
2. сравнение локального HEAD с `refs/remotes/<remote>/<branch>`:
   сколько коммитов позади (behind), впереди (ahead), список новых;
3. применение — `git pull --ff-only`, то есть только «перемотка вперёд».

Никаких слияний, rebase и force: если в рабочей копии есть незакоммиченные
правки или локальная ветка ушла вперёд, обновление отменяется с понятной
причиной — файлы пользователя не трогаются. Личные данные (config/,
zere.db, logs/, backups/, голосовые модели) в git не входят либо
игнорируются, поэтому pull их не перезаписывает.

Все команды запускаются без shell и без интерактивности: `git` не должен
спрашивать логин или парольную фразу ключа — иначе обновление «зависнет».
"""

from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from zere import paths
from zere.core.logging.log_service import log_error

# ── Константы ─────────────────────────────────────────────────────

_GIT_TIMEOUT = 60.0  # fetch, rev-parse, log
_PULL_TIMEOUT = 180.0  # сам pull (перемотка большого дерева)
_DEPS_TIMEOUT = 900.0  # pip install -r requirements.txt
_VERSION_TIMEOUT = 10.0
_MAX_COMMITS = 30

# Разделитель полей в --format: не встречается ни в именах, ни в темах
# коммитов, поэтому разбор не зависит от локали git.
_FIELD_SEP = "\x1f"
_COMMIT_FORMAT = _FIELD_SEP.join(["%H", "%h", "%an", "%aI", "%s"])

# Имя ветки из .git/HEAD попадает в аргументы git и в refspec — пускаем
# только безопасный алфавит (без пробелов, кавычек и ведущего дефиса).
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")

DEPENDENCIES_NOT_NEEDED = "not-needed"
DEPENDENCIES_UPDATED = "updated"
DEPENDENCIES_SKIPPED = "skipped"
DEPENDENCIES_FAILED = "failed"


class UpdateBusyError(RuntimeError):
    """Проверка или обновление уже выполняется (второй запрос — 409)."""


@dataclass(frozen=True)
class _CommandResult:
    """Результат внешней команды: код, потоки и ошибка запуска."""

    code: int
    stdout: str
    stderr: str
    error: str

    @property
    def ok(self) -> bool:
        return self.error == "" and self.code == 0

    @property
    def message(self) -> str:
        """Первая содержательная строка stderr — для сообщения пользователю."""
        text = self.stderr.strip() or self.stdout.strip() or self.error
        return text.splitlines()[0].strip() if text else ""


def _git_environment() -> dict[str, str]:
    """Окружение git: без интерактива и без пагинатора.

    `GIT_TERMINAL_PROMPT=0` запрещает спрашивать логин/пароль в терминале,
    `BatchMode=yes` — парольную фразу SSH-ключа (по умолчанию; свой
    `GIT_SSH_COMMAND` пользователя уважаем), `LC_ALL=C` — стабильный вывод.
    """
    env = dict(os.environ)
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    env["LC_ALL"] = "C"
    return env


def _redact_url(url: str) -> str:
    """Убирает логин/токен из URL удалённого репозитория.

    URL может содержать `https://user:token@host/...` — в панель и логи
    такое уходить не должно.
    """
    scheme_sep = url.find("://")
    if scheme_sep == -1:
        return url

    authority_start = scheme_sep + 3
    authority_end = len(url)
    for separator in ("/", "?"):
        index = url.find(separator, authority_start)
        if index != -1:
            authority_end = min(authority_end, index)

    authority = url[authority_start:authority_end]
    if "@" not in authority:
        return url

    return url[:authority_start] + authority.split("@", 1)[1] + url[authority_end:]


def _parse_commit(line: str) -> Optional[dict[str, str]]:
    fields = line.split(_FIELD_SEP)
    if len(fields) != 5:
        return None

    full, short, author, date, subject = fields
    return {
        "hash": full,
        "short": short,
        "subject": subject,
        "author": author,
        "date": date,
    }


class UpdateService:
    """Проверка и применение обновлений текущей ветки из origin.

    Экземпляр держит кэш последнего состояния: `status()` не ходит в сеть,
    сеть трогают только `check()` (git fetch) и `apply()` (fetch + pull).
    Операции сериализованы: параллельный запрос получает `UpdateBusyError`.
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        *,
        edition: str = "python",
        remote: Optional[str] = None,
        git: str = "git",
        timeout: float = _GIT_TIMEOUT,
        max_commits: int = _MAX_COMMITS,
        dependencies_command: Optional[Sequence[str]] = None,
    ) -> None:
        self._root = Path(root) if root is not None else paths.PROJECT_ROOT
        self._edition = edition
        self._remote = remote
        self._git = git
        self._timeout = timeout
        self._max_commits = max_commits
        self._deps_command = (
            list(dependencies_command) if dependencies_command is not None else None
        )

        self._state_lock = threading.RLock()
        self._op_lock = threading.Lock()
        self._state: dict[str, Any] = self._empty_state()

        # Локальное состояние (ветка, коммит, грязная копия) читается сразу:
        # панель показывает его, даже если сеть ещё не отвечала.
        self._inspect(fetch=False)

    # ── Публичный API ─────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Последнее известное состояние — без обращения к git и сети."""
        with self._state_lock:
            return copy.deepcopy(self._state)

    def check(self) -> dict[str, Any]:
        """Проверка обновлений: git fetch + сравнение с удалённой веткой."""
        if not self._op_lock.acquire(blocking=False):
            raise UpdateBusyError("Проверка или обновление уже выполняется.")

        try:
            self._set(checking=True)
            self._inspect(fetch=True)
        finally:
            self._set(checking=False)
            self._op_lock.release()

        return self.status()

    def apply(self, *, install_dependencies: bool = True) -> dict[str, Any]:
        """Применение обновления: `git pull --ff-only` текущей ветки.

        Возвращает результат операции (UpdateOutcome): `ok=False` — не
        ошибка запроса, а отказ с причиной (нет обновлений, грязная копия,
        расхождение веток, сбой pull).
        """
        if not self._op_lock.acquire(blocking=False):
            raise UpdateBusyError("Проверка или обновление уже выполняется.")

        try:
            self._set(applying=True)
            self._inspect(fetch=True)
            state = self.status()

            if state["current"] is None:
                return self._outcome(
                    False,
                    state["error"] or "Не удалось определить текущий коммит.",
                )

            if not state["updateAvailable"]:
                return self._outcome(
                    False,
                    state["error"]
                    or f"Обновлений нет: ветка {state['branch']} совпадает с "
                    f"{state['remote']}.",
                )

            if state["dirty"]:
                return self._outcome(
                    False,
                    "В рабочей копии есть незакоммиченные изменения — "
                    "обновление отменено, файлы не тронуты.",
                )

            if state["ahead"] > 0:
                return self._outcome(
                    False,
                    f"Локальная ветка ушла вперёд {state['remote']}/"
                    f"{state['branch']} — нужен ручной разбор (git status).",
                )

            from_hash = state["current"]["hash"]
            pulled = int(state["behind"])

            result = self._run(
                ["pull", "--ff-only", state["remote"], state["branch"]],
                timeout=_PULL_TIMEOUT,
            )
            if not result.ok:
                return self._outcome(
                    False,
                    "git pull не удался: "
                    + (result.message or "неизвестная ошибка pull"),
                )

            changed = self._changed_files(from_hash)
            dependencies = DEPENDENCIES_NOT_NEEDED
            if "requirements.txt" in changed:
                if install_dependencies:
                    dependencies = self._install_dependencies()
                else:
                    dependencies = DEPENDENCIES_SKIPPED

            # Локальные refs уже обновлены pull/fetch — сеть не нужна.
            self._inspect(fetch=False)

            message = f"Обновление применено: {pulled} коммитов."
            if dependencies == DEPENDENCIES_FAILED:
                message += (
                    " Зависимости обновить не удалось — выполните вручную: "
                    "pip install -r requirements.txt."
                )
            elif dependencies == DEPENDENCIES_SKIPPED:
                message += " Не забудьте: pip install -r requirements.txt."
            elif dependencies == DEPENDENCIES_UPDATED:
                message += " Зависимости Python обновлены."

            return self._outcome(
                True,
                message,
                from_hash=from_hash,
                pulled=pulled,
                dependencies=dependencies,
            )
        finally:
            self._set(applying=False)
            self._op_lock.release()

    # ── Состояние ─────────────────────────────────────────────────

    def _empty_state(self) -> dict[str, Any]:
        return {
            "edition": self._edition,
            "available": False,
            "branch": "unknown",
            "remote": "origin",
            "remoteUrl": None,
            "current": None,
            "target": None,
            "behind": 0,
            "ahead": 0,
            "commits": [],
            "dirty": False,
            "updateAvailable": False,
            "canUpdate": False,
            "blockedReason": None,
            "checking": False,
            "applying": False,
            "checkedAt": None,
            "error": None,
            "lastResult": None,
        }

    def _set(self, **fields: Any) -> None:
        with self._state_lock:
            self._state.update(fields)

    def _replace(self, state: dict[str, Any]) -> None:
        """Заменяет состояние, сохраняя флаги выполняющихся операций."""
        with self._state_lock:
            state["checking"] = self._state["checking"]
            state["applying"] = self._state["applying"]
            state["lastResult"] = self._state["lastResult"]
            self._state = state

    def _outcome(
        self,
        ok: bool,
        message: str,
        *,
        from_hash: Optional[str] = None,
        pulled: int = 0,
        dependencies: str = DEPENDENCIES_NOT_NEEDED,
    ) -> dict[str, Any]:
        state = self.status()
        current = state["current"]
        outcome = {
            "ok": ok,
            "message": message,
            "fromHash": from_hash,
            "toHash": current["hash"] if current else None,
            "pulled": pulled,
            "dependencies": dependencies,
            "restartRequired": ok and pulled > 0,
            "finishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self._set(lastResult=outcome)
        return outcome

    # ── Инспекция репозитория ─────────────────────────────────────

    def _inspect(self, *, fetch: bool) -> None:
        """Собирает состояние репозитория. Исключения наружу не уходят."""
        state = self._empty_state()
        state["checkedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")

        try:
            error, blocked = self._inspect_repository(state, fetch=fetch)
        except Exception as ex:  # noqa: BLE001 — панель не должна падать
            error, blocked = f"Сбой проверки обновлений: {ex}", "сбой проверки"

        state["error"] = error
        state["blockedReason"] = blocked
        state["updateAvailable"] = state["behind"] > 0
        state["canUpdate"] = (
            state["available"]
            and state["updateAvailable"]
            and not state["dirty"]
            and state["ahead"] == 0
            and error is None
        )
        self._replace(state)

    def _inspect_repository(
        self, state: dict[str, Any], *, fetch: bool
    ) -> tuple[Optional[str], Optional[str]]:
        """Заполняет state; возвращает (ошибка, причина блокировки)."""
        if not (self._root / ".git").exists():
            return (
                "Обновление через git недоступно: .git не найден "
                "(установка без репозитория).",
                "нет git-репозитория",
            )

        version = self._run(["--version"], timeout=_VERSION_TIMEOUT)
        if not version.ok:
            return (
                "git не найден: " + (version.message or "проверьте PATH"),
                "нет git",
            )

        branch = self._current_branch()
        if branch is None:
            return ("Не удалось определить текущую ветку.", "нет ветки")
        if branch == "HEAD" or not _BRANCH_RE.match(branch):
            return (
                f"Ветка «{branch}» не поддерживается (detached HEAD?) — "
                "обновление только для именованной ветки.",
                "отсоединённый HEAD",
            )

        state["branch"] = branch
        state["available"] = True
        state["current"] = self._commit("HEAD")

        dirty = self._run_text(
            ["status", "--porcelain", "--untracked-files=no"]
        )
        state["dirty"] = bool(dirty)

        remote = self._pick_remote()
        if remote is None:
            return (
                "У репозитория нет удалённого origin — тянуть обновления неоткуда.",
                "нет удалённого репозитория",
            )

        state["remote"] = remote
        state["remoteUrl"] = self._remote_url(remote)

        if fetch:
            refspec = f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}"
            fetched = self._run(
                ["fetch", "--quiet", remote, refspec], timeout=self._timeout
            )
            if not fetched.ok:
                return (
                    "Нет связи с GitHub (git fetch): "
                    + (fetched.message or "неизвестная ошибка"),
                    "git fetch не удался",
                )

        target_ref = f"refs/remotes/{remote}/{branch}"
        target = self._commit(target_ref)
        if target is None:
            return (
                f"Ветка {remote}/{branch} не найдена на удалённом репозитории.",
                "нет удалённой ветки",
            )

        state["target"] = target
        state["behind"] = self._count(f"HEAD..{target_ref}")
        state["ahead"] = self._count(f"{target_ref}..HEAD")
        state["commits"] = self._commits(f"HEAD..{target_ref}")

        # Причины отказа, не мешающие самой проверке: их показывает панель.
        if state["behind"] > 0 and state["dirty"]:
            return (None, "есть незакоммиченные изменения")
        if state["behind"] > 0 and state["ahead"] > 0:
            return (None, "ветки разошлись")

        return (None, None)

    # ── Команды git ───────────────────────────────────────────────

    def _run(
        self, args: Sequence[str], *, timeout: float, git: bool = True
    ) -> _CommandResult:
        command = [self._git, *args] if git else list(args)

        try:
            completed = subprocess.run(
                command,
                cwd=str(self._root),
                env=_git_environment() if git else dict(os.environ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _CommandResult(-1, "", "", f"таймаут {timeout:.0f} с")
        except OSError as ex:
            return _CommandResult(-1, "", "", str(ex))

        return _CommandResult(
            completed.returncode,
            completed.stdout.decode("utf-8", "replace"),
            completed.stderr.decode("utf-8", "replace"),
            "",
        )

    def _run_text(self, args: Sequence[str], *, timeout: Optional[float] = None) -> str:
        result = self._run(args, timeout=timeout or self._timeout)
        return result.stdout.strip() if result.ok else ""

    def _current_branch(self) -> Optional[str]:
        return self._run_text(["rev-parse", "--abbrev-ref", "HEAD"]) or None

    def _pick_remote(self) -> Optional[str]:
        remotes = [
            line.strip()
            for line in self._run_text(["remote"]).splitlines()
            if line.strip()
        ]
        if self._remote is not None and self._remote in remotes:
            return self._remote
        if "origin" in remotes:
            return "origin"
        return remotes[0] if remotes else None

    def _remote_url(self, remote: str) -> Optional[str]:
        url = self._run_text(["remote", "get-url", remote])
        return _redact_url(url) if url else None

    def _commit(self, ref: str) -> Optional[dict[str, str]]:
        text = self._run_text(["log", "-1", f"--format={_COMMIT_FORMAT}", ref])
        if not text:
            return None
        return _parse_commit(text.splitlines()[0])

    def _count(self, revision_range: str) -> int:
        text = self._run_text(["rev-list", "--count", revision_range])
        try:
            return int(text)
        except ValueError:
            return 0

    def _commits(self, revision_range: str) -> list[dict[str, str]]:
        text = self._run_text(
            [
                "log",
                f"--max-count={self._max_commits}",
                f"--format={_COMMIT_FORMAT}",
                revision_range,
            ]
        )

        commits: list[dict[str, str]] = []
        for line in text.splitlines():
            parsed = _parse_commit(line)
            if parsed is not None:
                commits.append(parsed)
        return commits

    def _changed_files(self, from_hash: str) -> list[str]:
        text = self._run_text(["diff", "--name-only", from_hash, "HEAD"])
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _install_dependencies(self) -> str:
        command = self._deps_command or [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            "requirements.txt",
        ]

        result = self._run(command, timeout=_DEPS_TIMEOUT, git=False)

        if result.ok:
            return DEPENDENCIES_UPDATED

        log_error(
            "UpdateService",
            "pip install -r requirements.txt: " + (result.message or "сбой"),
        )
        return DEPENDENCIES_FAILED
