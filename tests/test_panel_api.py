"""Контрактные тесты локальной панели ZERE против docs/api/openapi.yaml.

Этап 1 «API-ядро» (docs/GUI_DEVELOPMENT_PLAN.md §7): контракт один на обе
реализации, тесты проверяют ответы именно по спеке (required/enum/type).

Запуск:
- `python3 tests/test_panel_api.py` — без зависимостей (только pyyaml);
- `pytest tests/ -q` — в CI (функции test_* без аргументов);
- `ZERE_PANEL_EXTERNAL=1` — против уже запущенной панели в отдельном
  процессе (CI-джоба C#: `dotnet run --project ZERE.App -- --panel`),
  тогда контракт проверяется на второй реализации тем же набором тестов.
"""

from __future__ import annotations

import copy
import enum
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import quote

import yaml

# Корень репозитория — чтобы `python3 tests/test_panel_api.py` работал
# без установки пакета (pytest это делает сам, но дубликат не вредит).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere import paths as paths_module
from zere.ai.ai_service import AiService, MESSAGE_NOT_CONFIGURED
from zere.ai.ai_settings import DEFAULT_LOCAL_MODEL, AiSettings
from zere.ai.ollama_url_resolver import OllamaUrlResolver
from zere.api.server import PanelServer
from zere.core.update.updater import UpdateBusyError
from zere.core.configuration.zere_config import ZereConfig
from zere.core.plugins.interfaces.plugin import PluginType
from zere.core.plugins.plugin_config import PluginConfig
from zere.memory.models.conversation import Conversation
from zere.memory.models.memory_item import MemoryItem
# app_info — только dataclass: в отличие от ApplicationLauncher, чей импорт
# тянет winreg (сканеры), этот модуль работает на любой платформе.
from zere.tools.applications.indexing.app_info import AppInfo
# Фейковый HTTP-слой: проверка ключа и локальной модели не ходит в сеть.
from tests.fake_http import (
    FakeSession,
    chat_response,
    error_response,
    models_response,
    ollama_pull_response,
    ollama_tags_response,
)

SPEC: dict[str, Any] = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.yaml").read_text(
        encoding="utf-8"
    )
)

TOKEN = "b" * 64
_UNSET = object()

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = os.environ.get("ZERE_PANEL_EXTERNAL") == "1"
EXTERNAL_PORT = int(os.environ.get("ZERE_PANEL_PORT", "8080"))

# Необратимые операции (очистка истории) против ВНЕШНЕЙ панели запускаются
# только по явному флагу: там настоящая zere.db, а локальная база — фейк.
DESTRUCTIVE = os.environ.get("ZERE_PANEL_DESTRUCTIVE") == "1"

# Фактические стили встроенной личности (Custom исключён — урок «6 → 5»)
ACTUAL_STYLES = ["Friendly", "Formal", "Sarcastic", "Professional", "Casual"]


class _Style(enum.Enum):
    Friendly = "Friendly"
    Formal = "Formal"
    Sarcastic = "Sarcastic"
    Professional = "Professional"
    Casual = "Casual"
    Custom = "Custom"


class FakePersonality:
    """Подмена PersonalityPlugin: стиль меняется только через set_style."""

    id = "personality"

    def __init__(self) -> None:
        self.style = _Style.Friendly

    def get_available_styles(self) -> list[str]:
        return list(ACTUAL_STYLES)

    def set_style(self, style_name: str) -> None:
        self.style = _Style[style_name]

    def set_initial_style(self, style_name: str) -> None:
        self.style = _Style[style_name]


class FakePlugin:
    """Подмена IPlugin: поля как у встроенного плагина личности."""

    def __init__(self) -> None:
        self.id = "personality"
        self.name = "Личность ZERE"
        self.description = "Встроенные стили общения ассистента"
        self.version = "1.0.0"
        self.author = "ZERE"
        self.type = PluginType.Personality


#: Браузеры для подмены плагина: (id, подпись, есть на машине, подсказка).
_MCP_BROWSERS = (
    ("edge", "Microsoft Edge", True, ""),
    ("chrome", "Google Chrome", False, "Chrome не найден."),
    ("opera-gx", "Opera GX", False, "Opera GX не найден."),
    ("chromium", "Chromium (от Playwright)", False, "Chromium не установлен."),
)

_MCP_CHANNELS = {"edge": "msedge", "chrome": "chrome", "chromium": "chromium"}


class FakeMcpPlugin:
    """Подмена MCP-плагина (браузер): состояние и выбор без процессов.

    Реальный плагин поднимает `npx @playwright/mcp` — в контрактных тестах
    это недопустимо, поэтому проверяется только контракт: состояние для
    панели, выбор браузера и тексты отказа.
    """

    def __init__(
        self,
        server_id: str = "playwright",
        *,
        browser: str = "edge",
        accept: tuple[str, ...] = ("edge", "opera-gx"),
        can_select: bool = True,
    ) -> None:
        self.server_id = server_id
        self._browser = browser
        self._accept = accept
        self.selected: list[str] = []

        if not can_select:
            # Сборка плагина без выбора браузера: маршрут обязан ответить 404,
            # а не упасть на отсутствующем методе.
            self.select_browser = None  # type: ignore[assignment]

    def panel_status(self) -> dict[str, Any]:
        state = {
            "id": "obsidian-mcp" if self.server_id == "obsidian" else "playwright-mcp",
            "serverId": self.server_id,
            "enabled": True,
            "running": False,
            "command": "npx -y @playwright/mcp@0.0.83",
            "server": {},
            "lastError": "",
        }

        if self.server_id == "playwright":
            state["browser"] = self.browser_state()

        return state

    def browser_state(self) -> dict[str, Any]:
        labels = {browser_id: label for browser_id, label, _, _ in _MCP_BROWSERS}

        return {
            "current": self._browser,
            "currentLabel": labels[self._browser],
            "channel": _MCP_CHANNELS.get(self._browser, ""),
            "path": "",
            "options": [
                {"id": browser_id, "label": label, "available": available, "hint": hint}
                for browser_id, label, available, hint in _MCP_BROWSERS
            ],
        }

    def select_browser(self, name: str) -> tuple[bool, str]:
        self.selected.append(name)

        for browser_id, label, _available, hint in _MCP_BROWSERS:
            if browser_id != name:
                continue

            if name in self._accept:
                self._browser = name
                return True, f"Браузер переключён на {label}."

            # Отказ формулирует сам плагин — панель показывает текст как есть.
            return False, hint or f"Браузер «{label}» недоступен."

        return (
            False,
            f"Не знаю браузер «{name}». Доступны: edge, chrome, opera-gx, chromium.",
        )


class FakePluginManager:
    def __init__(self) -> None:
        self.active_personality = FakePersonality()
        self.plugins: list[Any] = [FakePlugin()]
        self.command_handlers: list[Any] = []


class FakeEngine:
    """Подмена ZereEngine: детерминированный ответ без LLM."""

    def __init__(self) -> None:
        self.processed: list[str] = []
        self.plugin_manager = FakePluginManager()

    def process(self, text: str) -> str:
        self.processed.append(text)
        return f"ответ: {text}"


def _sql_like(haystack: str, pattern: str) -> bool:
    """Эмуляция SQL LIKE (репозитории обеих реализаций ищут через LIKE)."""
    rx = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern.lower())
    return re.fullmatch(rx, haystack.lower(), re.DOTALL) is not None


class FakeMemory:
    """In-memory замена MemoryRepository: upsert по ключу, порядок Category/Key.

    Повторяет реальные семантики (register: case-insensitive ключи,
    ON CONFLICT по lower(Key)), но без SQLite — тесты идут в tmp-окружении.
    """

    def __init__(self) -> None:
        self._rows: dict[int, MemoryItem] = {}
        self._next_id = 1

    def remember(self, key: str, value: str, category: str = "User") -> None:
        normalized = key.lower()

        for row in self._rows.values():
            if row.key.lower() == normalized:
                row.value = value
                row.category = category
                return

        now = datetime.now()
        # Реальный репозиторий хранит ключ в нижнем регистре (key.ToLower()).
        self._rows[self._next_id] = MemoryItem(self._next_id, key.lower(), value, category, now)
        self._next_id += 1

    def find(self, key: str) -> Optional[MemoryItem]:
        normalized = key.lower()
        for row in self._rows.values():
            if row.key.lower() == normalized:
                return row
        return None

    def get_all(self) -> list[MemoryItem]:
        return sorted(
            self._rows.values(),
            key=lambda row: (row.category, row.key),
        )

    def search(self, query: str) -> list[MemoryItem]:
        pattern = f"%{query}%"
        return [row for row in self.get_all() if _sql_like(row.key, pattern) or _sql_like(row.value, pattern)]

    def forget(self, key: str) -> bool:
        found = self.find(key)
        if found is None:
            return False
        del self._rows[found.id]
        return True

    def forget_by_id(self, memory_id: int) -> bool:
        if memory_id not in self._rows:
            return False
        del self._rows[memory_id]
        return True


class FakeConversationRepository:
    """Порт-замена ConversationRepository: get_page/count/clear_history."""

    def __init__(self) -> None:
        self._rows: list[Conversation] = []
        self._next_id = 1

    def seed(self, user_message: str, zere_response: str) -> int:
        """Добавляет запись, как сделал бы реальный ConversationHandler."""
        now = datetime.now()
        row = Conversation(self._next_id, user_message, zere_response, now)
        self._rows.append(row)
        self._next_id += 1
        return row.id

    def count(self, search: str = "") -> int:
        return len(self._filtered(search))

    def get_page(self, limit: int, offset: int, search: str = "") -> list[Conversation]:
        ordered = sorted(self._filtered(search), key=lambda row: row.id, reverse=True)
        return ordered[offset:offset + limit]

    def _filtered(self, search: str) -> list[Conversation]:
        if not search:
            return list(self._rows)

        pattern = f"%{search}%"
        return [
            row
            for row in self._rows
            if _sql_like(row.user_message, pattern) or _sql_like(row.zere_response, pattern)
        ]

    def clear_history(self) -> None:
        self._rows.clear()


class FakeProcessInfo:
    """Порт-замена ProcessInfo (id/name/memory_mb/responding)."""

    def __init__(self, pid: int, name: str, memory_mb: float, responding: bool = True) -> None:
        self.id = pid
        self.name = name
        self.memory_mb = memory_mb
        self.responding = responding


class FakeProcessService:
    """Порт-замена ProcessService: get_processes/search/kill_pid/is_protected."""

    PROTECTED_NAMES = frozenset(
        {"system", "idle", "registry", "smss", "csrss", "wininit", "winlogon",
         "services", "lsass", "svchost"}
    )

    def __init__(self) -> None:
        self._rows: dict[int, FakeProcessInfo] = {
            4: FakeProcessInfo(4, "System", 1.5),
            100: FakeProcessInfo(100, "chrome", 220.0),
            101: FakeProcessInfo(101, "chrome", 180.0),
            200: FakeProcessInfo(200, "notepad", 42.0),
        }
        self.killed: list[int] = []

    @classmethod
    def is_protected(cls, name: str) -> bool:
        normalized = name[:-4] if name.lower().endswith(".exe") else name
        return bool(normalized) and normalized.lower() in cls.PROTECTED_NAMES

    def get_processes(self) -> list[FakeProcessInfo]:
        return sorted(self._rows.values(), key=lambda row: row.memory_mb, reverse=True)

    def search(self, name: str) -> list[FakeProcessInfo]:
        needle = name.lower()
        return [row for row in self.get_processes() if needle in row.name.lower()]

    def kill_pid(self, pid: int) -> bool:
        if pid not in self._rows:
            return False
        if self.is_protected(self._rows[pid].name):
            return False
        del self._rows[pid]
        self.killed.append(pid)
        return True


class FakeConfirmOutcome:
    """Значения ConfirmOutcome.value: executed / no_pending / expired / failed."""

    def __init__(self, value: str) -> None:
        self.value = value


class FakeSafeActionManager:
    """Порт-замена SafeActionManager: request/confirm с тем же сроком TTL."""

    TTL_SECONDS = 60

    def __init__(self) -> None:
        self._pending: Optional[str] = None
        self._requested_at = 0.0
        self.requests: list[str] = []

    @property
    def last_result(self) -> Optional[str]:
        """Ответ обработчика у настоящего менеджера; здесь выполнять нечего."""
        return None

    def set_command_executor(self, executor: Any) -> None:
        """Команды роутера интентов в fake-менеджере не выполняются."""
        self.executor = executor

    def request(self, action: Any, target: str = "") -> None:
        name = getattr(action, "name", str(action))
        self._pending = name
        self._requested_at = time.monotonic()
        self.requests.append(name)

    def confirm(self) -> FakeConfirmOutcome:
        if self._pending is None:
            return FakeConfirmOutcome("no_pending")

        if time.monotonic() - self._requested_at > self.TTL_SECONDS:
            self._pending = None
            return FakeConfirmOutcome("expired")

        self._pending = None
        # Настоящее выполнение не эмулируем: тесты ничего не выключают.
        return FakeConfirmOutcome("executed")


class FakeApplicationLauncher:
    """Порт-замена ApplicationLauncher: get_installed_applications/rebuild_index."""

    def __init__(self) -> None:
        self.rebuilds = 0
        self._apps: dict[str, AppInfo] = {
            "discord": AppInfo(
                name="Discord",
                executable_path=r"C:\Users\me\AppData\Local\Discord\Discord.exe",
                source="StartMenu",
                category="Communication",
                priority=80,
                aliases=["дискорд"],
                last_seen=datetime(2026, 1, 15, 9, 30, 0),
            ),
            "notepad++": AppInfo(
                name="Notepad++",
                executable_path=r"C:\Program Files\Notepad++\notepad++.exe",
                source="AppPaths",
                category="Utility",
                priority=95,
                aliases=[],
                last_seen=datetime(2026, 1, 15, 9, 31, 0),
            ),
            "calc": AppInfo(
                name="Calc",
                executable_path="calc.exe",
                source="Registry",
                category="Utility",
                priority=50,
                aliases=["калькулятор"],
                last_seen=datetime(2026, 1, 15, 9, 32, 0),
            ),
        }

    def get_installed_applications(self) -> dict[str, AppInfo]:
        return dict(self._apps)

    def rebuild_index(self) -> None:
        # Сканеры не гоняем: в фейке индекс неизменяем, важно лишь число вызовов.
        self.rebuilds += 1


