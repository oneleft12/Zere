"""Тесты обработчиков команд: память, история, процессы, файлы, громкость, игры, Windows.

Ключевые сценарии взяты из реальных фраз пользователя. Опасные действия
(питание, завершение процессов, удаление файлов) не выполняются по-настоящему:
сервисы подменяются фейками, а `SafeActionManager._start` — перехватчиком.

До этих тестов весь конвейер обработчиков имел покрытие 0 %: панельные тесты
подменяют engine, поэтому память, файлы, процессы и громкость не исполнялись
ни разу.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import pytest

# pycaw — Windows-only (COM). На Linux модуль не импортируется, а обработчик
# громкости — чистый код поверх сервиса. Подставляем пустую заглушку только
# если настоящий пакет недоступен; импорт VolumeHandler происходит ниже.
try:  # pragma: no cover - ветка исполняется в зависимости от платформы
    import pycaw.pycaw  # noqa: F401
except Exception:  # noqa: BLE001 - ImportError и OSError загрузки COM
    _pycaw = types.ModuleType("pycaw")
    _pycaw.__path__ = []  # type: ignore[attr-defined]
    _inner = types.ModuleType("pycaw.pycaw")
    _inner.AudioUtilities = object  # type: ignore[attr-defined]
    _pycaw.pycaw = _inner  # type: ignore[attr-defined]
    sys.modules.setdefault("pycaw", _pycaw)
    sys.modules.setdefault("pycaw.pycaw", _inner)

from zere import paths  # noqa: E402
from zere.core.handlers.conversation_handler import ConversationHandler  # noqa: E402
from zere.core.handlers.file_handler import FileHandler  # noqa: E402
from zere.core.handlers.game_handler import GameHandler  # noqa: E402
from zere.core.handlers.handler_pipeline import HandlerPipeline  # noqa: E402
from zere.core.handlers.memory_handler import MemoryHandler  # noqa: E402
from zere.core.handlers.memory_query_handler import MemoryQueryHandler  # noqa: E402
from zere.core.handlers.process_handler import ProcessHandler  # noqa: E402
from zere.core.handlers.volume_handler import VolumeHandler  # noqa: E402
from zere.core.handlers.windows_handler import WindowsHandler  # noqa: E402
from zere.memory.database.conversation_repository import ConversationRepository  # noqa: E402
from zere.memory.database.memory_database import MemoryDatabase  # noqa: E402
from zere.memory.database.memory_repository import MemoryRepository  # noqa: E402
from zere.tools.files.file_manager import FileManager  # noqa: E402
from zere.tools.gaming.models.game_stat import GameStat  # noqa: E402
from zere.tools.windows import safe_action_manager as safemod  # noqa: E402
from zere.tools.windows.safe_action_manager import SafeActionManager  # noqa: E402

# ── Общие фейки ──────────────────────────────────────────────────────


class FakeProcessService:
    def __init__(self) -> None:
        self.killed: list[str] = []

    def kill(self, name: str) -> bool:
        self.killed.append(name)
        return True


class FakeFileManager:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_file(self, name: str) -> bool:
        self.deleted.append(name)
        return True


@pytest.fixture
def memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MemoryRepository:
    """Настоящая SQLite-память во временном каталоге."""
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    return MemoryRepository(MemoryDatabase())


@pytest.fixture
def conversations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConversationRepository:
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    return ConversationRepository(MemoryDatabase())


@pytest.fixture
def safe_actions(monkeypatch: pytest.MonkeyPatch) -> SafeActionManager:
    started: list[list[str]] = []
    monkeypatch.setattr(
        SafeActionManager,
        "_start",
        staticmethod(lambda argv: started.append(list(argv)) or True),
    )
    manager = SafeActionManager(FakeProcessService(), FakeFileManager())  # type: ignore[arg-type]
    manager.started = started  # type: ignore[attr-defined]
    return manager


# ── MemoryHandler ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    ["запомни имя Dan", "Запомни имя Dan", "не забудь купить хлеб", "что ты помнишь", "очисти память"],
)
def test_memory_can_handle(message: str, memory: MemoryRepository) -> None:
    assert MemoryHandler(memory).can_handle(message) is True


def test_memory_ignores_unrelated(memory: MemoryRepository) -> None:
    assert MemoryHandler(memory).can_handle("привет, как дела") is False


def test_remember_key_value(memory: MemoryRepository) -> None:
    handler = MemoryHandler(memory)

    assert handler.handle("запомни имя Dan") == "Запомнил: имя = Dan"
    assert memory.get("имя").value == "Dan"  # type: ignore[union-attr]


def test_remember_with_equals(memory: MemoryRepository) -> None:
    handler = MemoryHandler(memory)

    assert handler.handle("запомни проект = ZERE") == "Запомнил: проект = ZERE"
    assert memory.get("проект").value == "ZERE"  # type: ignore[union-attr]


def test_remember_strips_leading_possessive(memory: MemoryRepository) -> None:
    MemoryHandler(memory).handle("запомни моя машина Volvo")

    assert memory.get("машина").value == "Volvo"  # type: ignore[union-attr]


def test_remember_without_value_asks_for_example(memory: MemoryRepository) -> None:
    handler = MemoryHandler(memory)

    assert handler.handle("запомни") == "Укажите, что запомнить. Например: запомни имя Dan"
    assert handler.handle("запомни Dan") == "Например: запомни имя Dan"
    assert memory.get_all() == []


def test_show_empty_memory(memory: MemoryRepository) -> None:
    assert MemoryHandler(memory).handle("покажи память") == "Я пока ничего не запомнил."


def test_show_memory_lists_items(memory: MemoryRepository) -> None:
    memory.remember("имя", "Dan")
    memory.remember("проект", "ZERE")

    answer = MemoryHandler(memory).handle("покажи память")

    assert "Вот что я помню:" in answer
    assert "• имя = Dan" in answer
    assert "• проект = ZERE" in answer


def test_forget_existing_and_missing(memory: MemoryRepository) -> None:
    memory.remember("имя", "Dan")
    handler = MemoryHandler(memory)

    assert handler.handle("забудь имя") == "Я забыл информацию: имя."
    assert handler.handle("забудь имя") == "Я не нашёл запись «имя»."


def test_forget_without_key(memory: MemoryRepository) -> None:
    assert MemoryHandler(memory).handle("забудь") == "Укажите, что забыть. Например: забудь имя"


def test_clear_memory(memory: MemoryRepository) -> None:
    memory.remember("имя", "Dan")

    assert MemoryHandler(memory).handle("очисти память") == "Память полностью очищена."
    assert memory.get_all() == []


def test_update_memory(memory: MemoryRepository) -> None:
    handler = MemoryHandler(memory)

    assert handler.handle("обнови память проект = AI VOCALPLUS") == "Память обновлена: проект = AI VOCALPLUS"
    assert memory.get("проект").value == "AI VOCALPLUS"  # type: ignore[union-attr]

    assert handler.handle("обнови память проект") == "Например: обнови память проект = AI VOCALPLUS"


# ── MemoryQueryHandler ───────────────────────────────────────────────


def test_query_can_handle() -> None:
    assert MemoryQueryHandler(FakeMemoryRepo()).can_handle("как меня зовут") is True
    assert MemoryQueryHandler(FakeMemoryRepo()).can_handle("что такое гравитация") is True
    assert MemoryQueryHandler(FakeMemoryRepo()).can_handle("открой дискорд") is False


def test_query_name_and_project(memory: MemoryRepository) -> None:
    memory.remember("имя", "Dan")
    memory.remember("проект", "ZERE")
    handler = MemoryQueryHandler(memory)

    assert handler.handle("как меня зовут") == "Вас зовут Dan."
    assert handler.handle("какой у меня проект") == "Ваш проект называется ZERE."


def test_query_without_answer_passes_to_next_handler() -> None:
    handler = MemoryQueryHandler(FakeMemoryRepo())

    assert handler.handle("что такое гравитация") is None


def test_query_uses_memory_search() -> None:
    repo = FakeMemoryRepo()
    repo.search_results = [_Item("гравитация", "сила притяжения")]
    handler = MemoryQueryHandler(repo)

    assert handler.handle("что такое гравитация") == "Из памяти: гравитация = сила притяжения"


def test_query_all_memories() -> None:
    repo = FakeMemoryRepo()
    repo.items = [_Item("имя", "Dan")]

    assert "• имя = Dan" in MemoryQueryHandler(repo).handle("что ты знаешь обо мне")  # type: ignore[operator]
    assert MemoryQueryHandler(FakeMemoryRepo()).handle("что ты знаешь обо мне") == "Я пока ничего не запомнил."


# ── ConversationHandler ──────────────────────────────────────────────


def test_conversation_can_handle() -> None:
    assert ConversationHandler(FakeConversationRepo()).can_handle("покажи историю") is True
    assert ConversationHandler(FakeConversationRepo()).can_handle("очисти историю") is True
    assert ConversationHandler(FakeConversationRepo()).can_handle("привет") is False


def test_conversation_empty_and_show(conversations: ConversationRepository) -> None:
    handler = ConversationHandler(conversations)

    assert handler.handle("покажи историю") == "История пуста."

    conversations.save("привет", "здравствуйте")
    answer = handler.handle("покажи историю")

    assert "Вы: привет" in answer
    assert "ZERE: здравствуйте" in answer


def test_conversation_clear(conversations: ConversationRepository) -> None:
    conversations.save("a", "b")
    handler = ConversationHandler(conversations)

    assert handler.handle("очисти историю") == "История очищена."
    assert conversations.get_last(10) == []


# ── ProcessHandler ───────────────────────────────────────────────────


@dataclass
class ProcInfo:
    id: int
    name: str
    memory_mb: float


class FakeProcesses:
    def __init__(self) -> None:
        self.items = [ProcInfo(10, "chrome", 300.0), ProcInfo(11, "discord", 100.0)]
        self.exact: list[ProcInfo] = []
        self.killed: list[str] = []

    def get_processes(self) -> list[ProcInfo]:
        return list(self.items)

    def search(self, name: str) -> list[ProcInfo]:
        return [item for item in self.items if name.lower() in item.name.lower()]

    def search_exact(self, name: str) -> list[ProcInfo]:
        return list(self.exact)

    def kill(self, name: str) -> bool:
        self.killed.append(name)
        return True


def test_process_list(safe_actions: SafeActionManager) -> None:
    handler = ProcessHandler(FakeProcesses(), safe_actions)  # type: ignore[arg-type]

    answer = handler.handle("процессы")

    assert "Самые тяжёлые процессы:" in answer
    assert "• chrome — 300.0 MB" in answer


def test_process_search_found_and_missing(safe_actions: SafeActionManager) -> None:
    handler = ProcessHandler(FakeProcesses(), safe_actions)  # type: ignore[arg-type]

    assert "• chrome (PID 10) — 300.0 MB" in handler.handle("найди процесс chrom")
    assert handler.handle("найди процесс zzz") == "Процесс не найден."


def test_process_protected_is_refused(safe_actions: SafeActionManager) -> None:
    processes = FakeProcesses()
    handler = ProcessHandler(processes, safe_actions)  # type: ignore[arg-type]

    answer = handler.handle("закрой процесс svchost")

    assert "системный" in answer
    assert processes.killed == []
    assert safe_actions.confirm().value == "no_pending"


def test_process_kill_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    processes = FakeProcesses()
    processes.exact = [ProcInfo(42, "discord", 1.0)]
    monkeypatch.setattr(SafeActionManager, "_start", staticmethod(lambda argv: True))
    actions = SafeActionManager(processes, FakeFileManager())  # type: ignore[arg-type]
    handler = ProcessHandler(processes, actions)  # type: ignore[arg-type]

    answer = handler.handle("закрой процесс discord")

    assert "Завершить?" in answer
    assert "PID 42" in answer
    assert processes.killed == []

    actions.confirm()

    assert processes.killed == ["discord"]


def test_process_missing_explicit_and_implicit(safe_actions: SafeActionManager) -> None:
    handler = ProcessHandler(FakeProcesses(), safe_actions)  # type: ignore[arg-type]

    assert handler.handle("закрой процесс нет-такого") == "Процесс не найден."
    # «закрой дверь» — не процесс: вопрос уходит дальше, до LLM.
    assert handler.handle("закрой дверь") is None


def test_process_can_handle() -> None:
    handler = ProcessHandler(FakeProcesses(), SafeActionManager(FakeProcessService(), FakeFileManager()))  # type: ignore[arg-type]

    assert handler.can_handle("процессы") is True
    assert handler.can_handle("закрой процесс discord") is True
    assert handler.can_handle("привет") is False


# ── VolumeHandler ────────────────────────────────────────────────────


class FakeVolumeService:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[str, int]] = []

    def set_volume(self, value: int) -> bool:
        self.calls.append(("set", value))
        return self.ok

    def volume_up(self) -> bool:
        self.calls.append(("up", 0))
        return self.ok

    def volume_down(self) -> bool:
        self.calls.append(("down", 0))
        return self.ok

    def mute(self) -> bool:
        self.calls.append(("mute", 0))
        return self.ok

    def un_mute(self) -> bool:
        self.calls.append(("unmute", 0))
        return self.ok


def test_volume_set_by_percent() -> None:
    service = FakeVolumeService()
    handler = VolumeHandler(service)  # type: ignore[arg-type]

    assert handler.handle("громкость 50") == "Громкость установлена на 50%."
    assert service.calls == [("set", 50)]


def test_volume_up_down_mute() -> None:
    service = FakeVolumeService()
    handler = VolumeHandler(service)  # type: ignore[arg-type]

    assert handler.handle("сделай громче") == "Громкость увеличена."
    assert handler.handle("сделай тише") == "Громкость уменьшена."
    assert handler.handle("выключи звук") == "Звук выключен."
    assert handler.handle("включи звук") == "Звук включён."
    assert [name for name, _ in service.calls] == ["up", "down", "mute", "unmute"]


def test_volume_failure_is_reported() -> None:
    handler = VolumeHandler(FakeVolumeService(ok=False))  # type: ignore[arg-type]

    assert handler.handle("громкость 50") == "Не удалось изменить громкость."
    assert handler.handle("сделай громче") == "Не удалось увеличить громкость."
    assert handler.handle("выключи звук") == "Не удалось выключить звук."


def test_volume_can_handle() -> None:
    handler = VolumeHandler(FakeVolumeService())  # type: ignore[arg-type]

    assert handler.can_handle("громкость 30") is True
    assert handler.can_handle("погромче") is True
    assert handler.can_handle("открой дискорд") is False


# ── FileHandler ──────────────────────────────────────────────────────


@pytest.fixture
def file_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "zere.tools.files.folder_search._windows_known_folder", lambda guid: None
    )
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    files = FileManager()
    monkeypatch.setattr(
        SafeActionManager,
        "_start",
        staticmethod(lambda argv: True),
    )
    actions = SafeActionManager(FakeProcessService(), files)  # type: ignore[arg-type]
    return FileHandler(files, actions), files, desktop, actions


def test_file_create_folder_file_and_delete(file_setup) -> None:
    handler, files, desktop, actions = file_setup

    assert handler.handle("создай папку test") == 'Папка "test" создана.'
    assert (desktop / "test").is_dir()

    assert handler.handle("создай файл note.txt") == 'Файл "note.txt" создан.'
    assert (desktop / "note.txt").is_file()

    answer = handler.handle("удали файл note.txt")
    assert "Удалить файл" in answer
    assert "действует 60 секунд" in answer

    from zere.tools.windows.safe_action_manager import ConfirmOutcome

    assert actions.confirm() is ConfirmOutcome.EXECUTED
    assert not (desktop / "note.txt").exists()


def test_file_delete_missing(file_setup) -> None:
    handler, _, _, actions = file_setup

    assert handler.handle("удали файл missing.txt") == 'Файл "missing.txt" не найден.'
    assert actions.confirm().value == "no_pending"


def test_delete_last_file(file_setup) -> None:
    handler, _, desktop, actions = file_setup

    assert handler.handle("удали его") == "Я не создавал файлов в этой сессии — нечего удалять."

    handler.handle("создай файл last.txt")
    assert "last.txt" in handler.handle("удали его")

    actions.confirm()

    assert not (desktop / "last.txt").exists()


def test_delete_last_file_already_gone(file_setup) -> None:
    handler, _, desktop, _ = file_setup
    handler.handle("создай файл gone.txt")
    (desktop / "gone.txt").unlink()

    assert "уже не существует" in handler.handle("удали его")


def test_file_find(file_setup) -> None:
    handler, _, desktop, _ = file_setup
    (desktop / "отчёт.md").write_text("x", encoding="utf-8")

    assert "отчёт.md" in handler.handle("найди файл отчёт")


def test_file_find_folder(file_setup) -> None:
    handler, _, desktop, _ = file_setup
    (desktop / "Проекты").mkdir()

    answer = handler.handle("найди папку проекты")

    assert "Найденные папки" in answer
    assert "Проекты" in answer


def test_file_can_handle() -> None:
    handler = FileHandler(FileManager(), SafeActionManager(FakeProcessService(), FakeFileManager()))  # type: ignore[arg-type]

    assert handler.can_handle("создай папку x") is True
    assert handler.can_handle("удали файл x") is True
    assert handler.can_handle("найди папку проекты") is True
    assert handler.can_handle("открой папку проекты") is True
    assert handler.can_handle("привет") is False


# ── GameHandler ──────────────────────────────────────────────────────


class FakeGuardian:
    def __init__(self, games: list[str]) -> None:
        self.games = games

    def get_running_games(self) -> list[str]:
        return list(self.games)


class FakeTracker:
    def __init__(self, stats: list[GameStat]) -> None:
        self.stats = stats
        self.reset_calls = 0

    def today_stats(self) -> list[GameStat]:
        return list(self.stats)

    def reset_today(self) -> None:
        self.reset_calls += 1
        self.stats = []


def test_games_running() -> None:
    handler = GameHandler(FakeGuardian(["Dota 2"]), FakeTracker([]))  # type: ignore[arg-type]

    assert handler.handle("игры") == "Сейчас запущены игры:\n\n• Dota 2"
    assert GameHandler(FakeGuardian([]), FakeTracker([])).handle("игры") == "Сейчас игры не запущены."  # type: ignore[arg-type]


def test_game_statistics_formatting() -> None:
    stats = [GameStat(game_name="Dota 2", today_time=timedelta(hours=1, minutes=2, seconds=3))]
    handler = GameHandler(FakeGuardian([]), FakeTracker(stats))  # type: ignore[arg-type]

    assert handler.handle("игровая статистика") == "Сегодня вы играли:\n\n• Dota 2 — 01:02:03"


def test_game_statistics_empty_and_reset() -> None:
    tracker = FakeTracker([])
    handler = GameHandler(FakeGuardian([]), tracker)  # type: ignore[arg-type]

    assert handler.handle("игровая статистика") == "Сегодня игр не обнаружено."
    assert handler.handle("сбросить игровую статистику") == "Игровая статистика очищена."
    assert tracker.reset_calls == 1


def test_game_can_handle() -> None:
    handler = GameHandler(FakeGuardian([]), FakeTracker([]))  # type: ignore[arg-type]

    assert handler.can_handle("игры") is True
    assert handler.can_handle("игровая статистика") is True
    assert handler.can_handle("что такое игра") is False


# ── WindowsHandler ───────────────────────────────────────────────────


@dataclass
class FakeApp:
    name: str
    executable_path: str = ""


class FakeLauncher:
    def __init__(self) -> None:
        self.apps = {"discord": FakeApp("Discord"), "steam": FakeApp("Steam")}
        self.launched: list[str] = []
        self.rebuilt = 0

    def get_installed_applications(self) -> dict[str, FakeApp]:
        return dict(self.apps)

    def launch(self, name: str) -> bool:
        self.launched.append(name)
        return name.lower() in self.apps or name.lower() in ("калькулятор", "блокнот")

    def rebuild_index(self) -> None:
        self.rebuilt += 1


def test_windows_open_app() -> None:
    launcher = FakeLauncher()
    handler = WindowsHandler(launcher, SafeActionManager(FakeProcessService(), FakeFileManager()))  # type: ignore[arg-type]

    assert handler.handle("открой discord") == "Открываю discord."
    assert launcher.launched == ["discord"]


def test_windows_open_missing_app() -> None:
    handler = WindowsHandler(FakeLauncher(), SafeActionManager(FakeProcessService(), FakeFileManager()))  # type: ignore[arg-type]

    assert handler.handle("открой нет-такого") == "Не удалось найти приложение «нет-такого»."


class FakeFolderFiles:
    """Мини-замена FileManager для «открой загрузки»."""

    def __init__(self) -> None:
        self.opened: list[str] = []

    def can_open_folder(self, query: str) -> bool:
        return query.lower() in ("загрузки", "документы")

    def open_folder(self, query: str) -> str:
        self.opened.append(query)
        return f"Открываю папку «{query}»."


def test_windows_opens_known_folder_after_missing_app() -> None:
    files = FakeFolderFiles()
    handler = WindowsHandler(  # type: ignore[arg-type]
        FakeLauncher(),
        SafeActionManager(FakeProcessService(), FakeFileManager()),
        files,
    )

    assert handler.handle("открой загрузки") == "Открываю папку «загрузки»."
    assert files.opened == ["загрузки"]


def test_windows_unknown_app_does_not_scan_folders() -> None:
    files = FakeFolderFiles()
    handler = WindowsHandler(  # type: ignore[arg-type]
        FakeLauncher(),
        SafeActionManager(FakeProcessService(), FakeFileManager()),
        files,
    )

    assert handler.handle("открой нет-такого") == "Не удалось найти приложение «нет-такого»."
    assert files.opened == []


def test_windows_index_and_count() -> None:
    launcher = FakeLauncher()
    handler = WindowsHandler(launcher, SafeActionManager(FakeProcessService(), FakeFileManager()))  # type: ignore[arg-type]

    assert handler.handle("сколько приложений") == "В индексе 2 приложений."
    assert handler.handle("обнови индекс") == "Индекс приложений успешно обновлён."
    assert launcher.rebuilt == 1


def test_windows_find_app() -> None:
    handler = WindowsHandler(FakeLauncher(), SafeActionManager(FakeProcessService(), FakeFileManager()))  # type: ignore[arg-type]

    assert handler.handle("найди discord") == "• Discord"
    assert handler.handle("найди zzz") == "Ничего не найдено."


def test_windows_does_not_steal_file_search() -> None:
    handler = WindowsHandler(FakeLauncher(), SafeActionManager(FakeProcessService(), FakeFileManager()))  # type: ignore[arg-type]

    assert handler.can_handle("найди файл отчёт") is False
    assert handler.can_handle("найди discord") is True


def test_windows_power_requires_confirmation(safe_actions: SafeActionManager) -> None:
    handler = WindowsHandler(FakeLauncher(), safe_actions)

    assert "Вы уверены, что хотите выключить компьютер?" in handler.handle("выключи компьютер")
    assert safe_actions.started == []  # type: ignore[attr-defined]

    assert handler.handle("да") == "Выполняю команду."
    assert safe_actions.started[0][:2] == ["shutdown", "/s"]  # type: ignore[attr-defined]


def test_windows_negated_power_is_not_a_command() -> None:
    handler = WindowsHandler(FakeLauncher(), SafeActionManager(FakeProcessService(), FakeFileManager()))  # type: ignore[arg-type]

    assert handler.can_handle("не выключай компьютер") is False
    assert handler.can_handle("нет, перезагружай сам") is False


def test_windows_no_pending_confirmation(safe_actions: SafeActionManager) -> None:
    handler = WindowsHandler(FakeLauncher(), safe_actions)

    assert handler.handle("да") == "Нет команды для подтверждения."


def test_windows_expired_confirmation(safe_actions: SafeActionManager, monkeypatch: pytest.MonkeyPatch) -> None:
    handler = WindowsHandler(FakeLauncher(), safe_actions)
    clock = [100.0]
    monkeypatch.setattr(safemod.time, "monotonic", lambda: clock[0])

    handler.handle("выключи компьютер")
    clock[0] += SafeActionManager.CONFIRM_TTL_SECONDS + 1

    assert "Время подтверждения истекло" in handler.handle("да")
    assert safe_actions.started == []  # type: ignore[attr-defined]


def test_windows_cancel(safe_actions: SafeActionManager) -> None:
    handler = WindowsHandler(FakeLauncher(), safe_actions)

    handler.handle("выключи компьютер")

    assert handler.handle("нет") == "Команда отменена."
    assert safe_actions.confirm().value == "no_pending"


# ── HandlerPipeline ──────────────────────────────────────────────────


class StubHandler:
    def __init__(self, handles: bool, answer: Optional[str] = None, boom: bool = False) -> None:
        self._handles = handles
        self._answer = answer
        self._boom = boom
        self.called = 0

    def can_handle(self, message: str) -> bool:
        return self._handles

    def handle(self, message: str) -> Optional[str]:
        self.called += 1
        if self._boom:
            raise RuntimeError("сбой обработчика")
        return self._answer


def test_pipeline_returns_first_answer() -> None:
    first = StubHandler(True, "первый")
    second = StubHandler(True, "второй")
    pipeline = HandlerPipeline([first, second])

    assert pipeline.handle("x") == "первый"
    assert first.called == 1
    assert second.called == 0


def test_pipeline_none_falls_through() -> None:
    first = StubHandler(True, None)
    second = StubHandler(True, "второй")
    pipeline = HandlerPipeline([first, second])

    assert pipeline.handle("x") == "второй"
    assert first.called == 1 and second.called == 1


def test_pipeline_error_does_not_stop_others() -> None:
    broken = StubHandler(True, "не дойдёт", boom=True)
    good = StubHandler(True, "ответ")
    pipeline = HandlerPipeline([broken, good])

    assert pipeline.handle("x") == "ответ"


def test_pipeline_no_handler_returns_none() -> None:
    assert HandlerPipeline([StubHandler(False), StubHandler(False, "нет")]).handle("x") is None


def test_pipeline_contains_and_copy() -> None:
    handler = StubHandler(True, "ok")
    pipeline = HandlerPipeline([handler])

    assert pipeline.contains(StubHandler) is True
    assert pipeline.handlers == [handler]

    pipeline.handlers.append(StubHandler(False))
    assert len(pipeline.handlers) == 1


# ── Вспомогательные фейки памяти/истории ─────────────────────────────


@dataclass
class _Item:
    key: str
    value: str


class FakeMemoryRepo:
    def __init__(self) -> None:
        self.items: list[_Item] = []
        self.search_results: list[_Item] = []

    def get_all(self) -> list[_Item]:
        return list(self.items)

    def get(self, key: str) -> Optional[_Item]:
        for item in self.items:
            if item.key == key:
                return item
        return None

    def search(self, query: str) -> list[_Item]:
        return list(self.search_results)


class FakeConversationRepo:
    def get_last(self, count: int) -> list[Any]:
        return []

    def clear_history(self) -> None:
        pass