# ── Инфраструктура ────────────────────────────────────────────────


class _ExternalPanel:
    """Панель в отдельном процессе (CI: dotnet run --panel).

    engine недоступен из тестового процесса, поэтому точные тексты ответов
    здесь не проверяются — только форма контракта.
    """

    def __init__(self, port: int, token: str) -> None:
        self.port = port
        self.token = token
        self.engine: Any = None
        # Настоящий PanelServer вне процесса недоступен: засеивание фейками
        # (history/memory) в этом режиме невозможно — тесты ветвятся на EXTERNAL.
        self.memory: Any = None
        self.conversation: Any = None


def _wait_external_panel(timeout: float = 120.0) -> _ExternalPanel:
    token_file = REPO_ROOT / "config" / "panel.token"
    deadline = time.monotonic() + timeout

    while not token_file.exists():
        if time.monotonic() > deadline:
            raise AssertionError("внешняя панель не создала config/panel.token")
        time.sleep(1)

    panel = _ExternalPanel(EXTERNAL_PORT, token_file.read_text(encoding="utf-8").strip())

    while True:
        try:
            status, _, _ = call(panel, "GET", "/api/health")
            if status == 200:
                return panel
        except OSError:
            pass  # сервер ещё не принял сокет

        if time.monotonic() > deadline:
            raise AssertionError("внешняя панель не ответила за отведённое время")
        time.sleep(1)


class FakeVoiceConfig:
    """Как ZERE.Voice.VoiceConfig: volume читается на каждое воспроизведение."""

    def __init__(self) -> None:
        self.volume = 1.0
        # Дефолты реального VoiceConfig: wake word включён, слово «зере».
        self.wake_word_enabled = True
        self.wake_word = "зере"
        self.command_silence_ms = 1500


class FakeVoiceManager:
    """Порт-замена C# VoiceManager: capabilities честные для C#-стороны.

    record_voice_reference есть → recordReference=True (как в C#);
    TTS/STT «установлены» — локально проверяем happy-path,
    в CI (EXTERNAL, --panel) голос не инициализирован → 503.

    Голосовой режим (POST /api/voice/mode): listen_results — сценарий
    распознавания (pop, затем микрофон «молчит»), listen_commands —
    сценарий команд после wake word, wake_hits — сколько раз
    wait_for_wake_word вернёт «триггер сработал» до ожидания отмены.
    """

    def __init__(self) -> None:
        self.config = FakeVoiceConfig()
        self.is_tts_available = True
        self.is_voice_available = True
        self.spoken: list[str] = []
        self.stops = 0
        self.listen_results: list[str] = ["привет из микрофона"]
        self.listen_commands: list[str] = []
        self.wake_hits = 0
        self.wake_armed = False
        self.wake_disabled = 0

    def record_voice_reference(self) -> str:
        # C# пишет <cwd>/voice/reference.wav; файл не создаём — контракт
        # панели проверяет только путь и его сохранение в конфигурации.
        return str(Path(tempfile.gettempdir()) / "zere_fake_reference.wav")

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def speak_background(self, text: str) -> None:
        # Панель озвучивает ответ чата фоном: тесту важно, что текст ответа
        # дошёл до TTS именно через фоновый путь (без блокировки SSE).
        self.spoken.append(text)

    def stop_speaking(self) -> None:
        # Озвучка в фейке мгновенная — останавливать нечего, но вызов считаем:
        # по нему проверяется обрыв речи при выключении голосового вывода.
        self.stops += 1

    def listen(self) -> str:
        if self.listen_results:
            return self.listen_results.pop(0)
        time.sleep(0.05)  # имитация блокирующей записи — не горячий цикл
        return ""

    # ── Wake word (путь голосового режима с триггером) ──────────

    def enable_wake_word(self) -> "FakeVoiceManager":
        self.wake_armed = True
        return self

    def disable_wake_word(self) -> None:
        if self.wake_armed:
            self.wake_disabled += 1
        self.wake_armed = False

    def wait_for_wake_word(self, cancel_event: Any = None) -> bool:
        if self.wake_hits > 0:
            self.wake_hits -= 1
            return True

        # Спим до отмены: возврат False раннер трактует как «ждём дальше».
        if cancel_event is not None:
            cancel_event.wait(10)
            return False
        time.sleep(0.05)
        return False

    def listen_command(self) -> str:
        if self.listen_commands:
            return self.listen_commands.pop(0)
        time.sleep(0.05)
        return ""


class FakeUpdater:
    """Порт-замена UpdateService: контракт /api/update без git и сети.

    Обновление проверяется на настоящем репозитории только в
    tests/test_updater.py; здесь важно другое — форма ответов по
    docs/api/openapi.yaml, кэширующий GET и автопроверка при старте.
    """

    #: Форма коммита — как у настоящего сервиса (git %H/%h/%an/%aI/%s).
    _CURRENT = {
        "hash": "a" * 40,
        "short": "aaaaaaa",
        "subject": "Текущий коммит (фейк)",
        "author": "ZERE",
        "date": "2026-10-06T10:00:00+05:00",
    }
    _TARGET = {
        "hash": "b" * 40,
        "short": "bbbbbbb",
        "subject": "Новый коммит (фейк)",
        "author": "ZERE",
        "date": "2026-10-06T11:00:00+05:00",
    }

    def __init__(self, *, update_available: bool = False) -> None:
        self.checks = 0
        self.applies = 0
        self.calls: list[str] = []
        self.busy = False
        self.available = True
        # По умолчанию ветка актуальна (как у обычной установки):
        # тесты «есть обновление» включают флаг явно, E2E — через конструктор.
        self.update_available = update_available
        self.behind = 1
        self.dirty = False
        self.error: Optional[str] = None
        self.blocked_reason: Optional[str] = None
        self.install_dependencies: Optional[bool] = None
        self.last_result: Optional[dict[str, Any]] = None

    # ── Контракт UpdateService ───────────────────────────────────

    def status(self) -> dict[str, Any]:
        return copy.deepcopy(self._status())

    def check(self) -> dict[str, Any]:
        if self.busy:
            raise UpdateBusyError("Проверка или обновление уже выполняется.")

        self.checks += 1
        self.calls.append("check")
        return self.status()

    def apply(self, *, install_dependencies: bool = True) -> dict[str, Any]:
        if self.busy:
            raise UpdateBusyError("Проверка или обновление уже выполняется.")

        self.applies += 1
        self.calls.append("apply")
        self.install_dependencies = install_dependencies

        if not self.update_available:
            self.last_result = self._outcome(ok=False)
            return copy.deepcopy(self.last_result)

        self.update_available = False
        self.last_result = self._outcome(ok=True)
        return copy.deepcopy(self.last_result)

    # ── Данные ───────────────────────────────────────────────────

    def _status(self) -> dict[str, Any]:
        commits = [copy.deepcopy(self._TARGET)] if self.update_available else []

        return {
            "edition": "python",
            "available": self.available,
            "branch": "python-port",
            "remote": "origin",
            "remoteUrl": "git@github.com:oneleft12/Jarvis.git",
            "current": copy.deepcopy(self._CURRENT),
            "target": copy.deepcopy(self._TARGET),
            "behind": self.behind if self.update_available else 0,
            "ahead": 0,
            "commits": commits,
            "dirty": self.dirty,
            "updateAvailable": self.update_available,
            "canUpdate": self.available and self.update_available and not self.busy,
            "blockedReason": self.blocked_reason,
            "checking": False,
            "applying": self.busy,
            "checkedAt": "2026-10-06T12:00:00+05:00",
            "error": self.error,
            "lastResult": copy.deepcopy(self.last_result),
        }

    def _outcome(self, *, ok: bool) -> dict[str, Any]:
        pulled = self.behind if ok else 0

        return {
            "ok": ok,
            "message": (
                f"Обновление применено: {pulled} коммитов."
                if ok
                else "Обновлений нет: ветка python-port совпадает с origin."
            ),
            "fromHash": self._CURRENT["hash"] if ok else None,
            "toHash": self._TARGET["hash"] if ok else self._CURRENT["hash"],
            "pulled": pulled,
            "dependencies": "updated" if ok else "not-needed",
            "restartRequired": ok,
            "finishedAt": "2026-10-06T12:05:00+05:00",
        }


@contextmanager
def running_panel(
    ai_session: Optional[Any] = None,
    mcp_plugins: Optional[list[Any]] = None,
) -> Iterator[tuple[Any, Path]]:
    """Панель на эфемерном порту, config.json — во временной папке.

    В режиме ZERE_PANEL_EXTERNAL — уже запущенная панель в отдельном
    процессе, конфигурация берётся из config/ репозитория.

    ai_session — подмена HTTP-слоя сервиса ИИ: проверка облачного ключа и
    локальной модели не должна ходить в сеть (по умолчанию — «нет ключа,
    локальный сервер не запущен»).

    mcp_plugins — подмена MCP-плагинов (браузер/заметки) в списке плагинов
    движка: реальные поднимают `npx`, чего контрактные тесты не делают.
    """
    if EXTERNAL:
        yield _wait_external_panel(), REPO_ROOT / "config"
        return

    # Контрактные тесты не ходят в сеть: проба Ollama в /api/health
    # (OllamaUrlResolver.resolve) резолвит host.docker.internal и на машине
    # без Docker занимает7–17 с (DNS), из-за чего клиентский таймаут15 с
    # обрушивал прогон. Стаб возвращает «недоступен» — детерминированно.
    original_resolve = OllamaUrlResolver.resolve
    OllamaUrlResolver.resolve = staticmethod(lambda: None)

    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            original_config_path = paths_module.config_path
            original_plugins_config_path = paths_module.plugins_config_path
            paths_module.config_path = lambda: tmp / "config.json"
            paths_module.plugins_config_path = lambda: tmp / "plugins.json"
            try:
                engine = FakeEngine()

                if mcp_plugins:
                    engine.plugin_manager.plugins.extend(mcp_plugins)

                panel = PanelServer(
                    engine=engine,
                    config=ZereConfig(),
                    memory=FakeMemory(),
                    conversation=FakeConversationRepository(),
                    plugin_config=PluginConfig(),
                    process_service=FakeProcessService(),
                    safe_actions=FakeSafeActionManager(),
                    app_launcher=FakeApplicationLauncher(),
                    voice=FakeVoiceManager(),
                    # Обновление из GitHub: фейк — тесты не ходят в сеть
                    # и не трогают рабочую копию репозитория.
                    updater=FakeUpdater(),
                    # ИИ: реальный AiService с фейковым HTTP — проверяются
                    # и код, и контракт (без сети и без запущенной Ollama).
                    ai=AiService(session=ai_session if ai_session is not None else FakeSession()),
                    token=TOKEN,
                    port=0,
                )
                panel.start()
                try:
                    yield panel, tmp
                finally:
                    panel.stop()
            finally:
                paths_module.config_path = original_config_path
                paths_module.plugins_config_path = original_plugins_config_path
    finally:
        OllamaUrlResolver.resolve = original_resolve


def call(
    panel: Any,
    method: str,
    path: str,
    *,
    host: Any = _UNSET,
    origin: Optional[str] = None,
    token: Any = _UNSET,
    body: Any = _UNSET,
) -> tuple[int, bytes, dict[str, str]]:
    if token is _UNSET:
        token = panel.token

    conn = http.client.HTTPConnection("127.0.0.1", panel.port, timeout=15)
    headers: dict[str, str] = {}
    if host is not _UNSET:
        headers["Host"] = host
    if origin is not None:
        headers["Origin"] = origin
    if token is not None:
        headers["X-ZERE-Token"] = token

    data: Optional[bytes] = None
    if body is not _UNSET:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    # URL-кодирование: клиенты шлют UTF-8 query percent-encoded,
    # http.client требует ASCII-строку.
    conn.request(method, quote(path, safe="/?=&%"), body=data, headers=headers)
    response = conn.getresponse()
    raw = response.read()
    response_headers = {k.lower(): v for k, v in response.getheaders()}
    conn.close()
    return response.status, raw, response_headers


def error_payload(raw: bytes) -> dict[str, str]:
    return json.loads(raw.decode("utf-8"))


def parse_sse(raw: bytes) -> list[tuple[str, dict[str, Any]]]:
    text = raw.decode("utf-8")
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        assert name is not None and data is not None, f"битое SSE-событие: {block!r}"
        events.append((name, data))
    return events


def assert_schema(schema: dict[str, Any], value: Any, path: str = "$") -> None:
    """Минимальный валидатор JSON Schema: type/required/enum/additionalProperties."""
    # OpenAPI 3.0: nullable: true → допускаем null до проверок типа.
    if value is None and schema.get("nullable") is True:
        return

    if "enum" in schema:
        assert value in schema["enum"], f"{path}: {value!r} не входит в {schema['enum']}"

    stype = schema.get("type")

    if stype == "object":
        assert isinstance(value, dict), f"{path}: ожидался объект, получен {value!r}"
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            assert key in value, f"{path}: отсутствует обязательный ключ «{key}»"
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            assert not extra, f"{path}: лишние ключи {sorted(extra)}"
        for key, subschema in properties.items():
            if key in value:
                assert_schema(subschema, value[key], f"{path}.{key}")
    elif stype == "boolean":
        assert isinstance(value, bool), f"{path}: ожидался bool, получен {value!r}"
    elif stype == "integer":
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{path}: ожидался int, получен {value!r}"
        )
    elif stype == "number":
        assert isinstance(value, (int, float)) and not isinstance(value, bool), (
            f"{path}: ожидалось число, получено {value!r}"
        )
    elif stype == "array":
        assert isinstance(value, list), f"{path}: ожидался список, получен {value!r}"
        if "items" in schema:
            for index, element in enumerate(value):
                assert_schema(schema["items"], element, f"{path}[{index}]")
        if "minItems" in schema:
            assert len(value) >= schema["minItems"], f"{path}: длина {len(value)} < minItems"
    elif stype == "string":
        assert isinstance(value, str), f"{path}: ожидалась строка, получена {value!r}"

    if stype in ("integer", "number"):
        if "minimum" in schema:
            assert value >= schema["minimum"], f"{path}: {value} < {schema['minimum']}"
        if "maximum" in schema:
            assert value <= schema["maximum"], f"{path}: {value} > {schema['maximum']}"


def schema(name: str) -> dict[str, Any]:
    return SPEC["components"]["schemas"][name]


# ── Безопасность ──────────────────────────────────────────────────


def test_without_token_is_unauthorized() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/health", token=None)
        assert status == 401
        payload = error_payload(raw)
        assert_schema(schema("Error"), payload)
        assert payload["code"] == "UNAUTHORIZED"


def test_wrong_token_is_unauthorized() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/config", token="f" * 64)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_host_rebinding_is_rejected() -> None:
    """Гейт этапа 1: панель не отвечает на Host: evil.local."""
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/health", host="evil.local")

        if EXTERNAL and status == 400:
            # C# (http.sys) может отклонить запрос ещё до приложения —
            # главное, что ответа 200 нет: панель не отвечает на evil.local.
            return

        assert status == 403
        assert error_payload(raw)["code"] == "FORBIDDEN_HOST"


def test_foreign_origin_is_rejected() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/health", origin="http://evil.local")
        assert status == 403
        assert error_payload(raw)["code"] == "FORBIDDEN_ORIGIN"


def test_own_origin_is_allowed() -> None:
    with running_panel() as (panel, _):
        status, _, _ = call(
            panel, "GET", "/api/health", origin=f"http://127.0.0.1:{panel.port}"
        )
        assert status == 200


# ── /api/health ───────────────────────────────────────────────────


def test_health_matches_spec() -> None:
    with running_panel() as (panel, _):
        status, raw, headers = call(panel, "GET", "/api/health")
        assert status == 200
        assert headers.get("content-type", "").startswith("application/json")
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("Health"), payload)


# ── /api/config ───────────────────────────────────────────────────


def test_config_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/config")
        assert status == 200
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("Config"), payload)
        # Единая схема Stage 0: голос уже читается в C#, движок TTS — в Python.
        assert payload["voiceVolume"] == 0.5
        assert payload["ttsEngine"] == "pocket"


def test_config_post_persists_atomically() -> None:
    with running_panel() as (panel, tmp):
        _, raw, _ = call(panel, "GET", "/api/config")
        payload = json.loads(raw.decode("utf-8"))
        payload["voiceVolume"] = 0.8
        payload["model"] = "qwen3.5:4b"

        status, raw_post, _ = call(panel, "POST", "/api/config", body=payload)
        assert status == 200, raw_post
        assert_schema(schema("Config"), json.loads(raw_post.decode("utf-8")))

        # Атомарно сохранено в config.json (camelCase), читается обратно
        written = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
        assert written["voiceVolume"] == 0.8
        assert written["model"] == "qwen3.5:4b"
        assert "voice_volume" not in written  # формат — camelCase, не snake_case

        reloaded = ZereConfig.load()
        assert reloaded.voice_volume == 0.8
        assert reloaded.model == "qwen3.5:4b"


def test_tts_engine_accepts_silero_in_voice_and_config() -> None:
    """Русский движок Silero — легальное значение ttsEngine (панель + конфиг)."""
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/voice", body={"ttsEngine": "silero"})
        assert status == 200, raw
        applied = json.loads(raw.decode("utf-8"))
        assert applied["ttsEngine"] == "silero"
        assert applied["appliedOnRestart"] is True

        # Единая схема конфига: тот же движок проходит и через POST /api/config
        _, raw_cfg, _ = call(panel, "GET", "/api/config")
        payload = json.loads(raw_cfg.decode("utf-8"))
        payload["ttsEngine"] = "silero"

        status, raw_post, _ = call(panel, "POST", "/api/config", body=payload)
        assert status == 200, raw_post
        assert json.loads(raw_post.decode("utf-8"))["ttsEngine"] == "silero"

        # Незнакомый движок по-прежнему отклоняется, а в тексте есть список
        status, raw_bad, _ = call(panel, "POST", "/api/voice", body={"ttsEngine": "piper"})
        assert status == 400, raw_bad
        assert "silero" in error_payload(raw_bad)["message"]


def test_config_post_rejects_unknown_key() -> None:
    with running_panel() as (panel, _):
        _, raw, _ = call(panel, "GET", "/api/config")
        payload = json.loads(raw.decode("utf-8"))
        payload["debugMode"] = True  # мёртвый ключ удалён на этапе 0

        status, raw_post, _ = call(panel, "POST", "/api/config", body=payload)
        assert status == 400
        error = error_payload(raw_post)
        assert_schema(schema("Error"), error)
        assert error["code"] == "VALIDATION_ERROR"
        assert "debugMode" in error["message"]


def test_config_post_rejects_wrong_type() -> None:
    with running_panel() as (panel, _):
        _, raw, _ = call(panel, "GET", "/api/config")
        payload = json.loads(raw.decode("utf-8"))
        payload["voiceVolume"] = "loud"

        status, raw_post, _ = call(panel, "POST", "/api/config", body=payload)
        assert status == 400
        assert error_payload(raw_post)["code"] == "VALIDATION_ERROR"


def test_config_post_rejects_missing_key() -> None:
    with running_panel() as (panel, _):
        _, raw, _ = call(panel, "GET", "/api/config")
        payload = json.loads(raw.decode("utf-8"))
        del payload["autoMemory"]

        status, raw_post, _ = call(panel, "POST", "/api/config", body=payload)
        assert status == 400
        assert "autoMemory" in error_payload(raw_post)["message"]


def test_config_post_rejects_bad_json() -> None:
    with running_panel() as (panel, _):
        conn = http.client.HTTPConnection("127.0.0.1", panel.port, timeout=15)
        conn.request(
            "POST",
            "/api/config",
            body=b"{not json",
            headers={"X-ZERE-Token": panel.token, "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        assert response.status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"


# ── /api/chat/stream ──────────────────────────────────────────────


def test_chat_stream_emits_token_and_done() -> None:
    with running_panel() as (panel, _):
        status, raw, headers = call(panel, "GET", "/api/chat/stream?text=привет")
        assert status == 200
        assert headers.get("content-type", "").startswith("text/event-stream")

        events = parse_sse(raw)
        assert [name for name, _ in events] == ["token", "done"]

        if EXTERNAL:
            # Внешняя панель — настоящий engine: в CI без Ollama текст ответа
            # может быть сообщением об ошибке. Контрактна форма событий.
            assert isinstance(events[0][1].get("text"), str)
            assert isinstance(events[1][1].get("answer"), str)
        else:
            assert events[0][1] == {"text": "ответ: привет"}
            assert events[1][1] == {"answer": "ответ: привет"}
            assert panel.engine.processed == ["привет"]


def test_chat_stream_requires_text() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/chat/stream")
        assert status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"

        status, raw, _ = call(panel, "GET", "/api/chat/stream?text=")
        assert status == 400


def test_chat_stream_rejects_too_long_text() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/chat/stream?text=" + "а" * 4001)
        assert status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"


def test_chat_stream_speaks_answer_only_when_voice_enabled() -> None:
    """Панель читает ответ голосом — но только при включённом голосовом выводе."""
    if EXTERNAL:
        # У внешней панели нет доступа к фейковому голосу и конфигу в памяти.
        return

    with running_panel() as (panel, _):
        panel.config.voice_enabled = False
        call(panel, "GET", "/api/chat/stream?text=привет")
        assert panel.voice.spoken == [], "голосовой вывод выключен — озвучки нет"

        panel.config.voice_enabled = True
        status, raw, _ = call(panel, "GET", "/api/chat/stream?text=привет")
        assert status == 200
        assert parse_sse(raw)[1][1] == {"answer": "ответ: привет"}
        assert panel.voice.spoken == ["ответ: привет"], "озвучивается ответ движка"


def test_voice_post_stops_speaking_when_voice_disabled() -> None:
    """Выключение голосового вывода обрывает уже начатую озвучку."""
    if EXTERNAL:
        return

    with running_panel() as (panel, _):
        panel.config.voice_enabled = True
        before = panel.voice.stops

        status, raw, _ = call(panel, "POST", "/api/voice", body={"voiceEnabled": False})
        assert status == 200, raw
        assert json.loads(raw.decode("utf-8"))["voiceEnabled"] is False
        assert panel.voice.stops == before + 1, "речь должна обрываться сразу"


# ── Роутинг ───────────────────────────────────────────────────────


def test_unknown_route_is_normalized_404() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/nope")
        assert status == 404
        error = error_payload(raw)
        assert_schema(schema("Error"), error)
        assert error["code"] == "NOT_FOUND"


def test_wrong_method_is_405() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/health", body={})
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


# ── /api/personality (смена стиля с персистом — чинит P1-3) ───────


def test_personality_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/personality")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("Personality"), payload)
        assert payload["activeId"] == "personality"
        assert payload["activeStyle"] == "Friendly"
        # урок отчёта «6 стилей → 5»: список только фактический
        assert payload["styles"] == ACTUAL_STYLES
        assert "Custom" not in payload["styles"]


def test_personality_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/personality", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_personality_set_persists_style_across_restart() -> None:
    """Гейт этапа 2: смена стиля переживает рестарт (закрывает P1-3)."""
    with running_panel() as (panel, cfg_dir):
        status, raw, _ = call(panel, "POST", "/api/personality/set", body={"styleId": "Sarcastic"})
        assert status == 200, raw

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("Personality"), payload)
        assert payload["activeStyle"] == "Sarcastic"

        # GET отражает новое состояние
        _, raw_get, _ = call(panel, "GET", "/api/personality")
        assert json.loads(raw_get.decode("utf-8"))["activeStyle"] == "Sarcastic"

        # Персист: config/plugins.json (PascalCase — формат PluginConfig)
        saved = json.loads((cfg_dir / "plugins.json").read_text(encoding="utf-8"))
        assert saved["ActivePersonalityStyle"] == "Sarcastic"
        assert saved["ActivePersonalityId"] == "personality"

        # Рестарт: PluginConfig.load() + восстановление стиля при старте
        reloaded = PluginConfig.load()
        assert reloaded.ActivePersonalityStyle == "Sarcastic"

        restored = FakePersonality()
        restored.set_initial_style(reloaded.ActivePersonalityStyle)
        assert restored.style is _Style.Sarcastic


def test_personality_set_is_case_insensitive() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/personality/set", body={"styleId": "formal"})
        assert status == 200, raw
        # каноническое имя из списка стилей, а не присланное
        assert json.loads(raw.decode("utf-8"))["activeStyle"] == "Formal"


def test_personality_set_rejects_unknown_style() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/personality/set", body={"styleId": "Custom"})
        assert status == 400

        error = error_payload(raw)
        assert_schema(schema("Error"), error)
        assert error["code"] == "VALIDATION_ERROR"
        assert "Custom" in error["message"]


def test_personality_set_validation_errors() -> None:
    with running_panel() as (panel, _):
        # отсутствует styleId
        status, raw, _ = call(panel, "POST", "/api/personality/set", body={})
        assert status == 400
        assert "styleId" in error_payload(raw)["message"]

        # неверный тип
        status, raw, _ = call(panel, "POST", "/api/personality/set", body={"styleId": 42})
        assert status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"

        # лишний ключ
        status, raw, _ = call(
            panel, "POST", "/api/personality/set", body={"styleId": "Formal", "extra": 1}
        )
        assert status == 400
        assert "extra" in error_payload(raw)["message"]


# ── /api/history (этап 3 «Чат, История, Память») ─────────────────


def test_history_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        if not EXTERNAL:
            panel.conversation.seed("привет", "здравствуйте")
            panel.conversation.seed("как дела", "нормально")

        status, raw, _ = call(panel, "GET", "/api/history")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("HistoryPage"), payload)
        assert len(payload["items"]) <= 50  # limit по умолчанию
        assert payload["total"] >= len(payload["items"])

        for item in payload["items"]:
            assert_schema(schema("HistoryItem"), item)

        if not EXTERNAL:
            assert payload["total"] == 2
            # новые сверху
            assert [i["userMessage"] for i in payload["items"]] == ["как дела", "привет"]


def test_history_pagination() -> None:
    with running_panel() as (panel, _):
        if not EXTERNAL:
            for index in range(5):
                panel.conversation.seed(f"вопрос {index}", f"ответ {index}")

        status, raw, _ = call(panel, "GET", "/api/history?limit=2")
        assert status == 200
        first = json.loads(raw.decode("utf-8"))
        assert_schema(schema("HistoryPage"), first)
        assert len(first["items"]) <= 2
        total = first["total"]

        status, raw, _ = call(panel, "GET", f"/api/history?limit=2&offset=2")
        assert status == 200
        second = json.loads(raw.decode("utf-8"))
        assert len(second["items"]) <= 2
        assert second["total"] == total

        if not EXTERNAL:
            assert total == 5
            assert len(first["items"]) == 2
            assert len(second["items"]) == 2
            # страницы не пересекаются
            first_ids = {item["id"] for item in first["items"]}
            second_ids = {item["id"] for item in second["items"]}
            assert not first_ids & second_ids
            assert [i["userMessage"] for i in first["items"]] == ["вопрос 4", "вопрос 3"]
            assert [i["userMessage"] for i in second["items"]] == ["вопрос 2", "вопрос 1"]

            # последняя неполная страница
            _, raw_last, _ = call(panel, "GET", "/api/history?limit=2&offset=4")
            last = json.loads(raw_last.decode("utf-8"))
            assert len(last["items"]) == 1


def test_history_rejects_bad_params() -> None:
    with running_panel() as (panel, _):
        for query in ("limit=0", "limit=501", "limit=abc", "offset=-1", "offset=x"):
            status, raw, _ = call(panel, "GET", f"/api/history?{query}")
            assert status == 400, f"{query}: {status}"
            error = error_payload(raw)
            assert_schema(schema("Error"), error)
            assert error["code"] == "VALIDATION_ERROR"


def test_history_search_filters_and_counts() -> None:
    with running_panel() as (panel, _):
        if not EXTERNAL:
            panel.conversation.seed("какая погода в Париже", "солнечно")
            panel.conversation.seed("закрой дискорд", "закрываю")

        # поиск регистронезависимый — как lower(...) LIKE в репозиториях
        status, raw, _ = call(panel, "GET", "/api/history?search=Погода")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("HistoryPage"), payload)

        if not EXTERNAL:
            assert payload["total"] == 1
            assert payload["items"][0]["userMessage"] == "какая погода в Париже"

        # пустая выборка — честные нули, а не ошибка
        status, raw, _ = call(panel, "GET", "/api/history?search=" + quote("ъъъънет"))
        assert status == 200

        empty = json.loads(raw.decode("utf-8"))
        assert empty["items"] == []
        assert empty["total"] == 0


def test_history_search_rejects_too_long_query() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/history?search=" + "а" * 201)
        assert status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"


def test_history_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/history", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_history_wrong_method_is_405() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/history", body={})
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


def test_history_delete_requires_confirmation() -> None:
    """P0-3: необратимая очистка без подтверждения — всегда 400, ничего не стёрто."""
    with running_panel() as (panel, _):
        if not EXTERNAL:
            panel.conversation.seed("не трогай", "меня")

        for body in (
            {},
            {"confirm": "yes"},
            {"confirm": "delete"},
            {"confir": "DELETE"},
            {"confirm": "DELETE", "extra": 1},
        ):
            status, raw, _ = call(panel, "DELETE", "/api/history", body=body)
            assert status == 400, body
            error = error_payload(raw)
            assert_schema(schema("Error"), error)
            assert error["code"] == "VALIDATION_ERROR"

        # история не тронута
        _, raw, _ = call(panel, "GET", "/api/history")
        payload = json.loads(raw.decode("utf-8"))
        if not EXTERNAL:
            assert payload["total"] == 1
        else:
            assert payload["total"] >= 0


def test_history_delete_clears_all() -> None:
    """Гейт этапа 3: очистка истории подтверждённым DELETE."""
    if EXTERNAL and not DESTRUCTIVE:
        print(
            "\n[пропущено] очистка истории внешней панели требует "
            "ZERE_PANEL_DESTRUCTIVE=1"
        )
        return

    with running_panel() as (panel, _):
        if not EXTERNAL:
            panel.conversation.seed("раз", "два")
            panel.conversation.seed("три", "четыре")

        status, raw, _ = call(panel, "DELETE", "/api/history", body={"confirm": "DELETE"})
        assert status == 200, raw

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("HistoryDeleteResponse"), payload)
        if not EXTERNAL:
            assert payload["deleted"] == 2

        _, raw, _ = call(panel, "GET", "/api/history")
        assert json.loads(raw.decode("utf-8"))["total"] == 0


def test_history_delete_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(
            panel, "DELETE", "/api/history", token=None, body={"confirm": "DELETE"}
        )
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


# ── /api/memory (CRUD — этап 3) ───────────────────────────────────


def test_memory_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        if not EXTERNAL:
            panel.memory.remember("Любимый язык", "Python", "User")

        status, raw, _ = call(panel, "GET", "/api/memory")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("MemoryList"), payload)

        for item in payload["items"]:
            assert_schema(schema("MemoryItem"), item)

        if not EXTERNAL:
            assert any(item["key"] == "любимый язык" for item in payload["items"])


def test_memory_create_update_search_delete() -> None:
    with running_panel() as (panel, _):
        # создание
        status, raw, _ = call(
            panel,
            "POST",
            "/api/memory",
            body={"key": "панельная_проба", "value": "1", "category": "Test"},
        )
        assert status == 200, raw

        created = json.loads(raw.decode("utf-8"))
        assert_schema(schema("MemoryItem"), created)
        assert created["key"] == "панельная_проба"
        assert created["category"] == "Test"
        item_id = created["id"]

        # upsert по ключу: тот же id, новое значение, категория по умолчанию
        status, raw, _ = call(
            panel, "POST", "/api/memory", body={"key": "панельная_проба", "value": "2"}
        )
        assert status == 200, raw

        updated = json.loads(raw.decode("utf-8"))
        assert updated["id"] == item_id
        assert updated["value"] == "2"
        assert updated["category"] == "User"

        # поиск
        status, raw, _ = call(panel, "GET", "/api/memory?search=панельная")
        assert status == 200

        found = json.loads(raw.decode("utf-8"))
        assert_schema(schema("MemoryList"), found)
        assert [row["id"] for row in found["items"]] == [item_id]

        # поиск без совпадений пуст
        _, raw, _ = call(panel, "GET", "/api/memory?search=несуществующее_ключ")
        assert json.loads(raw.decode("utf-8"))["items"] == []

        # удаление по id
        status, raw, _ = call(panel, "DELETE", f"/api/memory/{item_id}")
        assert status == 200, raw
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("MemoryDeleteResponse"), payload)
        assert payload["deleted"] is True

        # повторное удаление → 404
        status, raw, _ = call(panel, "DELETE", f"/api/memory/{item_id}")
        assert status == 404
        assert error_payload(raw)["code"] == "NOT_FOUND"


def test_memory_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(
            panel, "POST", "/api/memory", token=None, body={"key": "a", "value": "b"}
        )
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_memory_validation_errors() -> None:
    with running_panel() as (panel, _):
        cases = (
            ({} , "«key»"),
            ({"key": "a"}, "«value»"),
            ({"key": "a", "value": 42}, "строкой"),
            ({"key": "   ", "value": "v"}, "пустым"),
            ({"key": "a", "value": "v", "zz": 1}, "Неизвестный ключ"),
            ({"key": "a" * 201, "value": "v"}, "200"),
            ({"key": "a", "value": "v" * 2001}, "2000"),
            ({"key": "a", "value": "v", "category": "c" * 101}, "100"),
        )

        for body, expected in cases:
            status, raw, _ = call(panel, "POST", "/api/memory", body=body)
            assert status == 400, body
            error = error_payload(raw)
            assert_schema(schema("Error"), error)
            assert error["code"] == "VALIDATION_ERROR"
            assert expected in error["message"], f"{body!r} → {error['message']!r}"


def test_memory_post_rejects_bad_json() -> None:
    with running_panel() as (panel, _):
        conn = http.client.HTTPConnection("127.0.0.1", panel.port, timeout=15)
        conn.request(
            "POST",
            "/api/memory",
            body=b"[not json",
            headers={"X-ZERE-Token": panel.token, "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        assert response.status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"


def test_memory_delete_rejects_bad_id() -> None:
    with running_panel() as (panel, _):
        for raw_id, expected in (("abc", 400), ("", 400), ("-1", 400), ("1.5", 400)):
            status, raw, _ = call(panel, "DELETE", f"/api/memory/{raw_id}")
            assert status == expected, f"{raw_id!r} → {status}"
            assert error_payload(raw)["code"] == "VALIDATION_ERROR"

        # валидный, но отсутствующий id → 404
        status, raw, _ = call(panel, "DELETE", "/api/memory/9223372036854775807")
        assert status == 404
        assert error_payload(raw)["code"] == "NOT_FOUND"

        # динамический маршрут принимает только DELETE
        status, raw, _ = call(panel, "GET", "/api/memory/1")
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


# ── Статика панели (SPA из panel/dist) ────────────────────────────


def test_static_index_injects_token() -> None:
    """UI читает токен из HTML при загрузке (§6 плана) — без заголовка."""
    with running_panel() as (panel, _):
        status, raw, headers = call(panel, "GET", "/", token=None)
        assert status == 200
        assert headers.get("content-type", "").startswith("text/html")

        html = raw.decode("utf-8")
        assert "__ZERE_TOKEN__" not in html  # плейсхолдер заменён
        assert panel.token in html


def test_static_asset_served_without_token() -> None:
    """<link>/<script> не шлют заголовки — статика доступна без токена."""
    assets = sorted((REPO_ROOT / "panel" / "dist" / "assets").glob("*.js"))
    assert assets, "panel/dist не собран — выполните npm run build в panel/"

    with running_panel() as (panel, _):
        status, _, headers = call(panel, "GET", f"/assets/{assets[0].name}", token=None)
        assert status == 200
        assert "javascript" in headers.get("content-type", "")


def test_spa_fallback_serves_index() -> None:
    with running_panel() as (panel, _):
        status, _, headers = call(panel, "GET", "/dashboard", token=None)
        assert status == 200
        assert headers.get("content-type", "").startswith("text/html")


def test_stage3_routes_serve_spa() -> None:
    """Прямые ссылки на экраны этапа 3 открываются (SPA-фоллбэк)."""
    with running_panel() as (panel, _):
        for path in ("/chat", "/history", "/memory"):
            status, _, headers = call(panel, "GET", path, token=None)
            assert status == 200, path
            assert headers.get("content-type", "").startswith("text/html"), path


def test_static_traversal_never_escapes_dist() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(
            panel, "GET", "/%2e%2e/%2e%2e/etc/passwd", token=None
        )

        if status == 200:
            # нормализация путей может отдать index.html — но никогда
            # файл с диска за пределами panel/dist
            assert b"root:" not in raw
        else:
            assert status in (400, 403, 404)


def test_static_post_is_not_allowed() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/", token=None, body={})
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


# ── /api/processes и /api/power (этап 4) ──────────────────────────


def _pick_process_pid(panel: Any) -> Optional[int]:
    """Безопасный PID для тестов подтверждения: не защищённый процесс."""
    if not EXTERNAL:
        return 200  # фиктивный notepad в FakeProcessService

    status, raw, _ = call(panel, "GET", "/api/processes")
    if status != 200:
        return None

    for item in json.loads(raw.decode("utf-8"))["items"]:
        if not item["protected"]:
            return int(item["pid"])
    return None


def _pick_protected_pid(panel: Any) -> Optional[int]:
    """Защищённый процесс: локально — фиктивный System (4), в CI — реальный."""
    if not EXTERNAL:
        return 4

    status, raw, _ = call(panel, "GET", "/api/processes")
    if status != 200:
        return None

    for item in json.loads(raw.decode("utf-8"))["items"]:
        if item["protected"]:
            return int(item["pid"])
    return None


def test_processes_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/processes")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("ProcessList"), payload)

        for item in payload["items"]:
            assert_schema(schema("ProcessInfo"), item)

        memory = [item["memoryMb"] for item in payload["items"]]
        assert memory == sorted(memory, reverse=True), "нет сортировки по памяти"

        if not EXTERNAL:
            assert {item["pid"] for item in payload["items"]} == {4, 100, 101, 200}
            system = next(item for item in payload["items"] if item["pid"] == 4)
            assert system["protected"] is True
            assert system["responding"] is True


def test_processes_search_filters_by_name() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/processes?q=CHRO")
        assert status == 200

        items = json.loads(raw.decode("utf-8"))["items"]

        for item in items:
            assert "chro" in item["name"].lower()

        if not EXTERNAL:
            assert [item["pid"] for item in items] == [100, 101]


def test_processes_rejects_long_query() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/processes?q=" + "a" * 101)
        assert status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"


def test_processes_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/processes", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_processes_wrong_method_is_405() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/processes", body={})
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


def test_process_kill_rejects_bad_pid() -> None:
    with running_panel() as (panel, _):
        for bad in ("abc", "0", "-1", "2147483648", ""):
            status, raw, _ = call(panel, "POST", f"/api/processes/{bad}/kill", body={})
            assert status == 400, bad
            assert error_payload(raw)["code"] == "VALIDATION_ERROR", bad


def test_process_kill_unknown_pid_is_404() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/processes/2147483647/kill", body={})
        assert status == 404
        assert error_payload(raw)["code"] == "NOT_FOUND"


def test_process_kill_protected_is_rejected() -> None:
    """Гейт этапа 4: системный процесс не завершается даже с валидным токеном."""
    with running_panel() as (panel, _):
        pid = _pick_protected_pid(panel)

        if pid is None:
            print("\n[пропущено] защищённый процесс в этой среде не найден")
            return

        status, raw, _ = call(panel, "POST", f"/api/processes/{pid}/kill", body={})
        assert status == 400, raw
        error = error_payload(raw)
        assert_schema(schema("Error"), error)
        assert error["code"] == "PROTECTED"


def test_process_kill_requires_confirmation() -> None:
    """Шаг 2 без подтверждения или с несуществующим токеном не выполняется."""
    with running_panel() as (panel, _):
        pid = _pick_process_pid(panel)
        assert pid is not None, "не нашлся процесс для теста подтверждения"

        cases = (
            ({"ttlToken": "a" * 32}, "VALIDATION_ERROR"),
            ({"confirm": "YES", "ttlToken": "a" * 32}, "VALIDATION_ERROR"),
            ({"confirm": "KILL"}, "VALIDATION_ERROR"),
            ({"confirm": "KILL", "ttlToken": "zz" * 16}, "VALIDATION_ERROR"),
            ({"confirm": "KILL", "ttlToken": "a" * 32}, "TTL_EXPIRED"),
        )

        for body, expected_code in cases:
            status, raw, _ = call(panel, "POST", f"/api/processes/{pid}/kill", body=body)
            assert status == 400, body
            error = error_payload(raw)
            assert_schema(schema("Error"), error)
            assert error["code"] == expected_code, body


def test_process_kill_two_step_executes() -> None:
    """Гейт этапа 4: убийство только после серверного TTL-подтверждения."""
    if EXTERNAL and not DESTRUCTIVE:
        print(
            "\n[пропущено] завершение процесса внешней панели требует "
            "ZERE_PANEL_DESTRUCTIVE=1"
        )
        return

    # Против настоящей панели убиваем только СОБСТВЕННЫЙ дочерний процесс.
    child = (
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        if EXTERNAL
        else None
    )

    try:
        with running_panel() as (panel, _):
            pid = child.pid if child is not None else 200

            if child is not None:
                time.sleep(1.0)  # дать процессу появиться в списке

            status, raw, _ = call(panel, "POST", f"/api/processes/{pid}/kill", body={})
            assert status == 200, raw
            pending = json.loads(raw.decode("utf-8"))
            assert_schema(schema("KillPending"), pending)
            assert pending["pid"] == pid
            assert pending["expiresInSeconds"] == 60

            status, raw, _ = call(
                panel,
                "POST",
                f"/api/processes/{pid}/kill",
                body={"confirm": "KILL", "ttlToken": pending["ttlToken"]},
            )
            assert status == 200, raw
            result = json.loads(raw.decode("utf-8"))
            assert_schema(schema("KillResult"), result)
            assert result["pid"] == pid

            if not EXTERNAL:
                assert panel.process_service.killed == [200]

                # Токен одноразовый и привязан к действию: тот же токен
                # для другого (существующего!) процесса не выполняется.
                status, raw, _ = call(
                    panel,
                    "POST",
                    "/api/processes/101/kill",
                    body={"confirm": "KILL", "ttlToken": pending["ttlToken"]},
                )
                assert status == 400, raw
                assert error_payload(raw)["code"] == "TTL_EXPIRED"
            else:
                deadline = time.monotonic() + 10
                while child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.25)
                assert child.poll() is not None, "дочерний процесс не завершился"
    finally:
        if child is not None and child.poll() is None:
            child.kill()


def test_power_unknown_action_is_404() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/power/explode", body={})
        assert status == 404
        assert error_payload(raw)["code"] == "NOT_FOUND"


def test_power_pending_issues_token() -> None:
    """Шаг 1 безопасен: действие только ставится в очередь подтверждения."""
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/power/shutdown", body={})
        assert status == 200, raw

        pending = json.loads(raw.decode("utf-8"))
        assert_schema(schema("PowerPending"), pending)
        assert pending["action"] == "shutdown"
        assert pending["expiresInSeconds"] == 60

        if not EXTERNAL:
            assert panel.safe_actions.requests == ["SHUTDOWN"]


def test_power_requires_confirmation() -> None:
    """Подтверждение без валидного токена не доходит до выполнения."""
    with running_panel() as (panel, _):
        for body in (
            {"ttlToken": "a" * 32},
            {"confirm": "POWER"},
            {"confirm": "SHUTDOWN", "ttlToken": "a" * 32},
            {"confirm": "POWER", "ttlToken": "zz" * 16},
        ):
            status, raw, _ = call(panel, "POST", "/api/power/sleep", body=body)
            assert status == 400, body
            error = error_payload(raw)
            assert_schema(schema("Error"), error)
            assert error["code"] == "VALIDATION_ERROR", body

        # Корректный формат, но токен не выдавался.
        status, raw, _ = call(
            panel,
            "POST",
            "/api/power/sleep",
            body={"confirm": "POWER", "ttlToken": "a" * 32},
        )
        assert status == 400
        assert error_payload(raw)["code"] == "TTL_EXPIRED"


def test_power_confirm_executes() -> None:
    """Полный цикл питания — только локально: фейк не выключает машину."""
    if EXTERNAL:
        print(
            "\n[пропущено] подтверждение питания на внешней панели выполняло "
            "бы реальное выключение (тест только для фейка)"
        )
        return

    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/power/restart", body={})
        assert status == 200, raw
        token = json.loads(raw.decode("utf-8"))["ttlToken"]

        status, raw, _ = call(
            panel,
            "POST",
            "/api/power/restart",
            body={"confirm": "POWER", "ttlToken": token},
        )
        assert status == 200, raw
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("PowerResult"), payload)
        assert payload["status"] == "executed"
        assert payload["action"] == "restart"

        # Токен одноразовый: повторное подтверждение не выполняется.
        status, raw, _ = call(
            panel,
            "POST",
            "/api/power/restart",
            body={"confirm": "POWER", "ttlToken": token},
        )
        assert status == 400
        assert error_payload(raw)["code"] == "TTL_EXPIRED"


# ── /api/apps (этап 4) ────────────────────────────────────────────


def test_apps_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/apps")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AppList"), payload)

        for item in payload["items"]:
            assert_schema(schema("AppInfo"), item)

        assert payload["total"] == len(payload["items"])

        priorities = [item["priority"] for item in payload["items"]]
        assert priorities == sorted(priorities, reverse=True), "нет сортировки по priority"

        if not EXTERNAL:
            assert [item["name"] for item in payload["items"]] == [
                "Notepad++",
                "Discord",
                "Calc",
            ]
            discord = payload["items"][1]
            assert discord["executablePath"].endswith("Discord.exe")
            assert discord["aliases"] == ["дискорд"]
            assert discord["lastSeen"].startswith("2026-01-15T09:30")


def test_apps_search_filters_by_name_and_alias() -> None:
    with running_panel() as (panel, _):
        # По имени (без учёта регистра)
        status, raw, _ = call(panel, "GET", "/api/apps?q=note")
        assert status == 200
        items = json.loads(raw.decode("utf-8"))["items"]
        if not EXTERNAL:
            assert [item["name"] for item in items] == ["Notepad++"]
        else:
            for item in items:
                assert "note" in item["name"].lower()

        # По алиасу на кириллице
        status, raw, _ = call(panel, "GET", "/api/apps?q=" + quote("Дискорд"))
        assert status == 200
        items = json.loads(raw.decode("utf-8"))["items"]
        if not EXTERNAL:
            assert [item["name"] for item in items] == ["Discord"]

        # Ничего не найдено — пустой список, а не ошибка
        status, raw, _ = call(panel, "GET", "/api/apps?q=zzzz-no-such-app")
        assert status == 200
        payload = json.loads(raw.decode("utf-8"))
        assert payload["items"] == []
        assert payload["total"] == 0


def test_apps_rejects_long_query() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/apps?q=" + "a" * 201)
        assert status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"


def test_apps_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/apps", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_apps_wrong_method_is_405() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "DELETE", "/api/apps")
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


def test_apps_reindex_reports_count() -> None:
    """Гейт этапа 4: переиндексация возвращает размер индекса и длительность."""
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/apps/reindex")
        assert status == 200, raw

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AppReindexResponse"), payload)
        assert payload["count"] >= 0
        assert payload["durationMs"] >= 0

        if not EXTERNAL:
            assert panel.app_launcher.rebuilds == 1
            assert payload["count"] == 3


# ── /api/logs (этап 4) ────────────────────────────────────────────


@contextmanager
def seeded_logs(
    session_lines: Optional[list[str]] = None,
    errors_lines: Optional[list[str]] = None,
) -> Iterator[None]:
    """Засевает журнал панели (logs/) и возвращает исходное состояние.

    Сид-файл называется «в будущем» (2099): засеянные строки всегда первые
    в выдаче, поэтому реальные логи среды не мешают проверке порядка.

    Каталог берётся из `paths.LOGS_DIR`, а не из `REPO_ROOT / "logs"`:
    иначе фикстура писала бы в боевой журнал и восстанавливала его из
    снимка, затирая настоящие записи во время теста (изоляцию задаёт
    tests/conftest.py; во внешнем режиме путь остаётся настоящим).
    """
    folder = paths_module.LOGS_DIR
    folder.mkdir(parents=True, exist_ok=True)

    session_file = folder / "zere_2099-01-01_00-00-00.log"
    errors_file = folder / "errors.log"
    original_errors = errors_file.read_bytes() if errors_file.exists() else None

    session_file.write_text(
        "".join(f"{line}\n" for line in (session_lines or [])), encoding="utf-8"
    )

    if errors_lines:
        with errors_file.open("a", encoding="utf-8") as handle:
            for line in errors_lines:
                handle.write(line + "\n")

    try:
        yield
    finally:
        session_file.unlink(missing_ok=True)

        if original_errors is None:
            errors_file.unlink(missing_ok=True)
        else:
            errors_file.write_bytes(original_errors)


def test_logs_get_matches_spec() -> None:
    with running_panel() as (panel, _), seeded_logs(
        [
            "[2099-01-01 00:00:00] [INFO] seeded-info",
            "[2099-01-01 00:00:01] [WARN] seeded-warn",
        ]
    ):
        status, raw, _ = call(panel, "GET", "/api/logs")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("LogList"), payload)

        for item in payload["items"]:
            assert_schema(schema("LogEntry"), item)

        assert payload["total"] >= 2

        # Засеянные (2099-й год) — сверху, в порядке времени DESC
        top = payload["items"][:2]
        assert [item["time"] for item in top] == [
            "2099-01-01T00:00:01",
            "2099-01-01T00:00:00",
        ]
        assert [item["level"] for item in top] == ["warn", "info"]
        assert top[0]["message"] == "seeded-warn"
        assert top[1]["message"] == "seeded-info"
        assert top[1]["source"] is None  # сессионный файл — без источника


def test_logs_level_filter() -> None:
    with running_panel() as (panel, _), seeded_logs(
        [
            "[2099-01-01 00:01:00] [INFO] seeded-info",
            "[2099-01-01 00:01:01] [WARN] seeded-warn",
            "[2099-01-01 00:01:02] [ERROR] seeded-error",
        ]
    ):
        for level, expected in (
            ("info", "seeded-info"),
            ("warn", "seeded-warn"),
            ("error", "seeded-error"),
        ):
            status, raw, _ = call(panel, "GET", f"/api/logs?level={level}")
            assert status == 200, level

            payload = json.loads(raw.decode("utf-8"))
            assert payload["total"] >= 1, level
            assert all(item["level"] == level for item in payload["items"]), level
            assert any(item["message"] == expected for item in payload["items"]), level


def test_logs_pagination() -> None:
    with running_panel() as (panel, _), seeded_logs(
        ["[2099-01-01 00:02:00] [INFO] seeded-page"]
    ):
        status, raw, _ = call(panel, "GET", "/api/logs?limit=1")
        assert status == 200

        page = json.loads(raw.decode("utf-8"))
        assert len(page["items"]) == 1
        assert page["items"][0]["message"] == "seeded-page"

        # offset за концом — пустая страница, total не меняется
        status, raw, _ = call(panel, "GET", f"/api/logs?limit=1&offset={page['total']}")
        assert status == 200

        tail = json.loads(raw.decode("utf-8"))
        assert tail["items"] == []
        assert tail["total"] == page["total"]


def test_logs_rejects_bad_params() -> None:
    with running_panel() as (panel, _):
        for query in ("limit=0", "limit=501", "limit=abc", "offset=-1", "level=trace"):
            status, raw, _ = call(panel, "GET", f"/api/logs?{query}")
            assert status == 400, query
            assert error_payload(raw)["code"] == "VALIDATION_ERROR", query


def test_logs_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/logs", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_logs_errors_file_has_source() -> None:
    """Источник — по имени файла: сообщение с [скобками] не съедает поле."""
    with running_panel() as (panel, _), seeded_logs(
        errors_lines=[
            "[2099-01-01 00:03:00] [ERROR] [PanelServer] [Errno 32] Broken pipe"
        ]
    ):
        status, raw, _ = call(panel, "GET", "/api/logs?level=error")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        found = [
            item
            for item in payload["items"]
            if item["time"] == "2099-01-01T00:03:00"
        ]
        assert found, "засеянная строка errors.log не найдена"
        assert found[0]["source"] == "PanelServer"
        assert found[0]["message"] == "[Errno 32] Broken pipe"
        assert found[0]["level"] == "error"


# ── /api/plugins (этап 4) ─────────────────────────────────────────


def test_plugins_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/plugins")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("PluginList"), payload)

        for item in payload["items"]:
            assert_schema(schema("Plugin"), item)

        # Подмена движка конвейера не имеет — значит моста плагинов нет,
        # и флаг обязан быть false (у реального движка он true, см.
        # test_plugin_handlers_connected_reflects_pipeline).
        assert payload["handlersConnected"] is False
        assert isinstance(payload["commandHandlersCount"], int)
        assert payload["commandHandlersCount"] >= 0

        # Встроенный плагин личности есть в обеих реализациях
        found = [item for item in payload["items"] if item["id"] == "personality"]
        assert found, "встроенный плагин личности не найден"
        assert found[0]["name"] == "Личность ZERE"
        assert found[0]["version"] == "1.0.0"
        assert found[0]["author"] == "ZERE"
        assert found[0]["type"] == "Personality"

        active = payload["activePersonality"]
        assert active is not None
        assert active["id"] == "personality"
        assert active["style"] == "Friendly"


def test_plugins_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/plugins", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_plugins_wrong_method_is_405() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "DELETE", "/api/plugins")
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


# ── /api/plugins/mcp: состояние MCP-плагинов и выбор браузера ──────
#
# Маршруты есть только в Python-редакции (в C# MCP-плагинов нет), поэтому во
# внешнем режиме они не проверяются — панель по 404 прячет блок выбора.


def test_plugins_mcp_paths_are_in_spec() -> None:
    """Контракт: маршруты MCP-плагинов описаны в docs/api/openapi.yaml."""
    for path in ("/api/plugins/mcp", "/api/plugins/mcp/browser"):
        assert path in SPEC["paths"], path


def test_plugins_mcp_without_plugins_is_empty() -> None:
    """Нет MCP-плагинов — честный пустой список, а не ошибка."""
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/plugins/mcp")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("McpPluginList"), payload)
        assert payload["items"] == []


def test_plugins_mcp_get_matches_spec() -> None:
    if EXTERNAL:
        return

    browser = FakeMcpPlugin()
    notes = FakeMcpPlugin("obsidian")

    with running_panel(mcp_plugins=[browser, notes]) as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/plugins/mcp")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("McpPluginList"), payload)

        items = {item["serverId"]: item for item in payload["items"]}
        assert set(items) == {"playwright", "obsidian"}

        for item in payload["items"]:
            assert_schema(schema("McpPluginState"), item)

        # Браузер: только у плагина браузера, со списком и текущим выбором.
        assert_schema(schema("McpBrowserState"), items["playwright"]["browser"])
        assert items["playwright"]["browser"]["current"] == "edge"
        assert [option["id"] for option in items["playwright"]["browser"]["options"]] == [
            "edge",
            "chrome",
            "opera-gx",
            "chromium",
        ]
        assert "browser" not in items["obsidian"], "у плагина заметок выбора браузера нет"


def test_plugins_mcp_browser_select_persists_and_returns_state() -> None:
    if EXTERNAL:
        return

    browser = FakeMcpPlugin()

    with running_panel(mcp_plugins=[browser]) as (panel, _):
        status, raw, _ = call(
            panel, "POST", "/api/plugins/mcp/browser", body={"browser": "opera-gx"}
        )
        assert status == 200, raw

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("McpBrowserSelected"), payload)
        assert_schema(schema("McpBrowserState"), payload["browser"])

        assert browser.selected == ["opera-gx"], "выбор доходит до плагина"
        assert payload["browser"]["current"] == "opera-gx"
        assert "Opera GX" in payload["message"]

        # Состояние после выбора отдаётся сразу — панели не нужен второй запрос.
        assert payload["items"][0]["browser"]["current"] == "opera-gx"


def test_plugins_mcp_browser_rejects_unknown_name() -> None:
    """Неизвестный браузер — 400 с русским объяснением от плагина."""
    if EXTERNAL:
        return

    browser = FakeMcpPlugin()

    with running_panel(mcp_plugins=[browser]) as (panel, _):
        status, raw, _ = call(
            panel, "POST", "/api/plugins/mcp/browser", body={"browser": "файрфокс"}
        )
        assert status == 400

        payload = error_payload(raw)
        assert payload["code"] == "BROWSER_UNAVAILABLE"
        assert "файрфокс" in payload["message"]
        assert "opera-gx" in payload["message"], "в отказе перечислены доступные браузеры"
        assert browser.selected == ["файрфокс"], "попытка доходит до плагина"


def test_plugins_mcp_browser_validates_body() -> None:
    if EXTERNAL:
        return

    with running_panel(mcp_plugins=[FakeMcpPlugin()]) as (panel, _):
        for body in ({}, {"browser": ""}, {"browser": 5}, {"browser": "edge", "x": 1}):
            status, raw, _ = call(panel, "POST", "/api/plugins/mcp/browser", body=body)
            assert status == 400, (body, raw)
            assert error_payload(raw)["code"] == "VALIDATION_ERROR"


def test_plugins_mcp_browser_without_plugin_is_404() -> None:
    """Плагин браузера не загружен (или сборка без выбора) — 404, не 500."""
    with running_panel() as (panel, _):
        status, raw, _ = call(
            panel, "POST", "/api/plugins/mcp/browser", body={"browser": "edge"}
        )
        assert status == 404
        assert error_payload(raw)["code"] == "NOT_FOUND"

    with running_panel(mcp_plugins=[FakeMcpPlugin(can_select=False)]) as (panel, _):
        status, raw, _ = call(
            panel, "POST", "/api/plugins/mcp/browser", body={"browser": "edge"}
        )
        assert status == 404
        assert error_payload(raw)["code"] == "NOT_FOUND"


def test_plugins_mcp_routes_require_token_and_reject_methods() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/plugins/mcp", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"

        status, _, _ = call(panel, "POST", "/api/plugins/mcp")
        assert status == 405

        status, _, _ = call(panel, "GET", "/api/plugins/mcp/browser")
        assert status == 405

        status, _, _ = call(panel, "GET", "/api/plugins/mcp/browser", token=None)
        assert status == 401


# ── Голос (этап 4, §6 плана) ──────────────────────────────────────


def test_voice_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/voice")
        assert status == 200, raw
        data = json.loads(raw.decode("utf-8"))
        assert_schema(schema("VoiceSettings"), data)

        assert isinstance(data["voiceEnabled"], bool)
        assert data["voiceVolume"] == 0.5
        assert data["ttsEngine"] == "pocket"
        assert isinstance(data["voiceReferencePath"], str)

        caps = data["capabilities"]
        assert_schema(schema("VoiceCapabilities"), caps)
        # Одинаково в обеих реализациях:
        assert caps["liveVolumeApply"] is True
        assert caps["recordReference"] is True  # C# записывает; фейк локально — тоже
        # Значения зависят от реализации (C# vs Python) — проверяем только тип:
        for key in ("pocketCloning", "speechSpeedConfig", "sttTest"):
            assert isinstance(caps[key], bool), key


def test_voice_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/voice", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_voice_wrong_method_is_405() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "DELETE", "/api/voice")
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"

        # /api/voice/test принимает только POST
        status, raw, _ = call(panel, "GET", "/api/voice/test")
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


def test_voice_post_applies_volume_live() -> None:
    with running_panel() as (panel, _):
        # EXTERNAL: значение совпадает с текущим — конфиг репозитория не трогаем
        volume = 0.5 if EXTERNAL else 0.75

        status, raw, _ = call(panel, "POST", "/api/voice", body={"voiceVolume": volume})
        assert status == 200, raw
        data = json.loads(raw.decode("utf-8"))
        assert_schema(schema("VoiceSettingsApplied"), data)
        assert data["voiceVolume"] == volume
        # Только громкость — рестарт не нужен
        assert data["appliedOnRestart"] is False

        if not EXTERNAL:
            # liveVolumeApply: громкость ушла в голосовой модуль сразу
            assert panel.voice.config.volume == 0.75

            status, raw, _ = call(panel, "GET", "/api/voice")
            assert status == 200, raw
            assert json.loads(raw.decode("utf-8"))["voiceVolume"] == 0.75


def test_voice_post_applies_on_restart() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/voice")
        assert status == 200, raw
        initial = json.loads(raw.decode("utf-8"))

        # ttsEngine: переключаем и возвращаем исходное (репозиторий/темп чистые)
        other_engine = "chattts" if initial["ttsEngine"] != "chattts" else "pocket"

        status, raw, _ = call(panel, "POST", "/api/voice", body={"ttsEngine": other_engine})
        assert status == 200, raw
        data = json.loads(raw.decode("utf-8"))
        assert_schema(schema("VoiceSettingsApplied"), data)
        assert data["ttsEngine"] == other_engine
        assert data["appliedOnRestart"] is True

        status, raw, _ = call(panel, "POST", "/api/voice", body={"ttsEngine": initial["ttsEngine"]})
        assert status == 200, raw
        assert json.loads(raw.decode("utf-8"))["appliedOnRestart"] is True

        # voiceEnabled: bool-путь тоже «отложенный»
        status, raw, _ = call(panel, "POST", "/api/voice", body={"voiceEnabled": not initial["voiceEnabled"]})
        assert status == 200, raw
        data = json.loads(raw.decode("utf-8"))
        assert data["voiceEnabled"] is (not initial["voiceEnabled"])
        assert data["appliedOnRestart"] is True

        status, raw, _ = call(panel, "POST", "/api/voice", body={"voiceEnabled": initial["voiceEnabled"]})
        assert status == 200, raw
        assert json.loads(raw.decode("utf-8"))["appliedOnRestart"] is True

        # всё возвращено к исходному состоянию
        status, raw, _ = call(panel, "GET", "/api/voice")
        data = json.loads(raw.decode("utf-8"))
        assert data["ttsEngine"] == initial["ttsEngine"]
        assert data["voiceEnabled"] is initial["voiceEnabled"]
        assert data["voiceVolume"] == initial["voiceVolume"]


def test_voice_post_rejects_bad_payload() -> None:
    with running_panel() as (panel, _):
        bad_bodies: list[Any] = [
            {},  # ни одного поля
            {"assistantName": "X"},  # посторонний ключ
            {"voiceVolume": 1.5},  # вне диапазона
            {"voiceVolume": -0.1},
            {"voiceVolume": "loud"},  # не число
            {"voiceVolume": True},  # bool ≠ число
            {"ttsEngine": "elevenlabs"},  # не тот движок
            {"voiceEnabled": "yes"},  # не bool
            {"voiceReferencePath": 42},  # не строка
            [1, 2],  # не объект
        ]
        for body in bad_bodies:
            status, raw, _ = call(panel, "POST", "/api/voice", body=body)
            assert status == 400, (body, raw)
            assert error_payload(raw)["code"] == "VALIDATION_ERROR", body

        # точное сообщение — в стиле валидации /api/config
        status, raw, _ = call(panel, "POST", "/api/voice", body={"speed": 2})
        assert status == 400
        assert error_payload(raw)["message"] == "Неизвестный ключ голосовых настроек: «speed»."

        # ничего не применилось
        status, raw, _ = call(panel, "GET", "/api/voice")
        data = json.loads(raw.decode("utf-8"))
        assert data["voiceVolume"] == 0.5
        assert data["ttsEngine"] == "pocket"


def test_voice_test_speaks_or_not_ready() -> None:
    with running_panel() as (panel, _):
        # валидация текста — до проверки доступности TTS, одинаково везде
        for body, needle in [
            ({"t": 1}, "Неизвестный ключ"),
            ({}, "должен быть строкой"),
            ({"text": "   "}, "не может быть пустым"),
            ({"text": "х" * 501}, "длиннее 500"),
        ]:
            status, raw, _ = call(panel, "POST", "/api/voice/test", body=body)
            assert status == 400, (body, raw)
            assert error_payload(raw)["code"] == "VALIDATION_ERROR", body
            assert needle in error_payload(raw)["message"], body

        status, raw, _ = call(panel, "POST", "/api/voice/test", body={"text": "скажи привет"})

        if EXTERNAL:
            # --panel не инициализирует голос → детерминированный 503
            assert status == 503, raw
            assert error_payload(raw)["code"] == "NOT_READY"
        else:
            assert status == 200, raw
            data = json.loads(raw.decode("utf-8"))
            assert_schema(schema("VoiceTestResult"), data)
            assert data["status"] == "ok"
            assert panel.voice.spoken == ["скажи привет"]


def test_voice_reference_records() -> None:
    if EXTERNAL:
        print("\n[пропущено] /api/voice/reference в EXTERNAL: запись с микрофона (15 с)")
        return

    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/voice/reference")
        assert status == 200, raw
        data = json.loads(raw.decode("utf-8"))
        assert_schema(schema("VoiceReferenceResult"), data)
        assert data["voiceReferencePath"].endswith(".wav")

        # путь сохранён в конфигурации и виден через GET
        status, raw, _ = call(panel, "GET", "/api/voice")
        assert status == 200, raw
        assert json.loads(raw.decode("utf-8"))["voiceReferencePath"] == data["voiceReferencePath"]


def test_voice_listen_transcribes() -> None:
    if EXTERNAL:
        print("\n[пропущено] /api/voice/listen в EXTERNAL: микрофон")
        return

    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/voice/listen")
        assert status == 200, raw
        data = json.loads(raw.decode("utf-8"))
        assert_schema(schema("VoiceListenResult"), data)
        assert data["text"] == "привет из микрофона"


# ── Непрерывный голосовой режим (POST /api/voice/mode) ───────────


def voice_mode_status(panel: Any) -> dict[str, Any]:
    """GET /api/voice/mode: код + схема проверяются на каждом опросе."""
    status, raw, _ = call(panel, "GET", "/api/voice/mode")
    assert status == 200, raw
    data = json.loads(raw.decode("utf-8"))
    assert_schema(schema("VoiceModeState"), data)
    return data


def wait_voice_mode(panel: Any, predicate: Any, timeout: float = 5.0) -> dict[str, Any]:
    """Опрашивает состояние, пока predicate не станет True (или таймаут)."""
    deadline = time.monotonic() + timeout
    last = voice_mode_status(panel)

    while time.monotonic() < deadline:
        if predicate(last):
            return last
        time.sleep(0.05)
        last = voice_mode_status(panel)

    raise AssertionError(f"голосовой режим не достиг ожидаемого состояния: {last}")


def test_voice_mode_get_matches_spec() -> None:
    with running_panel() as (panel, _):
        data = voice_mode_status(panel)

        assert data["enabled"] is False
        assert data["state"] == "idle"
        # Доступность/ wake word зависят от окружения — проверяем только типы,
        # значения wake word фиксированы дефолтами VoiceConfig в обеих реализациях:
        assert isinstance(data["available"], bool)
        assert isinstance(data["wakeWordEnabled"], bool)
        assert data["wakeWord"] == "зере"
        assert data["lastUtterance"] == ""
        assert data["lastAnswer"] == ""
        assert data["lastError"] is None
        # Счётчик голосовых реплик: по нему чат дописывает пару в диалог.
        assert data["turn"] == 0


def test_voice_mode_requires_token() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/voice/mode", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"

        status, raw, _ = call(panel, "POST", "/api/voice/mode", token=None, body={"enabled": True})
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_voice_mode_wrong_method_is_405() -> None:
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "PUT", "/api/voice/mode", body={"enabled": True})
        assert status == 405
        assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


def test_voice_mode_rejects_bad_payload() -> None:
    with running_panel() as (panel, _):
        for body, needle in [
            ({"on": True}, "Неизвестный ключ"),
            ({}, "Отсутствует обязательный ключ"),
            ({"enabled": 1}, "логическим значением"),
            ({"enabled": "yes"}, "логическим значением"),
        ]:
            status, raw, _ = call(panel, "POST", "/api/voice/mode", body=body)
            assert status == 400, (body, raw)
            assert error_payload(raw)["code"] == "VALIDATION_ERROR", body
            assert needle in error_payload(raw)["message"], body

        # Выключение без включения — идемпотентно и валидно (обе реализации)
        status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": False})
        assert status == 200, raw
        data = json.loads(raw.decode("utf-8"))
        assert_schema(schema("VoiceModeState"), data)
        assert data["enabled"] is False


def test_voice_mode_enable_requires_stt() -> None:
    if EXTERNAL:
        print("\n[пропущено] POST /api/voice/mode (enable) в EXTERNAL: чужой процесс")
        return

    with running_panel() as (panel, _):
        panel.voice.is_voice_available = False
        try:
            status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": True})
            assert status == 503, raw
            assert error_payload(raw)["code"] == "NOT_READY"

            data = voice_mode_status(panel)
            assert data["available"] is False
            assert data["enabled"] is False
        finally:
            panel.voice.is_voice_available = True


def test_voice_mode_cycle_without_wake_word() -> None:
    """Цикл без триггера: listen → engine.process → озвучка → выключение."""
    if EXTERNAL:
        print("\n[пропущено] POST /api/voice/mode (enable) в EXTERNAL: микрофон")
        return

    with running_panel() as (panel, _):
        voice = panel.voice
        voice.config.wake_word_enabled = False  # слушаем без слова-триггера
        voice.listen_results = ["создай папку тест"]

        status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": True})
        assert status == 200, raw
        started = json.loads(raw.decode("utf-8"))
        assert_schema(schema("VoiceModeState"), started)
        assert started["enabled"] is True
        # state в момент ответа гонится с фоновым потоком — значим только запуск
        assert started["state"] in ("sleeping", "listening", "processing", "speaking")

        # Повторное включение идемпотентно: цикл один
        status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": True})
        assert status == 200, raw

        done = wait_voice_mode(
            panel, lambda s: s["lastAnswer"] == "ответ: создай папку тест"
        )
        assert done["lastUtterance"] == "создай папку тест"
        assert done["lastError"] is None
        assert done["turn"] == 1, "обработанная реплика должна поднять счётчик чата"
        assert "создай папку тест" in panel.engine.processed
        assert "ответ: создай папку тест" in voice.spoken

        # Выключение: цикл останавливается, последняя реплика не теряется
        status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": False})
        assert status == 200, raw

        stopped = wait_voice_mode(panel, lambda s: s["enabled"] is False)
        assert stopped["state"] == "idle"
        assert stopped["lastUtterance"] == "создай папку тест"
        assert stopped["lastAnswer"] == "ответ: создай папку тест"


def test_voice_mode_cycle_with_wake_word() -> None:
    """Цикл с триггером: wake word → команда → ответ; стоп освобождает детектор."""
    if EXTERNAL:
        print("\n[пропущено] POST /api/voice/mode (enable) в EXTERNAL: микрофон")
        return

    with running_panel() as (panel, _):
        voice = panel.voice  # wake_word_enabled=True — дефолт VoiceConfig
        voice.wake_hits = 1  # детектор «слышит» триггер ровно один раз
        voice.listen_commands = ["сколько процессов"]

        status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": True})
        assert status == 200, raw

        done = wait_voice_mode(
            panel, lambda s: s["lastAnswer"] == "ответ: сколько процессов"
        )
        assert done["lastUtterance"] == "сколько процессов"
        assert done["lastError"] is None
        assert done["turn"] == 1, "wake-путь тоже считается репликой для чата"
        assert voice.wake_armed is True  # детектор пережил команду и ждёт снова

        status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": False})
        assert status == 200, raw

        stopped = wait_voice_mode(panel, lambda s: s["enabled"] is False)
        assert stopped["state"] == "idle"
        assert voice.wake_armed is False  # disable_wake_word вызван — микрофон свободен
        assert voice.wake_disabled >= 1


def test_voice_mode_process_error_keeps_listening() -> None:
    """Ошибка engine не убивает цикл: lastError заполнен, режим продолжает."""
    if EXTERNAL:
        print("\n[пропущено] POST /api/voice/mode (enable) в EXTERNAL: микрофон")
        return

    with running_panel() as (panel, _):
        voice = panel.voice
        voice.config.wake_word_enabled = False

        original_process = panel.engine.process

        def exploding(text: str) -> str:
            raise RuntimeError("ollama упал")

        panel.engine.process = exploding  # type: ignore[assignment]
        try:
            voice.listen_results = ["привет"]
            status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": True})
            assert status == 200, raw

            failed = wait_voice_mode(panel, lambda s: s["lastError"] is not None)
            assert "ollama упал" in failed["lastError"]
            assert failed["enabled"] is True  # цикл жив, слушает дальше
            assert failed["state"] in ("sleeping", "listening", "processing")
            # Пара не состоялась — счётчик реплик не растёт, и в чат
            # дописывать нечего (ошибка видна в самом режиме).
            assert failed["turn"] == 0
        finally:
            panel.engine.process = original_process  # type: ignore[assignment]
            status, raw, _ = call(panel, "POST", "/api/voice/mode", body={"enabled": False})
            assert status == 200, raw
            wait_voice_mode(panel, lambda s: s["enabled"] is False)


# ── /api/update — обновление из GitHub (docs/UPDATE.md) ───────────


def _require_python_update() -> bool:
    """Обновление реализовано только в Python-редакции.

    C#-панель эндпоинтов /api/update не имеет, поэтому в EXTERNAL-режиме
    (CI-джоба C#-редакции) проверки пропускаются — так же, как голосовые
    тесты, требующие микрофона.
    """
    if EXTERNAL:
        print("\n[пропущено] /api/update реализован только в Python-редакции")
        return False
    return True


def _wait_for_startup_probe(panel: Any, timeout: float = 5.0) -> int:
    """Ждёт автопроверку обновления при старте и возвращает число проверок.

    Панель запускает check() фоновым потоком, поэтому «сколько раз
    спрашивали сервис» проверяем после того, как он ответил хотя бы раз.
    """
    deadline = time.monotonic() + timeout
    while panel.updater.checks == 0 and time.monotonic() < deadline:
        time.sleep(0.01)

    return panel.updater.checks


def _pending_update(panel: Any) -> FakeUpdater:
    """Состояние фейка «есть 1 новый коммит» — без git и сети."""
    updater = panel.updater
    assert isinstance(updater, FakeUpdater)
    updater.update_available = True
    return updater


def test_update_paths_are_in_spec() -> None:
    """Контракт: маршруты обновления описаны в docs/api/openapi.yaml."""
    for path in ("/api/update", "/api/update/check", "/api/update/apply"):
        assert path in SPEC["paths"], path


def test_update_get_matches_spec() -> None:
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        checks = _wait_for_startup_probe(panel)
        _pending_update(panel)

        status, raw, headers = call(panel, "GET", "/api/update")
        assert status == 200
        assert headers.get("content-type", "").startswith("application/json")

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("UpdateStatus"), payload)
        assert_schema(schema("UpdateCommit"), payload["current"])
        assert_schema(schema("UpdateCommit"), payload["target"])

        for commit in payload["commits"]:
            assert_schema(schema("UpdateCommit"), commit)

        assert payload["edition"] == "python"
        assert payload["branch"] == "python-port"
        assert payload["behind"] == len(payload["commits"])
        assert payload["updateAvailable"] is True

        # GET отдаёт кэш: сервис (git fetch) повторно не опрашивается.
        assert panel.updater.checks == checks


def test_update_check_matches_spec() -> None:
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        checks = _wait_for_startup_probe(panel)
        _pending_update(panel)

        status, raw, _ = call(panel, "POST", "/api/update/check")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("UpdateStatus"), payload)

        assert panel.updater.checks == checks + 1
        assert payload["updateAvailable"] is True
        assert payload["behind"] == 1
        assert payload["commits"][0]["short"] == "bbbbbbb"
        assert payload["error"] is None


def test_update_check_runs_on_start() -> None:
    """Автопроверка при старте панели: ровно один фоновый опрос сервиса."""
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        assert _wait_for_startup_probe(panel) == 1
        assert panel.updater.calls == ["check"]


def test_update_apply_matches_spec() -> None:
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        _pending_update(panel)
        status, raw, _ = call(
            panel, "POST", "/api/update/apply", body={"installDependencies": True}
        )
        assert status == 200

        outcome = json.loads(raw.decode("utf-8"))
        assert_schema(schema("UpdateOutcome"), outcome)

        assert outcome["ok"] is True
        assert outcome["pulled"] == 1
        assert outcome["dependencies"] == "updated"
        assert outcome["restartRequired"] is True
        assert outcome["fromHash"] == "a" * 40
        assert outcome["toHash"] == "b" * 40
        assert panel.updater.install_dependencies is True

        # Состояние после применения: обновлений больше нет, итог в lastResult.
        status, raw, _ = call(panel, "GET", "/api/update")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("UpdateStatus"), payload)
        assert_schema(schema("UpdateOutcome"), payload["lastResult"])

        assert payload["updateAvailable"] is False
        assert payload["canUpdate"] is False
        assert payload["lastResult"]["ok"] is True


def test_update_apply_empty_body_uses_defaults() -> None:
    """Пустое тело (requestBody.required: false) — зависимости обновляются."""
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        _pending_update(panel)
        status, raw, _ = call(panel, "POST", "/api/update/apply")
        assert status == 200

        outcome = json.loads(raw.decode("utf-8"))
        assert_schema(schema("UpdateOutcome"), outcome)

        assert outcome["ok"] is True
        assert panel.updater.install_dependencies is True


def test_update_apply_can_skip_dependencies() -> None:
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        _pending_update(panel)
        status, raw, _ = call(
            panel, "POST", "/api/update/apply", body={"installDependencies": False}
        )
        assert status == 200

        outcome = json.loads(raw.decode("utf-8"))
        assert_schema(schema("UpdateOutcome"), outcome)
        assert outcome["ok"] is True
        assert panel.updater.install_dependencies is False


def test_update_apply_validation_errors() -> None:
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        for body in ({"foo": 1}, {"installDependencies": "yes"}):
            status, raw, _ = call(panel, "POST", "/api/update/apply", body=body)
            assert status == 400, body
            assert error_payload(raw)["code"] == "VALIDATION_ERROR"

        # Битый JSON и не-объект в теле — тоже 400, сервис не вызывается.
        conn = http.client.HTTPConnection("127.0.0.1", panel.port, timeout=15)
        try:
            conn.request(
                "POST",
                "/api/update/apply",
                body=b"{not json",
                headers={"X-ZERE-Token": panel.token, "Content-Type": "application/json"},
            )
            assert conn.getresponse().status == 400
        finally:
            conn.close()

        status, raw, _ = call(panel, "POST", "/api/update/apply", body=[1, 2])
        assert status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"

        assert panel.updater.applies == 0


def test_update_busy_is_409() -> None:
    """Параллельная операция: 409 UPDATE_BUSY, GET по-прежнему отдаёт статус."""
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        _wait_for_startup_probe(panel)
        _pending_update(panel).busy = True

        for path in ("/api/update/check", "/api/update/apply"):
            status, raw, _ = call(panel, "POST", path)
            assert status == 409, path

            payload = error_payload(raw)
            assert_schema(schema("Error"), payload)
            assert payload["code"] == "UPDATE_BUSY"

        status, raw, _ = call(panel, "GET", "/api/update")
        assert status == 200

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("UpdateStatus"), payload)
        assert payload["applying"] is True
        assert payload["canUpdate"] is False


def test_update_requires_token() -> None:
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/update", token=None)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"

        status, raw, _ = call(panel, "POST", "/api/update/apply", token="f" * 64)
        assert status == 401
        assert error_payload(raw)["code"] == "UNAUTHORIZED"

        assert panel.updater.applies == 0


def test_update_wrong_method_is_405() -> None:
    if not _require_python_update():
        return

    with running_panel() as (panel, _):
        for method, path in (
            ("POST", "/api/update"),
            ("GET", "/api/update/check"),
            ("GET", "/api/update/apply"),
            ("DELETE", "/api/update"),
        ):
            status, raw, _ = call(panel, method, path)
            assert status == 405, f"{method} {path}"
            assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


def test_ai_paths_are_in_spec() -> None:
    """Контракт: маршруты ИИ описаны в docs/api/openapi.yaml."""
    for path in (
        "/api/ai",
        "/api/ai/settings",
        "/api/ai/key",
        "/api/ai/key/test",
        "/api/ai/local",
        "/api/ai/local/test",
        "/api/ai/local/pull",
    ):
        assert path in SPEC["paths"], path


def _require_inprocess_ai() -> bool:
    """Проверки с фейковым провайдером: только внутрипроцессный прогон.

    В режиме ZERE_PANEL_EXTERNAL панель настоящая (C# или Python): подсунуть
    ей фейковый HTTP нельзя, а живые ключи и модели пользователя трогать
    нельзя — поэтому там остаются только форма ответа, валидация и
    безопасность (401/405/400 без обращения к провайдеру).
    """
    if EXTERNAL:
        print("\n[пропущено] нужен фейковый провайдер ИИ (внутрипроцессный прогон)")
        return False
    return True


def _ai_session_with_key() -> FakeSession:
    """HTTP-фейк: облачный /models и мини-запрос к чату отвечают.

    Мини-запрос нужен потому, что ключ подтверждается ещё и запросом к
    модели (`max_tokens=1`) — /models у части шлюзов публичный.
    """
    return (
        FakeSession()
        .route("GET", "/models", models_response(["gpt-4o-mini"]))
        .route("POST", "/chat/completions", chat_response("pong"))
    )


def _ai_session_with_local(model: str = DEFAULT_LOCAL_MODEL) -> FakeSession:
    """HTTP-фейк: запущена Ollama с моделью (native /api/tags + чат)."""
    return (
        FakeSession()
        .route("GET", "/api/tags", ollama_tags_response([model]))
        .route("POST", "/chat/completions", chat_response("pong"))
    )


def test_ai_status_without_key_or_model() -> None:
    with running_panel() as (panel, _):
        status, raw, headers = call(panel, "GET", "/api/ai")
        assert status == 200
        assert headers.get("content-type", "").startswith("application/json")

        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AiStatus"), payload)
        assert_schema(schema("AiCloudStatus"), payload["cloud"])
        assert_schema(schema("AiLocalStatus"), payload["local"])
        for preset in payload["presets"]:
            assert_schema(schema("AiProviderPreset"), preset)
        for option in payload["local"]["suggestions"]:
            assert_schema(schema("AiLocalModelOption"), option)

        if EXTERNAL:
            # У настоящей панели свой config/ai.json и своя Ollama: состояние
            # не детерминировано, форма ответа уже проверена выше.
            return

        # Требование 1: без ключа и без локальной модели — приглашение.
        assert payload["activeProvider"] == "none"
        assert payload["ready"] is False
        assert payload["summary"] == "Подключите API-ключ или используйте локальную модель"
        assert payload["cloud"]["keySaved"] is False
        assert payload["cloud"]["keyMask"] == ""
        assert payload["local"]["status"] == "server-down"
        # Требование 8: понятная инструкция по установке.
        assert_schema(schema("AiInstallHint"), payload["local"]["installHint"])
        assert payload["local"]["installHint"]["command"] == f"ollama pull {DEFAULT_LOCAL_MODEL}"


def test_ai_status_reports_local_model_available() -> None:
    if not _require_inprocess_ai():
        return

    with running_panel(_ai_session_with_local()) as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/ai")
        assert status == 200
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AiStatus"), payload)
        assert payload["activeProvider"] == "local"
        assert payload["ready"] is True
        assert "Подключено: локальная модель" in payload["summary"]
        assert payload["local"]["status"] == "available"
        assert payload["local"]["canPull"] is True
        assert payload["local"]["installHint"] is None


def test_ai_key_save_shows_cloud_connected() -> None:
    if not _require_inprocess_ai():
        return

    with running_panel(_ai_session_with_key()) as (panel, tmp):
        status, raw, _ = call(
            panel,
            "POST",
            "/api/ai/key",
            body={
                "apiKey": "sk-live-abcdefghijklmnop",
                "cloudProvider": "openai",
                "cloudBaseUrl": "https://api.openai.com/v1",
                "cloudModel": "gpt-4o-mini",
            },
        )
        assert status == 200
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AiStatus"), payload)

        # Требование 1: рабочий ключ → «Подключено: облачная модель».
        assert payload["activeProvider"] == "cloud"
        assert "Подключено: облачная модель" in payload["summary"]
        assert payload["cloud"]["keySaved"] is True
        assert payload["cloud"]["keyStatus"] == "ok"
        # Требование 4: в интерфейс уходит только маска.
        assert payload["cloud"]["keyMask"] == "sk-...mnop"
        assert "sk-live-abcdefghijklmnop" not in raw.decode("utf-8")

        # Ключ сохранён на бэкенде (файл настроек ИИ), а не в клиенте.
        saved = json.loads((tmp / "ai.json").read_text(encoding="utf-8"))
        assert saved["cloud_api_key"] == "sk-live-abcdefghijklmnop"


def test_ai_key_invalid_is_rejected_and_not_saved() -> None:
    if not _require_inprocess_ai():
        return

    session = FakeSession().route("GET", "/models", error_response(401, "invalid api key")).route(
        "POST", "/chat/completions", error_response(401, "invalid api key")
    )

    with running_panel(session) as (panel, tmp):
        status, raw, _ = call(panel, "POST", "/api/ai/key", body={"apiKey": "sk-bad-key-1234567890"})
        assert status == 400
        error = error_payload(raw)
        assert_schema(schema("Error"), error)
        assert error["code"] == "AI_KEY_INVALID"
        assert error["message"] == "Неверный API-ключ"
        assert "sk-bad-key-1234567890" not in raw.decode("utf-8")

        assert not (tmp / "ai.json").exists() or (
            "sk-bad-key-1234567890" not in (tmp / "ai.json").read_text(encoding="utf-8")
        )


def test_ai_key_errors_are_reported_with_codes() -> None:
    if not _require_inprocess_ai():
        return

    cases = (
        (402, "no credits", "AI_NO_CREDITS", "На балансе нет средств"),
        (429, "slow down", "AI_RATE_LIMIT", "Превышен лимит запросов"),
        (500, "boom", "AI_PROVIDER_ERROR", None),
    )

    for provider_status, provider_body, expected_code, expected_message in cases:
        session = FakeSession().route(
            "GET", "/models", error_response(provider_status, provider_body)
        ).route("POST", "/chat/completions", error_response(provider_status, provider_body))

        with running_panel(session) as (panel, _):
            status, raw, _ = call(
                panel, "POST", "/api/ai/key", body={"apiKey": "sk-live-abcdefghijklmnop"}
            )
            error = error_payload(raw)
            assert error["code"] == expected_code, f"HTTP {provider_status}: {error}"
            if expected_message is not None:
                assert error["message"] == expected_message


def test_ai_key_test_does_not_save() -> None:
    if not _require_inprocess_ai():
        return

    with running_panel(_ai_session_with_key()) as (panel, tmp):
        status, raw, _ = call(
            panel, "POST", "/api/ai/key/test", body={"apiKey": "sk-live-abcdefghijklmnop"}
        )
        assert status == 200
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AiKeyTestResult"), payload)
        assert payload["ok"] is True
        assert payload["keyMask"] == "sk-...mnop"
        assert payload["models"] == ["gpt-4o-mini"]

        assert not (tmp / "ai.json").exists(), "проверка ключа ничего не сохраняет"


def test_ai_key_delete_and_owner_key() -> None:
    if not _require_inprocess_ai():
        return

    with running_panel(_ai_session_with_key()) as (panel, _):
        call(panel, "POST", "/api/ai/key", body={"apiKey": "sk-live-abcdefghijklmnop"})

        status, raw, _ = call(panel, "DELETE", "/api/ai/key")
        assert status == 200
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AiStatus"), payload)
        assert payload["cloud"]["keySaved"] is False
        assert payload["cloud"]["keyMask"] == ""
        assert payload["activeProvider"] == "none"


def test_ai_settings_update_matches_spec() -> None:
    if not _require_inprocess_ai():
        return

    with running_panel(_ai_session_with_local()) as (panel, _):
        status, raw, _ = call(
            panel,
            "POST",
            "/api/ai/settings",
            body={"mode": "local", "localModel": "qwen2.5:1.5b", "localBaseUrl": "http://127.0.0.1:11434/v1"},
        )
        assert status == 200
        payload = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AiStatus"), payload)
        assert payload["mode"] == "local"
        assert payload["local"]["model"] == "qwen2.5:1.5b"
        # Модели нет среди локальных — панель честно это показывает.
        assert payload["local"]["modelInstalled"] is False
        assert payload["local"]["statusText"] == "Локальная модель недоступна"


def test_ai_local_status_and_test() -> None:
    if not _require_inprocess_ai():
        return

    with running_panel(_ai_session_with_local()) as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/ai/local")
        assert status == 200
        local = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AiLocalStatus"), local)
        assert local["server"] == "up"
        assert local["api"] == "ollama"
        assert local["models"] == [DEFAULT_LOCAL_MODEL]

        status, raw, _ = call(panel, "POST", "/api/ai/local/test", body={})
        assert status == 200
        result = json.loads(raw.decode("utf-8"))
        assert_schema(schema("AiLocalTestResult"), result)
        assert result["ok"] is True


def test_ai_local_errors_are_friendly() -> None:
    if not _require_inprocess_ai():
        return

    # Сервер выключен.
    with running_panel() as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/ai/local/test", body={})
        assert status == 400
        error = error_payload(raw)
        assert error["code"] == "AI_LOCAL_SERVER_DOWN"
        assert error["message"] == "Локальный сервер не запущен"

    # Сервер запущен, нужной модели нет.
    session = FakeSession().route("GET", "/api/tags", ollama_tags_response(["llama3.2:3b"]))
    with running_panel(session) as (panel, _):
        status, raw, _ = call(panel, "POST", "/api/ai/local/test", body={})
        assert status == 400
        error = error_payload(raw)
        assert error["code"] == "AI_LOCAL_MODEL_MISSING"
        assert f"ollama pull {DEFAULT_LOCAL_MODEL}" in error["message"]


def test_ai_local_pull_streams_progress() -> None:
    if not _require_inprocess_ai():
        return

    session = _ai_session_with_local().route(
        "POST",
        "/api/pull",
        ollama_pull_response(
            [
                '{"status":"pulling manifest"}',
                '{"status":"downloading","total":100,"completed":40}',
                '{"status":"success"}',
            ]
        ),
    )

    with running_panel(session) as (panel, _):
        status, raw, headers = call(panel, "GET", "/api/ai/local/pull?model=qwen3.5:2b")
        assert status == 200
        assert headers.get("content-type", "").startswith("text/event-stream")

        events = parse_sse(raw)
        names = [name for name, _ in events]
        assert names == ["progress", "progress", "progress", "done"]

        assert_schema(schema("AiPullEvent"), {"event": "progress", "data": events[1][1]})
        assert events[1][1]["percent"] == 40.0
        assert events[-1][1]["model"] == "qwen3.5:2b"


def test_ai_pull_unauthorized_and_bad_model() -> None:
    """401 и недопустимое имя модели безопасны для обеих редакций.

    Сам поток загрузки на настоящей панели не открываем: он скачивал бы
    модель в Ollama пользователя (внутрипроцессный прогон — с фейком).
    """
    if EXTERNAL:
        with running_panel() as (panel, _):
            status, raw, _ = call(panel, "GET", "/api/ai/local/pull", token=None)
            assert status == 401

            status, raw, _ = call(panel, "GET", "/api/ai/local/pull?model=плохое имя")
            assert status == 400
            assert error_payload(raw)["code"] == "VALIDATION_ERROR"
        return

    with running_panel(_ai_session_with_local()) as (panel, _):
        status, raw, _ = call(panel, "GET", "/api/ai/local/pull", token=None)
        assert status == 401

        status, raw, _ = call(panel, "GET", "/api/ai/local/pull?model=плохое имя")
        assert status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"


def test_ai_rejects_bad_payloads() -> None:
    cases = (
        ("POST", "/api/ai/settings", {}, "Не задано ни одного поля настроек ИИ."),
        ("POST", "/api/ai/settings", {"mode": "магия"}, None),
        ("POST", "/api/ai/settings", {"localBaseUrl": "не-адрес"}, None),
        ("POST", "/api/ai/settings", {"unknown": 1}, None),
        ("POST", "/api/ai/key", {}, None),
        ("POST", "/api/ai/key", {"apiKey": "   "}, None),
        ("POST", "/api/ai/key", {"apiKey": "sk-live-x", "unknown": 1}, None),
        ("POST", "/api/ai/key/test", {"apiKey": 42}, None),
        ("POST", "/api/ai/local/test", {"localModel": ""}, None),
        ("POST", "/api/ai/local/test", {"localBaseUrl": "ftp://x"}, None),
    )

    with running_panel(_ai_session_with_key()) as (panel, _):
        for method, path, body, message in cases:
            status, raw, _ = call(panel, method, path, body=body)
            assert status == 400, f"{method} {path} {body}"
            error = error_payload(raw)
            assert_schema(schema("Error"), error)
            assert error["code"] == "VALIDATION_ERROR", f"{path}: {error}"
            if message is not None:
                assert error["message"] == message


def test_ai_bad_json_body_is_rejected() -> None:
    with running_panel(_ai_session_with_key()) as (panel, _):
        conn = http.client.HTTPConnection("127.0.0.1", panel.port, timeout=15)
        conn.request(
            "POST",
            "/api/ai/key",
            body=b"{not json",
            headers={"X-ZERE-Token": panel.token, "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        assert response.status == 400
        assert error_payload(raw)["code"] == "VALIDATION_ERROR"


def test_ai_requires_token() -> None:
    with running_panel(_ai_session_with_key()) as (panel, _):
        for method, path in (
            ("GET", "/api/ai"),
            ("POST", "/api/ai/settings"),
            ("POST", "/api/ai/key"),
            ("DELETE", "/api/ai/key"),
            ("POST", "/api/ai/key/test"),
            ("GET", "/api/ai/local"),
            ("POST", "/api/ai/local/test"),
            ("GET", "/api/ai/local/pull"),
        ):
            status, raw, _ = call(panel, method, path, token="f" * 64)
            assert status == 401, f"{method} {path}"
            assert error_payload(raw)["code"] == "UNAUTHORIZED"


def test_ai_wrong_method_is_405() -> None:
    with running_panel() as (panel, _):
        for method, path in (
            ("POST", "/api/ai"),
            ("GET", "/api/ai/settings"),
            ("GET", "/api/ai/key"),
            ("GET", "/api/ai/key/test"),
            ("POST", "/api/ai/local"),
            ("GET", "/api/ai/local/test"),
            ("POST", "/api/ai/local/pull"),
        ):
            status, raw, _ = call(panel, method, path)
            assert status == 405, f"{method} {path}"
            assert error_payload(raw)["code"] == "METHOD_NOT_ALLOWED"


def test_ai_chat_without_provider_is_covered_by_unit_tests() -> None:
    """Требование 5 (сообщение в чате) проверяется на уровне сервиса ИИ.

    Контрактные тесты панели подменяют engine фейком (FakeEngine), который
    не ходит в AIHandler, поэтому сообщение «Чтобы начать, введите API-ключ
    или установите локальную модель» проверяет tests/test_ai_providers.py
    на реальном AiService (там же — приоритет облако → локальная модель).
    """
    if not _require_inprocess_ai():
        return

    with running_panel() as (panel, _):
        assert panel.ai.generate("привет") == MESSAGE_NOT_CONFIGURED


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} контрактных тестов")


if __name__ == "__main__":
    main()
