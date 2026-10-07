"""Локальная панель ZERE: HTTP API (этап 1 «API-ядро»).

Контракт: docs/api/openapi.yaml. Правила безопасности (§6 плана):

- слушаем только 127.0.0.1 (loopback-only);
- Host должен быть 127.0.0.1/localhost — защита от DNS-rebinding;
- Origin, если задан, — только собственный — защита от CSRF;
- каждый запрос требует заголовок X-ZERE-Token (config/panel.token);
- ошибки нормализованы: {code, message} — без сырых исключений и путей.
"""

from __future__ import annotations

import enum
import hmac
import json
import mimetypes
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from zere import paths
from zere.ai.ai_service import AiService
from zere.ai.ai_settings import MODES, PROVIDER_IDS
from zere.ai.cloud_client import AiError
from zere.api.token import load_or_create_token
from zere.ai.ollama_url_resolver import OllamaUrlResolver
from zere.core.configuration.zere_config import ZereConfig
from zere.core.logging.log_service import log_error, redact_secrets
from zere.core.plugins.plugin_config import PluginConfig
from zere.core.update.updater import UpdateBusyError, UpdateService
# Только раннер: он тянет лишь log_error/threading — сервер панели
# по-прежнему собирается без тяжёлых голосовых зависимостей (Whisper/ChatTTS).
from zere.voice.voice_mode import VoiceModeRunner
# Только enum: сам SafeActionManager тянет psutil (ProcessService),
# а сервер панели обязан собираться без голосовых/системных зависимостей.
from zere.tools.windows.pending_action import PendingAction

DEFAULT_PORT = 8080
_MAX_BODY_BYTES = 64 * 1024
_MAX_TEXT_LENGTH = 4000

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
_ALLOWED_TTS_ENGINES = ("pocket", "chattts")
# STT: gigaam — GigaAM-v3 (основной), whisper — откат
# (отчёт docs/STT_ENGINE_RESEARCH.md, §5).
_ALLOWED_STT_ENGINES = ("gigaam", "whisper")

# Путь → допустимые методы (маршрутизация до проверки токена не доходит).
_ROUTES = {
    "/api/health": frozenset({"GET"}),
    "/api/config": frozenset({"GET", "POST"}),
    "/api/chat/stream": frozenset({"GET"}),
    "/api/personality": frozenset({"GET"}),
    "/api/personality/set": frozenset({"POST"}),
    "/api/history": frozenset({"GET", "DELETE"}),
    "/api/memory": frozenset({"GET", "POST"}),
    "/api/processes": frozenset({"GET"}),
    "/api/apps": frozenset({"GET"}),
    "/api/apps/reindex": frozenset({"POST"}),
    "/api/logs": frozenset({"GET"}),
    "/api/plugins": frozenset({"GET"}),
    "/api/voice": frozenset({"GET", "POST"}),
    "/api/voice/mode": frozenset({"GET", "POST"}),
    "/api/voice/reference": frozenset({"POST"}),
    "/api/voice/test": frozenset({"POST"}),
    "/api/voice/listen": frozenset({"POST"}),
    # Обновление из GitHub: статус (кэш) → проверка → применение.
    "/api/update": frozenset({"GET"}),
    "/api/update/check": frozenset({"POST"}),
    "/api/update/apply": frozenset({"POST"}),
    # ИИ: облачный ключ пользователя или локальная модель (docs/AI_PROVIDERS.md).
    #   GET    /api/ai            — состояние подключения ИИ;
    #   POST   /api/ai/settings   — режим авто/облако/локально, адреса, модели;
    #   POST   /api/ai/key        — проверка + сохранение ключа;
    #   DELETE /api/ai/key        — удаление ключа пользователя;
    #   POST   /api/ai/key/test   — «Проверить ключ» без сохранения;
    #   GET    /api/ai/local      — запущен ли локальный сервер, какие модели;
    #   POST   /api/ai/local/test — тестовый запрос к локальной модели;
    #   GET    /api/ai/local/pull — SSE-прогресс загрузки модели (Ollama).
    "/api/ai": frozenset({"GET"}),
    "/api/ai/settings": frozenset({"POST"}),
    "/api/ai/key": frozenset({"POST", "DELETE"}),
    "/api/ai/key/test": frozenset({"POST"}),
    "/api/ai/local": frozenset({"GET"}),
    "/api/ai/local/test": frozenset({"POST"}),
    "/api/ai/local/pull": frozenset({"GET"}),
}

_MEMORY_PREFIX = "/api/memory/"
# Динамические маршруты подтверждаемых действий (этап 4 плана, §6):
#   POST /api/processes/{pid}/kill — двухшаговый подтверждённый запрос;
#   POST /api/power/{action}       — питание через SafeActionManager.
_KILL_PREFIX = "/api/processes/"
_KILL_SUFFIX = "/kill"
_POWER_PREFIX = "/api/power/"
_TTL_SECONDS = 60  # тот же срок, что у SafeActionManager (серверная проверка)
_MAX_PROCESS_QUERY_LENGTH = 100
_MAX_PID = 2_147_483_647  # int32, как int.TryParse в C#-реализации
_MAX_APP_QUERY_LENGTH = 200
_LOG_DEFAULT_LIMIT = 50
_LOG_MAX_LIMIT = 500
_LOG_LEVELS = ("info", "warn", "error")
_MAX_VOICE_TEST_LENGTH = 500
_POWER_ACTIONS = ("shutdown", "restart", "sleep")
_PENDING_BY_ACTION = {
    "shutdown": PendingAction.SHUTDOWN,
    "restart": PendingAction.RESTART,
    "sleep": PendingAction.SLEEP,
}
_HISTORY_DEFAULT_LIMIT = 50
_HISTORY_MAX_LIMIT = 500
_MAX_HISTORY_SEARCH_LENGTH = 200
_MAX_MEMORY_KEY_LENGTH = 200
_MAX_MEMORY_VALUE_LENGTH = 2000
_MAX_MEMORY_CATEGORY_LENGTH = 100


class PanelServer:
    """HTTP-сервер панели: статусы, конфигурация, SSE-чат, личности."""

    def __init__(
        self,
        engine: Any,
        config: ZereConfig,
        memory: Any,
        *,
        conversation: Optional[Any] = None,
        plugin_config: Optional[PluginConfig] = None,
        process_service: Optional[Any] = None,
        safe_actions: Optional[Any] = None,
        app_launcher: Optional[Any] = None,
        voice: Optional[Any] = None,
        runtime: Optional[Any] = None,
        updater: Optional[Any] = None,
        ai: Optional[Any] = None,
        token: Optional[str] = None,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._engine = engine
        self._config = config
        self._memory = memory
        self._conversation = conversation
        self._plugin_config = plugin_config
        self._process_service = process_service
        self._safe_actions = safe_actions
        self._app_launcher = app_launcher
        self._voice = voice
        # Непрерывный голосовой режим (POST /api/voice/mode): цикл живёт
        # фоновым потоком, обработка — тот же engine, что и в /api/chat/stream
        # (позднее связывание: текстовые реплики панели и голосовые идут
        # в одну историю разговоров).
        self._voice_mode = (
            VoiceModeRunner(voice, lambda text: engine.process(text), runtime)
            if voice is not None
            else None
        )
        self._token = token if token is not None else load_or_create_token()
        # Обновление из GitHub (docs/UPDATE.md): сервис с кэшем состояния;
        # в тестах и E2E подменяется фейком — сеть и рабочая копия не трогаются.
        self._updater = updater if updater is not None else UpdateService()
        # Настройки ИИ (облачный ключ / локальная модель). None — сервис
        # создаётся лениво при первом обращении (тесты подменяют его фейком),
        # поэтому отсутствие Ollama или сети не мешает старту панели.
        self._ai = ai
        self._requested_port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[Thread] = None
        # Одноразовый токен подтверждения (kill/power): (token, action, issued_at).
        self._challenge_lock = Lock()
        self._challenge: Optional[tuple[str, str, float]] = None

    # ── Доступ из обработчика ─────────────────────────────────────

    @property
    def engine(self) -> Any:
        return self._engine

    @property
    def config(self) -> ZereConfig:
        return self._config

    @property
    def memory(self) -> Any:
        return self._memory

    @property
    def conversation(self) -> Optional[Any]:
        return self._conversation

    @property
    def plugin_config(self) -> Optional[PluginConfig]:
        return self._plugin_config

    @property
    def process_service(self) -> Optional[Any]:
        return self._process_service

    @property
    def safe_actions(self) -> Optional[Any]:
        return self._safe_actions

    @property
    def app_launcher(self) -> Optional[Any]:
        return self._app_launcher

    @property
    def voice(self) -> Optional[Any]:
        return self._voice

    @property
    def voice_mode(self) -> Optional[VoiceModeRunner]:
        """Раннер непрерывного голосового режима (None — голоса нет)."""
        return self._voice_mode

    @property
    def updater(self) -> Any:
        """Сервис обновления из GitHub (UpdateService или фейк в тестах)."""
        return self._updater

    @property
    def ai(self) -> Any:
        """Сервис выбора провайдера ИИ (AiService или фейк в тестах).

        Создаётся лениво: сервер панели не должен трогать сеть/локальные
        серверы при старте, если пользователь не открыл настройки ИИ.
        """
        if self._ai is None:
            self._ai = AiService(config=self._config)
        return self._ai

    # ── Подтверждения опасных действий (серверный TTL, P0-3) ──────

    def issue_challenge(self, action: str) -> str:
        """Одноразовый токен подтверждения; живёт не дольше _TTL_SECONDS.

        Новый токен аннулирует предыдущий: одна незавершённая операция на панель.
        """
        token = secrets.token_hex(16)
        with self._challenge_lock:
            self._challenge = (token, action, time.monotonic())
        return token

    def consume_challenge(self, token: Any, action: str) -> Optional[tuple[str, str]]:
        """Проверяет и гасит токен. None — годен; иначе (код, сообщение)."""
        if (
            not isinstance(token, str)
            or len(token) != 32
            or any(char not in "0123456789abcdef" for char in token)
        ):
            return "VALIDATION_ERROR", "Некорректный ttlToken."

        with self._challenge_lock:
            challenge = self._challenge
            self._challenge = None  # гасим в любом случае: токен одноразовый

        if challenge is None or challenge[0] != token:
            return "TTL_EXPIRED", "Нет действия, ожидающего подтверждения."

        issued_token, issued_action, issued_at = challenge

        if issued_action != action:
            return "TTL_EXPIRED", "Подтверждение относится к другому действию."

        if time.monotonic() - issued_at > _TTL_SECONDS:
            return "TTL_EXPIRED", "Срок подтверждения истёк — запросите действие заново."

        return None

    @property
    def token(self) -> str:
        return self._token

    @property
    def port(self) -> int:
        if self._httpd is not None:
            return int(self._httpd.server_address[1])
        return self._requested_port

    # ── Управление ────────────────────────────────────────────────

    def start(self) -> None:
        """Запуск в фоновом потоке (неблокирующий)."""
        self._httpd = ThreadingHTTPServer(
            ("127.0.0.1", self._requested_port),  # только loopback
            _PanelHandler,
        )
        self._httpd.daemon_threads = True
        self._httpd.panel = self  # обработчик читает сервер сюда

        self._thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

        # Автопроверка обновлений при старте — фоном, чтобы старт не ждал сеть.
        self._start_update_probe()

    def _start_update_probe(self) -> None:
        """Проверка обновлений в фоне (единственный сетевой вызов панели).

        Сбой (нет сети, нет git, закрытый ключ) не мешает работе: причина
        остаётся в статусе `/api/update`, панель показывает её как ошибку.
        """

        def probe() -> None:
            try:
                status = self._updater.check()
            except Exception as ex:  # noqa: BLE001 — фон не должен падать
                log_error("PanelServer", f"Проверка обновлений: {ex}")
                return

            if status.get("updateAvailable"):
                print(
                    f"[Обновление] Доступно {status['behind']} коммитов позади "
                    f"{status['remote']}/{status['branch']} — панель → «Обновления»."
                )

        Thread(target=probe, daemon=True, name="zere-update-check").start()

    def stop(self) -> None:
        # Голосовой режим — фоновый поток с захваченным микрофоном:
        # останавливаем до закрытия сервера (иначе детектор переживёт приложение).
        if self._voice_mode is not None:
            try:
                self._voice_mode.stop(timeout=0.5)
            except Exception as ex:  # noqa: BLE001 — остановка не должна падать
                log_error("PanelServer", f"voice mode stop: {ex}")

        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


class _PanelHandler(BaseHTTPRequestHandler):
    """Один запрос → одна проверка безопасности → один маршрут."""

    # Не раскрываем версию Python в заголовке Server.
    server_version = "ZEREPanel/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    @property
    def panel(self) -> PanelServer:
        return self.server.panel  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 — имя из BaseHTTPRequestHandler
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    # Без собственных обработчиков BaseHTTPRequestHandler отдаёт 501, что
    # расходится с C# (404/405 из таблицы маршрутов) — реализуем все явно.
    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._dispatch("OPTIONS")

    def log_message(self, format: str, *args: Any) -> None:
        pass  # сырой лог запросов не пишем — только нормализованные события

    # ── Безопасность ──────────────────────────────────────────────

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host")
        if host is None:
            return True  # HTTP/1.0-клиент может не прислать Host
        return _host_name(host) in _ALLOWED_HOSTS

    def _origin_allowed(self, port: int) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin in (
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        )

    def _token_allowed(self) -> bool:
        supplied = self.headers.get("X-ZERE-Token", "")
        return hmac.compare_digest(supplied, self.panel.token)

    # ── Диспетчеризация ───────────────────────────────────────────

    def _dispatch(self, method: str) -> None:
        if not self._host_allowed():
            self._send_json(403, "FORBIDDEN_HOST", "Недопустимый Host.")
            return

        if not self._origin_allowed(self.panel.port):
            self._send_json(403, "FORBIDDEN_ORIGIN", "Недопустимый Origin.")
            return

        path = urlsplit(self.path).path

        # Статика панели (panel/dist) — без токена: <link>/<img> не умеют
        # шлить заголовки, а токен в HTML читает только same-origin-страница
        # (SOP), Host/Origin проверяются выше для обоих классов запросов.
        if not path.startswith("/api/"):
            if method != "GET":
                self._send_json(405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.")
                return

            self._handle_static(path)
            return

        if not self._token_allowed():
            self._send_json(401, "UNAUTHORIZED", "Требуется X-ZERE-Token.")
            return

        # Динамический маршрут DELETE /api/memory/{id}
        if path.startswith(_MEMORY_PREFIX):
            if method != "DELETE":
                self._send_json(405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.")
                return

            self._handle_memory_delete(path[len(_MEMORY_PREFIX):])
            return

        # Динамический маршрут POST /api/processes/{pid}/kill
        if path.startswith(_KILL_PREFIX):
            if method != "POST":
                self._send_json(405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.")
                return

            # Нормализуем любую ошибку, как это делает C#-панель (HandleAsync).
            try:
                self._handle_process_kill(path[len(_KILL_PREFIX):])
            except Exception as ex:  # noqa: BLE001
                log_error("PanelServer", str(ex))
                self._send_json(500, "INTERNAL", "Внутренняя ошибка сервера.")
            return

        # Динамический маршрут POST /api/power/{action}
        if path.startswith(_POWER_PREFIX):
            if method != "POST":
                self._send_json(405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.")
                return

            try:
                self._handle_power(path[len(_POWER_PREFIX):])
            except Exception as ex:  # noqa: BLE001
                log_error("PanelServer", str(ex))
                self._send_json(500, "INTERNAL", "Внутренняя ошибка сервера.")
            return

        allowed = _ROUTES.get(path)
        if allowed is None:
            self._send_json(404, "NOT_FOUND", "Маршрут не найден.")
            return

        if method not in allowed:
            self._send_json(405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.")
            return

        try:
            if path == "/api/health":
                self._handle_health()
            elif path == "/api/config":
                if method == "GET":
                    self._handle_config_get()
                else:
                    self._handle_config_post()
            elif path == "/api/personality":
                self._handle_personality_get()
            elif path == "/api/personality/set":
                self._handle_personality_set()
            elif path == "/api/history":
                if method == "GET":
                    self._handle_history_get()
                else:
                    self._handle_history_delete()
            elif path == "/api/memory":
                if method == "GET":
                    self._handle_memory_get()
                else:
                    self._handle_memory_post()
            elif path == "/api/processes":
                self._handle_processes_get()
            elif path == "/api/apps":
                self._handle_apps_get()
            elif path == "/api/apps/reindex":
                self._handle_apps_reindex()
            elif path == "/api/logs":
                self._handle_logs_get()
            elif path == "/api/plugins":
                self._handle_plugins_get()
            elif path == "/api/voice":
                if method == "GET":
                    self._handle_voice_get()
                else:
                    self._handle_voice_post()
            elif path == "/api/voice/reference":
                self._handle_voice_reference()
            elif path == "/api/voice/test":
                self._handle_voice_test()
            elif path == "/api/voice/listen":
                self._handle_voice_listen()
            elif path == "/api/voice/mode":
                if method == "GET":
                    self._handle_voice_mode_get()
                else:
                    self._handle_voice_mode_post()
            elif path == "/api/update":
                self._handle_update_get()
            elif path == "/api/update/check":
                self._handle_update_check()
            elif path == "/api/update/apply":
                self._handle_update_apply()
            elif path == "/api/ai":
                self._handle_ai_get()
            elif path == "/api/ai/settings":
                self._handle_ai_settings()
            elif path == "/api/ai/key":
                if method == "POST":
                    self._handle_ai_key_post()
                else:
                    self._handle_ai_key_delete()
            elif path == "/api/ai/key/test":
                self._handle_ai_key_test()
            elif path == "/api/ai/local":
                self._handle_ai_local_get()
            elif path == "/api/ai/local/test":
                self._handle_ai_local_test()
            elif path == "/api/ai/local/pull":
                self._handle_ai_local_pull()
            else:  # /api/chat/stream
                self._handle_chat_stream()
        except Exception as ex:  # noqa: BLE001 — нормализуем любую ошибку
            log_error("PanelServer", str(ex))
            self._send_json(500, "INTERNAL", "Внутренняя ошибка сервера.")

    # ── Статика панели (panel/dist) ───────────────────────────────

    def _handle_static(self, path: str) -> None:
        root = paths.PROJECT_ROOT / "panel" / "dist"

        if not root.is_dir():
            self._send_json(
                404, "NOT_FOUND", "Панель не собрана: выполните npm run build в panel/."
            )
            return

        target = _resolve_static_target(root, path)

        if target is None:
            self._send_json(404, "NOT_FOUND", "Ресурс не найден.")
            return

        if target.name == "index.html":
            # Токен подставляется только в HTML (см. §6 плана: UI читает
            # его при загрузке). Кэшировать нельзя — токен может смениться.
            html = target.read_text(encoding="utf-8").replace(
                "__ZERE_TOKEN__", self.panel.token
            )
            self._send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"), cache=False)
            return

        content_type = _static_content_type(target)
        self._send_bytes(200, content_type, target.read_bytes())

    # ── Маршруты API ──────────────────────────────────────────────

    def _handle_health(self) -> None:
        config = self.panel.config

        try:
            ollama = "ok" if OllamaUrlResolver.resolve() else "down"
        except Exception:  # noqa: BLE001 — пробинг не должен ронять статус
            ollama = "down"

        models_dir = paths.whisper_models_dir()
        whisper = (
            "ok"
            if models_dir.is_dir() and any(models_dir.glob("*.bin"))
            else "missing"
        )

        engine_name = config.tts_engine
        if engine_name not in _ALLOWED_TTS_ENGINES:
            engine_name = "chattts"

        try:
            count = len(self.panel.memory.get_all())
        except Exception:  # noqa: BLE001
            count = 0

        self._send_json(
            200,
            None,
            {
                "ollama": ollama,
                "whisper": whisper,
                "tts": {"engine": engine_name, "status": "configured"},
                "memory": {"count": count},
                "version": config.version,
                "branch": _git_branch(),
            },
        )

    def _handle_config_get(self) -> None:
        self._send_json(200, None, self.panel.config.to_camel_dict())

    def _handle_config_post(self) -> None:
        body = self._read_body()
        if body is None:
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON.")
            return

        error = _validate_config_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        config = self.panel.config
        for camel_key, value in payload.items():
            setattr(config, _camel_to_snake(camel_key), value)

        # DSP-обработка озвучки: применяется на лету (читается на каждое
        # предложение), поэтому помимо config.json обновляем живой VoiceConfig.
        voice = self.panel.voice
        if voice is not None and "audioProcessing" in payload:
            voice.config.audio_processing = bool(config.audio_processing)

        config.save()

        self._send_json(200, None, config.to_camel_dict())

    def _handle_personality_get(self) -> None:
        payload = self._personality_payload()

        if payload is None:
            self._send_json(503, "NOT_READY", "Сервис личностей не готов.")
            return

        self._send_json(200, None, payload)

    def _handle_personality_set(self) -> None:
        """Смена стиля с персистом в config/plugins.json (чинит P1-3)."""
        payload_obj = self._personality_payload()

        if payload_obj is None:
            self._send_json(503, "NOT_READY", "Сервис личностей не готов.")
            return

        plugin_config = self.panel.plugin_config
        if plugin_config is None:
            # Без хранилища стиль не сохранится — не применяем, чтобы не
            # обещать пользователю персист, которого не будет.
            self._send_json(503, "NOT_READY", "Хранилище настроек не готово.")
            return

        body = self._read_body()
        if body is None:
            return

        try:
            request = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON.")
            return

        if not isinstance(request, dict):
            self._send_json(400, "VALIDATION_ERROR", "Ожидался JSON-объект {styleId}.")
            return

        for key in request:
            if key != "styleId":
                self._send_json(400, "VALIDATION_ERROR", f"Неизвестный ключ: «{key}».")
                return

        if "styleId" not in request:
            self._send_json(400, "VALIDATION_ERROR", "Отсутствует обязательный ключ: «styleId».")
            return

        style_id = request["styleId"]
        if not isinstance(style_id, str):
            self._send_json(400, "VALIDATION_ERROR", "Ключ «styleId» должен быть строкой.")
            return

        available = list(payload_obj["styles"])
        canonical = next((s for s in available if s.lower() == style_id.lower()), None)

        if canonical is None:
            self._send_json(400, "VALIDATION_ERROR", f"Неизвестный стиль: «{style_id}».")
            return

        active = self._active_personality()
        assert active is not None  # payload_obj уже подтвердил наличие личности
        active.set_style(canonical)

        plugin_config.ActivePersonalityId = payload_obj["activeId"]
        plugin_config.ActivePersonalityStyle = canonical
        PluginConfig.save(plugin_config)

        self._send_json(200, None, self._personality_payload())

    def _active_personality(self) -> Any:
        plugin_manager = getattr(self.panel.engine, "plugin_manager", None)
        if plugin_manager is None:
            return None
        return getattr(plugin_manager, "active_personality", None)

    def _personality_payload(self) -> Optional[dict[str, Any]]:
        """{activeId, activeStyle, styles} — только фактический список стилей."""
        active = self._active_personality()

        if active is None:
            return None

        style = getattr(active, "style", "")
        style_name = style.name if isinstance(style, enum.Enum) else str(style)

        return {
            "activeId": str(getattr(active, "id", "")),
            "activeStyle": style_name,
            "styles": [str(s) for s in active.get_available_styles()],
        }

    def _handle_history_get(self) -> None:
        params = parse_qs(urlsplit(self.path).query)

        limit, error = _query_int(params, "limit", _HISTORY_DEFAULT_LIMIT, 1, _HISTORY_MAX_LIMIT)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        offset, error = _query_int(params, "offset", 0, 0, 10**9)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        search = (params.get("search") or [""])[0]
        if len(search) > _MAX_HISTORY_SEARCH_LENGTH:
            self._send_json(
                400,
                "VALIDATION_ERROR",
                f"Параметр «search» длиннее {_MAX_HISTORY_SEARCH_LENGTH} символов.",
            )
            return

        repo = self.panel.conversation
        if repo is None:
            self._send_json(503, "NOT_READY", "Хранилище истории не готово.")
            return

        items = [
            {
                "id": int(c.id),
                "userMessage": c.user_message,
                "zereResponse": c.zere_response,
                "timestamp": c.timestamp.isoformat(),
            }
            for c in repo.get_page(limit, offset, search)
        ]

        self._send_json(200, None, {"items": items, "total": repo.count(search)})

    def _handle_history_delete(self) -> None:
        """Очистка истории — требует явного подтверждения {confirm: "DELETE"}."""
        body = self._read_body()
        if body is None:
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON.")
            return

        error = _validate_confirm_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        repo = self.panel.conversation
        if repo is None:
            self._send_json(503, "NOT_READY", "Хранилище истории не готово.")
            return

        deleted = repo.count()
        repo.clear_history()

        self._send_json(200, None, {"deleted": deleted})

    def _handle_memory_get(self) -> None:
        params = parse_qs(urlsplit(self.path).query)
        search = (params.get("search") or [""])[0]

        try:
            items = (
                self.panel.memory.search(search) if search else self.panel.memory.get_all()
            )
        except Exception as ex:  # noqa: BLE001
            log_error("PanelServer.memory", str(ex))
            self._send_json(500, "INTERNAL", "Внутренняя ошибка сервера.")
            return

        self._send_json(200, None, {"items": [_memory_item_payload(i) for i in items]})

    def _handle_memory_post(self) -> None:
        body = self._read_body()
        if body is None:
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON.")
            return

        error = _validate_memory_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        try:
            self.panel.memory.remember(
                payload["key"], payload["value"], payload.get("category", "User")
            )
            saved = self.panel.memory.find(payload["key"])
        except Exception as ex:  # noqa: BLE001
            log_error("PanelServer.memory", str(ex))
            self._send_json(500, "INTERNAL", "Внутренняя ошибка сервера.")
            return

        if saved is None:
            self._send_json(503, "NOT_READY", "Хранилище памяти не готово.")
            return

        self._send_json(200, None, _memory_item_payload(saved))

    def _handle_memory_delete(self, raw_id: str) -> None:
        if not (raw_id.isascii() and raw_id.isdigit()):
            self._send_json(400, "VALIDATION_ERROR", "Идентификатор памяти должен быть числом.")
            return

        if not self.panel.memory.forget_by_id(int(raw_id)):
            self._send_json(404, "NOT_FOUND", "Запись памяти не найдена.")
            return

        self._send_json(200, None, {"deleted": True})

    # ── Приложения (этап 4, §6 плана) ─────────────────────────────

    def _handle_apps_get(self) -> None:
        """Индексированные приложения; {q} — подстрочный поиск по имени/алиасам."""
        params = parse_qs(urlsplit(self.path).query)
        query = (params.get("q") or [""])[0]

        if len(query) > _MAX_APP_QUERY_LENGTH:
            self._send_json(
                400,
                "VALIDATION_ERROR",
                f"Параметр «q» длиннее {_MAX_APP_QUERY_LENGTH} символов.",
            )
            return

        launcher = self.panel.app_launcher
        if launcher is None:
            self._send_json(503, "NOT_READY", "Сервис приложений не готов.")
            return

        apps = list(launcher.get_installed_applications().values())
        apps.sort(key=lambda app: (-int(app.priority), str(app.name)))

        if query:
            needle = query.casefold()
            apps = [
                app
                for app in apps
                if needle in str(app.name).casefold()
                or any(needle in str(alias).casefold() for alias in app.aliases)
            ]

        self._send_json(
            200,
            None,
            {"items": [_app_payload(app) for app in apps], "total": len(apps)},
        )

    def _handle_apps_reindex(self) -> None:
        """Полная переиндексация: сканеры реестра/меню/AppPaths/LocalAppData."""
        launcher = self.panel.app_launcher
        if launcher is None:
            self._send_json(503, "NOT_READY", "Сервис приложений не готов.")
            return

        started = time.monotonic()
        launcher.rebuild_index()
        duration_ms = int((time.monotonic() - started) * 1000)

        self._send_json(
            200,
            None,
            {
                "count": len(launcher.get_installed_applications()),
                "durationMs": duration_ms,
            },
        )

    # ── Журнал (этап 4, §6 плана) ─────────────────────────────────

    def _handle_logs_get(self) -> None:
        """Сессионный журнал + errors.log: фильтр по level, пагинация как в истории."""
        params = parse_qs(urlsplit(self.path).query)

        limit, error = _query_int(params, "limit", _LOG_DEFAULT_LIMIT, 1, _LOG_MAX_LIMIT)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        offset, error = _query_int(params, "offset", 0, 0, 10**9)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        level = (params.get("level") or [""])[0]
        if level and level not in _LOG_LEVELS:
            self._send_json(
                400,
                "VALIDATION_ERROR",
                "Параметр level должен быть одним из: info, warn, error.",
            )
            return

        entries = _read_log_entries(paths.LOGS_DIR, level)

        self._send_json(
            200,
            None,
            {"items": entries[offset : offset + limit], "total": len(entries)},
        )

    # ── Плагины (этап 4, §6 плана) ────────────────────────────────

    def _handle_plugins_get(self) -> None:
        """Инвентарь плагинов и активная личность (без флага enabled: его нет)."""
        plugin_manager = self.panel.engine.plugin_manager

        items = [
            {
                "id": str(getattr(plugin, "id", "")),
                "name": str(getattr(plugin, "name", "")),
                "description": str(getattr(plugin, "description", "")),
                "version": str(getattr(plugin, "version", "")),
                "author": str(getattr(plugin, "author", "")),
                "type": _enum_name(getattr(plugin, "type", "")),
            }
            for plugin in plugin_manager.plugins
        ]

        active = plugin_manager.active_personality
        active_payload = None

        if active is not None:
            active_payload = {
                "id": str(getattr(active, "id", "")),
                "style": _enum_name(getattr(active, "style", "")),
            }

        self._send_json(
            200,
            None,
            {
                "items": items,
                # Честное false: пайплайн — 9 фиксированных обработчиков,
                # плагины-обработчики в него не встраиваются.
                "handlersConnected": False,
                "commandHandlersCount": len(plugin_manager.command_handlers),
                "activePersonality": active_payload,
            },
        )

    # ── Голос (этап 4, §6 плана) ──────────────────────────────────

    def _voice_settings(self) -> dict[str, Any]:
        """Читаемые поля голоса из конфигурации (без полей-призраков)."""
        config = self.panel.config

        return {
            "voiceEnabled": bool(config.voice_enabled),
            "voiceVolume": float(config.voice_volume),
            "ttsEngine": str(config.tts_engine),
            "voiceReferencePath": str(config.voice_reference_path),
            "audioProcessing": bool(config.audio_processing),
        }

    def _voice_capabilities(self, voice: Any) -> dict[str, Any]:
        """Что эта реализация умеет фактически (описания — в openapi)."""
        return {
            # Python-порт не записывает референс: у VoiceManager нет метода
            "recordReference": hasattr(voice, "record_voice_reference"),
            "pocketCloning": False,  # PocketTTS только в C#-версии
            "speechSpeedConfig": True,  # ChatTTS получает [speed_N] из speech_speed
            "liveVolumeApply": True,  # громкость читается на каждое воспроизведение
            "sttTest": bool(getattr(voice, "is_voice_available", False)),
        }

    def _require_voice(self) -> Any:
        voice = self.panel.voice

        if voice is None:
            self._send_json(503, "NOT_READY", "Голосовой модуль не готов.")
            return None

        return voice

    def _handle_voice_get(self) -> None:
        voice = self._require_voice()
        if voice is None:
            return

        self._send_json(
            200,
            None,
            {**self._voice_settings(), "capabilities": self._voice_capabilities(voice)},
        )

    def _handle_voice_post(self) -> None:
        """Обновление голоса: громкость и audioProcessing — сразу, остальное после рестарта."""
        voice = self._require_voice()
        if voice is None:
            return

        payload = self._read_json_object()
        if payload is None:
            return

        error = _validate_voice_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        config = self.panel.config
        restart_keys = ("voiceEnabled", "ttsEngine", "voiceReferencePath")
        before = tuple(getattr(config, _camel_to_snake(key)) for key in restart_keys)

        if "voiceVolume" in payload:
            volume = float(payload["voiceVolume"])
            config.voice_volume = volume
            # liveVolumeApply: VoiceConfig читается на каждое воспроизведение
            voice.config.volume = volume

        if "audioProcessing" in payload:
            processing = bool(payload["audioProcessing"])
            config.audio_processing = processing
            # читается на каждое предложение — тоже применяется сразу
            voice.config.audio_processing = processing

        for key in restart_keys:
            if key in payload:
                setattr(config, _camel_to_snake(key), payload[key])

        config.save()

        after = tuple(getattr(config, _camel_to_snake(key)) for key in restart_keys)

        self._send_json(
            200,
            None,
            {**self._voice_settings(), "appliedOnRestart": after != before},
        )

    def _handle_voice_reference(self) -> None:
        """Запись WAV-референса: в C#-версии настоящая, в Python-порте — 503."""
        voice = self._require_voice()
        if voice is None:
            return

        if not self._voice_capabilities(voice)["recordReference"]:
            self._send_json(
                503,
                "NOT_READY",
                "Запись референса голоса недоступна в этой реализации.",
            )
            return

        path_text = voice.record_voice_reference()

        if not path_text:
            self._send_json(503, "NOT_READY", "Не удалось записать референс голоса.")
            return

        self.panel.config.voice_reference_path = str(path_text)
        self.panel.config.save()

        self._send_json(200, None, {"voiceReferencePath": str(path_text)})

    def _handle_voice_test(self) -> None:
        """Синтез фразы: 503, если TTS не инициализирован (как в консоли)."""
        voice = self._require_voice()
        if voice is None:
            return

        payload = self._read_json_object()
        if payload is None:
            return

        for key in payload:
            if key != "text":
                self._send_json(400, "VALIDATION_ERROR", f"Неизвестный ключ: «{key}».")
                return

        text = payload.get("text")

        if not isinstance(text, str):
            self._send_json(400, "VALIDATION_ERROR", "Ключ «text» должен быть строкой.")
            return

        if not text.strip():
            self._send_json(400, "VALIDATION_ERROR", "Ключ «text» не может быть пустым.")
            return

        if len(text) > _MAX_VOICE_TEST_LENGTH:
            self._send_json(
                400,
                "VALIDATION_ERROR",
                f"Ключ «text» длиннее {_MAX_VOICE_TEST_LENGTH} символов.",
            )
            return

        if not getattr(voice, "is_tts_available", False):
            # Причина в тексте ответа: иначе пользователь видел «недоступен» без
            # объяснения (например, ChatTTS не установлен — нужен pip install).
            reason = getattr(voice, "tts_unavailable_reason", "")
            message = "Синтез речи недоступен."
            if reason:
                message = f"Синтез речи недоступен: {reason}"
            self._send_json(503, "NOT_READY", message)
            return

        voice.speak(text)
        self._send_json(200, None, {"status": "ok"})

    def _handle_voice_listen(self) -> None:
        """Тест STT: распознавание одной фразы с микрофона."""
        voice = self._require_voice()
        if voice is None:
            return

        if not getattr(voice, "is_voice_available", False):
            self._send_json(503, "NOT_READY", "Распознавание речи недоступно.")
            return

        text = voice.listen()
        self._send_json(200, None, {"text": str(text)})

    def _require_voice_mode(self) -> Optional[Any]:
        """Раннер голосового режима или 503 (голос к панели не подключён)."""
        if self._require_voice() is None:
            return None

        runner = self.panel.voice_mode
        if runner is None:
            self._send_json(503, "NOT_READY", "Голосовой модуль не готов.")
            return None

        return runner

    def _handle_voice_mode_get(self) -> None:
        """Состояние непрерывного голосового режима (VoiceModeState)."""
        runner = self._require_voice_mode()
        if runner is None:
            return

        self._send_json(200, None, runner.status())

    def _handle_voice_mode_post(self) -> None:
        """Включение/выключение фонового цикла wake word → команда → TTS."""
        runner = self._require_voice_mode()
        if runner is None:
            return

        payload = self._read_json_object()
        if payload is None:
            return

        error = _validate_voice_mode_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        if payload["enabled"]:
            if not runner.start():
                # available=false: STT не установлен — цикл слушать нечим
                self._send_json(
                    503,
                    "NOT_READY",
                    "Распознавание речи недоступно — режим голоса включить нельзя.",
                )
                return
        else:
            runner.stop()

        self._send_json(200, None, runner.status())

    # ── Обновление из GitHub (docs/UPDATE.md) ─────────────────────

    def _handle_update_get(self) -> None:
        """Статус обновления из кэша сервиса: сеть не трогаем.

        Единственный сетевой вызов — автопроверка при старте и POST
        /api/update/check; GET отдаёт последнее известное состояние.
        """
        self._send_json(200, None, self.panel.updater.status())

    def _handle_update_check(self) -> None:
        """Проверка: git fetch удалённой ветки и сравнение с локальным HEAD."""
        try:
            status = self.panel.updater.check()
        except UpdateBusyError as ex:
            self._send_json(409, "UPDATE_BUSY", str(ex))
            return

        self._send_json(200, None, status)

    def _handle_update_apply(self) -> None:
        """Применение: git pull --ff-only текущей ветки (+ зависимости Python).

        `ok: false` в ответе — не ошибка запроса, а отказ с причиной
        (нет обновлений, грязная рабочая копия, расхождение веток).
        """
        body = self._read_body()
        if body is None:
            return

        install_dependencies = True

        if body.strip():
            try:
                payload = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(
                    400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON."
                )
                return

            if not isinstance(payload, dict):
                self._send_json(
                    400, "VALIDATION_ERROR", "Ожидался JSON-объект в теле запроса."
                )
                return

            error = _validate_update_payload(payload)
            if error is not None:
                self._send_json(400, "VALIDATION_ERROR", error)
                return

            install_dependencies = payload.get("installDependencies", True)

        try:
            outcome = self.panel.updater.apply(
                install_dependencies=install_dependencies
            )
        except UpdateBusyError as ex:
            self._send_json(409, "UPDATE_BUSY", str(ex))
            return

        self._send_json(200, None, outcome)

    # ── Процессы и питание (этап 4, §6 плана) ────────────────────

    def _handle_processes_get(self) -> None:
        """Список процессов: {q} — подстрочный поиск по имени."""
        params = parse_qs(urlsplit(self.path).query)
        query = (params.get("q") or [""])[0]

        if len(query) > _MAX_PROCESS_QUERY_LENGTH:
            self._send_json(
                400,
                "VALIDATION_ERROR",
                f"Параметр «q» длиннее {_MAX_PROCESS_QUERY_LENGTH} символов.",
            )
            return

        service = self.panel.process_service
        if service is None:
            self._send_json(503, "NOT_READY", "Сервис процессов не готов.")
            return

        items = service.search(query) if query else service.get_processes()

        self._send_json(
            200,
            None,
            {"items": [_process_payload(info, service) for info in items]},
        )

    def _handle_process_kill(self, raw_path: str) -> None:
        """Завершение процесса в два шага: токен, затем {confirm, ttlToken}."""
        if not raw_path.endswith(_KILL_SUFFIX):
            self._send_json(404, "NOT_FOUND", "Маршрут не найден.")
            return

        pid_text = raw_path[: -len(_KILL_SUFFIX)]
        if not (pid_text.isascii() and pid_text.isdigit()) or not 0 < int(pid_text) <= _MAX_PID:
            self._send_json(400, "VALIDATION_ERROR", "PID должен быть положительным целым числом.")
            return
        pid = int(pid_text)

        payload = self._read_json_object()
        if payload is None:
            return

        service = self.panel.process_service
        if service is None:
            self._send_json(503, "NOT_READY", "Сервис процессов не готов.")
            return

        info = _find_process(service, pid)
        if info is None:
            self._send_json(404, "NOT_FOUND", f"Процесс с PID {pid} не найден.")
            return

        if service.is_protected(info.name):
            self._send_json(400, "PROTECTED", f"Процесс «{info.name}» защищён от завершения.")
            return

        action = f"kill:{pid}"

        # Шаг 1: пустое тело — выдаём одноразовый токен с серверным сроком.
        if payload == {}:
            self._send_json(
                200,
                None,
                {
                    "status": "pending",
                    "pid": pid,
                    "name": info.name,
                    "ttlToken": self.panel.issue_challenge(action),
                    "expiresInSeconds": _TTL_SECONDS,
                },
            )
            return

        # Шаг 2: подтверждение.
        error = _validate_ttl_payload(payload, "KILL")
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        problem = self.panel.consume_challenge(payload["ttlToken"], action)
        if problem is not None:
            code, message = problem
            self._send_json(400, code, message)
            return

        # Повторная проверка: PID могли переиспользовать за время диалога.
        info = _find_process(service, pid)
        if info is None:
            self._send_json(404, "NOT_FOUND", f"Процесс с PID {pid} не найден.")
            return

        if service.is_protected(info.name):
            self._send_json(400, "PROTECTED", f"Процесс «{info.name}» защищён от завершения.")
            return

        if not service.kill_pid(pid):
            self._send_json(404, "NOT_FOUND", "Процесс не найден или уже завершён.")
            return

        self._send_json(200, None, {"status": "killed", "pid": pid, "name": info.name})

    def _handle_power(self, action: str) -> None:
        """Питание через штатный SafeActionManager + серверный TTL."""
        if action not in _POWER_ACTIONS:
            self._send_json(404, "NOT_FOUND", "Неизвестное действие питания.")
            return

        safe = self.panel.safe_actions
        if safe is None:
            self._send_json(503, "NOT_READY", "Сервис питания не готов.")
            return

        payload = self._read_json_object()
        if payload is None:
            return

        # Шаг 1: команда поставлена в очередь подтверждения, токен выдан.
        if payload == {}:
            safe.request(_PENDING_BY_ACTION[action])
            self._send_json(
                200,
                None,
                {
                    "status": "pending",
                    "action": action,
                    "ttlToken": self.panel.issue_challenge(f"power:{action}"),
                    "expiresInSeconds": _TTL_SECONDS,
                },
            )
            return

        error = _validate_ttl_payload(payload, "POWER")
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        problem = self.panel.consume_challenge(payload["ttlToken"], f"power:{action}")
        if problem is not None:
            code, message = problem
            self._send_json(400, code, message)
            return

        # Шаг 2: второй TTL — внутри самого SafeActionManager.
        # Сравнение по .value: тянуть ConfirmOutcome в сервер нельзя,
        # его модуль импортирует ProcessService (psutil).
        outcome = str(getattr(safe.confirm(), "value", ""))

        if outcome == "executed":
            self._send_json(200, None, {"status": "executed", "action": action})
        elif outcome == "failed":
            self._send_json(200, None, {"status": "failed", "action": action})
        else:  # expired / no_pending
            self._send_json(
                400, "TTL_EXPIRED", "Срок подтверждения истёк — запросите действие заново."
            )

    def _handle_chat_stream(self) -> None:
        params = parse_qs(urlsplit(self.path).query)
        text = (params.get("text") or [""])[0]

        if not text.strip():
            self._send_json(400, "VALIDATION_ERROR", "Параметр text обязателен.")
            return

        if len(text) > _MAX_TEXT_LENGTH:
            self._send_json(
                400,
                "VALIDATION_ERROR",
                f"Текст слишком длинный (максимум {_MAX_TEXT_LENGTH} символов).",
            )
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        try:
            answer = self.panel.engine.process(text)
        except Exception as ex:  # noqa: BLE001 — сырую ошибку клиенту не показываем
            log_error("PanelServer.chat", str(ex))
            self._write_event("error", {"code": "INTERNAL", "message": "Не удалось обработать запрос."})
        else:
            # Этап 1: полный ответ одним событием token; потоковая токенизация
            # появится, когда OllamaClient откроет посимвольный стриминг.
            self._write_event("token", {"text": answer})
            self._write_event("done", {"answer": answer})

        self.close_connection = True

    # ── ИИ: облачный ключ пользователя и локальная модель ─────────

    def _handle_ai_get(self) -> None:
        """GET /api/ai — состояние подключения ИИ (без секретов)."""
        self._send_json(200, None, self.panel.ai.status())

    def _handle_ai_settings(self) -> None:
        """POST /api/ai/settings — режим (авто/облако/локально), адреса, модели."""
        payload = self._read_json_object()
        if payload is None:
            return

        error = _validate_ai_settings_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        try:
            status = self.panel.ai.update_settings(payload)
        except AiError as ex:
            self._send_json(ex.status, ex.code, ex.message)
            return

        self._send_json(200, None, status)

    def _handle_ai_key_post(self) -> None:
        """POST /api/ai/key — проверить рабочим запросом и сохранить ключ."""
        payload = self._read_json_object()
        if payload is None:
            return

        error = _validate_ai_key_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        validate = payload.get("validate", True)
        try:
            status = self.panel.ai.save_key(payload, validate=bool(validate))
        except AiError as ex:
            # Ключ не сохранён: клиент видит понятную причину
            # (AI_KEY_INVALID / AI_NO_CREDITS / AI_RATE_LIMIT / ...).
            self._send_json(ex.status, ex.code, ex.message)
            return

        self._send_json(200, None, status)

    def _handle_ai_key_delete(self) -> None:
        """DELETE /api/ai/key — удалить ключ пользователя (ключ владельца не трогаем)."""
        self._send_json(200, None, self.panel.ai.delete_key())

    def _handle_ai_key_test(self) -> None:
        """POST /api/ai/key/test — «Проверить ключ» без сохранения."""
        payload = self._read_json_object()
        if payload is None:
            return

        error = _validate_ai_key_test_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        try:
            result = self.panel.ai.test_key(payload)
        except AiError as ex:
            self._send_json(ex.status, ex.code, ex.message)
            return

        self._send_json(200, None, result)

    def _handle_ai_local_get(self) -> None:
        """GET /api/ai/local — запущен ли сервер, какие модели, есть ли нужная."""
        self._send_json(200, None, self.panel.ai.local_status())

    def _handle_ai_local_test(self) -> None:
        """POST /api/ai/local/test — минимальный запрос к локальной модели."""
        payload = self._read_json_object()
        if payload is None:
            return

        error = _validate_ai_local_payload(payload)
        if error is not None:
            self._send_json(400, "VALIDATION_ERROR", error)
            return

        try:
            result = self.panel.ai.test_local(payload)
        except AiError as ex:
            self._send_json(ex.status, ex.code, ex.message)
            return

        self._send_json(200, None, result)

    def _handle_ai_local_pull(self) -> None:
        """GET /api/ai/local/pull?model=... — SSE-прогресс загрузки модели.

        Работает только с Ollama (нативный /api/pull): для прочих локальных
        серверов приходит событие error с понятным текстом.
        """
        params = parse_qs(urlsplit(self.path).query)
        model = (params.get("model") or [""])[0].strip()

        if model and not re.fullmatch(r"[A-Za-z0-9._\-/:]{1,120}", model):
            self._send_json(400, "VALIDATION_ERROR", "Недопустимое имя модели.")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        try:
            for event in self.panel.ai.pull_model(model or None):
                status = event.get("status")

                if status == "error":
                    self._write_event(
                        "error",
                        {
                            "code": event.get("code", "AI_PULL_FAILED"),
                            "message": event.get("message", "Не удалось скачать модель."),
                        },
                    )
                elif status == "done":
                    self._write_event("done", {"model": event.get("model", model)})
                else:
                    self._write_event(
                        "progress",
                        {
                            "percent": event.get("percent"),
                            "completed": event.get("completed"),
                            "total": event.get("total"),
                            "detail": event.get("detail", ""),
                        },
                    )
        except Exception as ex:  # noqa: BLE001 — поток не должен рвать соединение
            log_error("PanelServer.ai.pull", redact_secrets(str(ex)))
            self._write_event(
                "error", {"code": "INTERNAL", "message": "Не удалось скачать модель."}
            )

        self.close_connection = True

    # ── Помощники ─────────────────────────────────────────────────

    def _read_json_object(self) -> Optional[dict[str, Any]]:
        """Тело запроса как JSON-объект; None — ответ с ошибкой уже отправлен."""
        body = self._read_body()
        if body is None:
            return None

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON.")
            return None

        if not isinstance(payload, dict):
            self._send_json(400, "VALIDATION_ERROR", "Ожидался JSON-объект в теле запроса.")
            return None

        return payload

    def _read_body(self) -> Optional[bytes]:
        length_text = self.headers.get("Content-Length", "0")
        try:
            length = int(length_text)
        except ValueError:
            length = -1

        if length < 0 or length > _MAX_BODY_BYTES:
            self._send_json(400, "VALIDATION_ERROR", "Недопустимый размер тела запроса.")
            return None

        return self.rfile.read(length)

    def _send_json(self, status: int, code: Optional[str], payload: Any) -> None:
        if code is not None:
            payload = {"code": code, "message": payload}

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body, cache=False)

    def _send_bytes(
        self, status: int, content_type: str, body: bytes, *, cache: bool = True
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))

        if not cache:
            self.send_header("Cache-Control", "no-store")

        self.end_headers()
        self.wfile.write(body)

    def _write_event(self, event: str, data: dict[str, Any]) -> None:
        chunk = (
            f"event: {event}\n"
            f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        ).encode("utf-8")
        self.wfile.write(chunk)
        self.wfile.flush()


# ── Функции-помощники ─────────────────────────────────────────────


def _resolve_static_target(root: Path, path: str) -> Optional[Path]:
    """Безопасное разрешение пути внутри panel/dist (без выхода наружу)."""
    relative = unquote(path.lstrip("/")) or "index.html"
    parts = [part for part in relative.split("/") if part not in ("", ".")]

    if not parts or any(part == ".." for part in parts):
        return None

    try:
        resolved_root = root.resolve()
        candidate = (root.joinpath(*parts)).resolve()
    except OSError:
        return None

    if candidate != resolved_root and resolved_root not in candidate.parents:
        return None  # выход за пределы каталога статики

    if candidate.is_dir():
        index = candidate / "index.html"
        return index if index.is_file() else None

    if candidate.is_file():
        return candidate

    # SPA-фоллбэк: маршруты без расширения отдают index.html (роутер сам)
    if "." not in Path(parts[-1]).name:
        index = resolved_root / "index.html"
        return index if index.is_file() else None

    return None


_TEXTUAL_TYPES = ("text/", "application/javascript", "image/svg+xml")


def _static_content_type(target: Path) -> str:
    content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"

    if content_type.startswith(_TEXTUAL_TYPES) and "charset" not in content_type:
        return f"{content_type}; charset=utf-8"

    return content_type


def _host_name(host: str) -> str:
    """Имя хоста из заголовка Host без порта (учитывает IPv6-литерал)."""
    host = host.strip()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end > 0 else host
    if host.count(":") == 1:
        name, _, port = host.partition(":")
        if port.isdigit():
            return name
    return host


def _git_branch() -> str:
    """Ветка из .git/HEAD — без запуска shell (см. P1-6 отчёта)."""
    try:
        text = (paths.PROJECT_ROOT / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"

    prefix = "ref: refs/heads/"
    if text.startswith(prefix):
        return text[len(prefix):]
    return "detached" if text else "unknown"


def _query_int(
    params: dict[str, list[str]],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> tuple[int, Optional[str]]:
    """Целочисленный query-параметр: (значение, ошибка)."""
    raw = params.get(name)

    if raw is None or raw[0] == "":
        return default, None

    try:
        value = int(raw[0])
    except ValueError:
        return default, f"Параметр «{name}» должен быть целым числом."

    if not minimum <= value <= maximum:
        return default, f"Параметр «{name}» должен быть в диапазоне {minimum}…{maximum}."

    return value, None


def _validate_confirm_payload(payload: Any) -> Optional[str]:
    """Подтверждение необратимого действия: ровно {confirm: "DELETE"}."""
    if not isinstance(payload, dict):
        return 'Ожидался JSON-объект {confirm: "DELETE"}.'

    for key in payload:
        if key != "confirm":
            return f"Неизвестный ключ: «{key}»."

    if "confirm" not in payload:
        return "Отсутствует обязательный ключ: «confirm»."

    if payload["confirm"] != "DELETE":
        return 'Ожидалось подтверждение confirm = "DELETE".'

    return None


def _validate_ttl_payload(payload: Any, expected: str) -> Optional[str]:
    """Подтверждение опасного действия: ровно {confirm, ttlToken}."""
    if not isinstance(payload, dict):
        return f'Ожидался JSON-объект {{confirm: "{expected}", ttlToken: "…"}}.'

    for key in payload:
        if key not in ("confirm", "ttlToken"):
            return f"Неизвестный ключ: «{key}»."

    if "confirm" not in payload:
        return "Отсутствует обязательный ключ: «confirm»."

    if payload["confirm"] != expected:
        return f'Ожидалось подтверждение confirm = "{expected}".'

    if "ttlToken" not in payload:
        return "Отсутствует обязательный ключ: «ttlToken»."

    if not isinstance(payload["ttlToken"], str):
        return "Ключ «ttlToken» должен быть строкой."

    return None

def _find_process(service: Any, pid: int) -> Optional[Any]:
    """ProcessInfo с таким PID или None (поиск по свежему списку)."""
    for info in service.get_processes():
        try:
            if int(info.id) == pid:
                return info
        except (TypeError, ValueError):
            continue
    return None

def _process_payload(info: Any, service: Any) -> dict[str, Any]:
    """Строка списка процессов: поля ProcessInfo + флаг защиты.

    CPU не отдаём намеренно: ни C#, ни Python-сервис процессов его
    не измеряют — не показываем в UI то, чего нет (§5 плана).
    """
    name = str(info.name)
    return {
        "pid": int(info.id),
        "name": name,
        "memoryMb": float(info.memory_mb),
        "responding": bool(info.responding),
        "protected": bool(service.is_protected(name)),
    }

def _app_payload(info: Any) -> dict[str, Any]:
    """Строка списка приложений: AppInfo (snake_case, datetime) → camelCase."""
    last_seen = getattr(info, "last_seen", "")
    # datetime → ISO-8601 (у C#-поля LastSeen — формат "O").
    last_seen_text = last_seen.isoformat() if hasattr(last_seen, "isoformat") else str(last_seen)

    return {
        "name": str(info.name),
        "executablePath": str(info.executable_path),
        "source": str(info.source),
        "category": str(info.category),
        "priority": int(info.priority),
        "aliases": [str(alias) for alias in info.aliases],
        "lastSeen": last_seen_text,
    }

def _enum_name(value: Any) -> str:
    """Enum (PluginType/PersonalityStyle) → имя члена; иначе строка как есть."""
    return value.name if isinstance(value, enum.Enum) else str(value)

# Журнал: строка сессии `[ts] [LEVEL] msg` vs errors.log `[ts] [LEVEL] [src] msg`.
# Источник определяется по ИМЕНИ файла, а не по разбору строки: сообщение
# ошибки может само начинаться с квадратных скобок (например, [Errno 32]).
_LOG_SESSION_LINE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([A-Za-z]+)\] (.*)$")
_LOG_ERRORS_LINE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([A-Za-z]+)\] \[([^\]]+)\] (.*)$"
)

def _read_log_entries(folder: Path, level: str) -> list[dict[str, Any]]:
    """Строки журнала (сессии + errors.log), отфильтрованные по level.

    Файлы читаются по имени DESC, затем стабильная сортировка по времени
    DESC — ровно как OrderByDescending в C#-реализации. Неразобранные
    строки пропускаются.
    """
    if not folder.is_dir():
        return []

    files = sorted(
        (path for path in folder.iterdir() if path.is_file() and path.suffix == ".log"),
        key=lambda path: path.name,
        reverse=True,
    )

    entries: list[dict[str, Any]] = []

    for path in files:
        is_errors = path.name == "errors.log"
        pattern = _LOG_ERRORS_LINE if is_errors else _LOG_SESSION_LINE

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for line in lines:
            match = pattern.match(line)
            if match is None:
                continue

            time_text, line_level, *rest = match.groups()
            item_level = line_level.lower()

            if level and item_level != level:
                continue

            if is_errors:
                source, message = rest[0], rest[1]
            else:
                source, message = None, rest[0]

            entries.append(
                {
                    "time": time_text.replace(" ", "T"),
                    "level": item_level,
                    "message": message,
                    "source": source,
                }
            )

    entries.sort(key=lambda entry: str(entry["time"]), reverse=True)
    return entries


def _validate_update_payload(payload: Any) -> Optional[str]:
    """Тело POST /api/update/apply: только необязательный installDependencies."""
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект {installDependencies}."

    for key in payload:
        if key != "installDependencies":
            return f"Неизвестный ключ: «{key}»."

    if "installDependencies" in payload and not isinstance(
        payload["installDependencies"], bool
    ):
        return "Ключ «installDependencies» должен быть булевым."

    return None


def _validate_memory_payload(payload: Any) -> Optional[str]:
    """Валидация записи памяти: {key, value, category?}."""
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект записи памяти."

    allowed = {"key", "value", "category"}

    for key in payload:
        if key not in allowed:
            return f"Неизвестный ключ: «{key}»."

    for required in ("key", "value"):
        if required not in payload:
            return f"Отсутствует обязательный ключ: «{required}»."
        if not isinstance(payload[required], str):
            return f"Ключ «{required}» должен быть строкой."

    if not payload["key"].strip():
        return "Ключ «key» не может быть пустым."

    if len(payload["key"]) > _MAX_MEMORY_KEY_LENGTH:
        return f"Ключ «key» длиннее {_MAX_MEMORY_KEY_LENGTH} символов."

    if len(payload["value"]) > _MAX_MEMORY_VALUE_LENGTH:
        return f"Значение длиннее {_MAX_MEMORY_VALUE_LENGTH} символов."

    if "category" in payload:
        category = payload["category"]
        if not isinstance(category, str):
            return "Ключ «category» должен быть строкой."
        if not category.strip():
            return "Ключ «category» не может быть пустым."
        if len(category) > _MAX_MEMORY_CATEGORY_LENGTH:
            return f"Ключ «category» длиннее {_MAX_MEMORY_CATEGORY_LENGTH} символов."

    return None


def _memory_item_payload(item: Any) -> dict[str, Any]:
    return {
        "id": int(item.id),
        "key": item.key,
        "value": item.value,
        "category": item.category,
        "createdAt": item.created_at.isoformat(),
    }


def _camel_to_snake(key: str) -> str:
    out: list[str] = []
    for char in key:
        if char.isupper():
            out.append("_")
            out.append(char.lower())
        else:
            out.append(char)
    return "".join(out)


_STRING_FIELDS = ("version", "assistantName", "language", "model", "ttsEngine", "voiceReferencePath")
# Необязательные строковые ключи: старые клиенты/скрипты могут их не
# присылать (openapi: свойство есть в схеме, но вне required).
_OPTIONAL_STRING_FIELDS = ("sttEngine",)
_BOOL_FIELDS = ("voiceEnabled", "autoMemory")
# Необязательные логические ключи — тот же контракт, что у sttEngine:
# свойство есть в схеме, но вне required (старые клиенты его не шлют).
_OPTIONAL_BOOL_FIELDS = ("audioProcessing",)


# ── ИИ: границы полей (docs/AI_PROVIDERS.md) ───────────────────────
_MAX_AI_KEY_LENGTH = 500
_MAX_AI_URL_LENGTH = 500
_MAX_AI_MODEL_LENGTH = 120
_AI_SETTINGS_KEYS = (
    "mode",
    "cloudProvider",
    "cloudBaseUrl",
    "cloudModel",
    "localBaseUrl",
    "localModel",
)


def _validate_ai_base_url(key: str, value: Any) -> Optional[str]:
    """Base URL облачного/локального API: только http(s) и с хостом."""
    if not isinstance(value, str):
        return f"Ключ «{key}» должен быть строкой."

    url = value.strip()
    if not url:
        return f"Ключ «{key}» не может быть пустым."

    if len(url) > _MAX_AI_URL_LENGTH:
        return f"Ключ «{key}» длиннее {_MAX_AI_URL_LENGTH} символов."

    if any(char.isspace() for char in url):
        return f"Ключ «{key}» не должен содержать пробелов."

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return f"Ключ «{key}» должен быть полным адресом вида http://127.0.0.1:11434/v1."

    return None


def _validate_ai_model(key: str, value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return f"Ключ «{key}» должен быть строкой."

    model = value.strip()
    if not model:
        return f"Ключ «{key}» не может быть пустым."

    if len(model) > _MAX_AI_MODEL_LENGTH:
        return f"Ключ «{key}» длиннее {_MAX_AI_MODEL_LENGTH} символов."

    return None


def _validate_ai_settings_payload(payload: Any) -> Optional[str]:
    """Тело POST /api/ai/settings: подмножество ключей ИИ, дополнительных нет."""
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект настроек ИИ."

    for key in payload:
        if key not in _AI_SETTINGS_KEYS:
            return f"Неизвестный ключ настроек ИИ: «{key}»."

    if not payload:
        return "Не задано ни одного поля настроек ИИ."

    if "mode" in payload:
        if not isinstance(payload["mode"], str):
            return "Ключ «mode» должен быть строкой."
        if payload["mode"] not in MODES:
            return f"Ключ «mode» допускает только: {', '.join(MODES)}."

    if "cloudProvider" in payload:
        if not isinstance(payload["cloudProvider"], str):
            return "Ключ «cloudProvider» должен быть строкой."
        if payload["cloudProvider"] not in PROVIDER_IDS:
            return f"Ключ «cloudProvider» допускает только: {', '.join(PROVIDER_IDS)}."

    for key in ("cloudBaseUrl", "localBaseUrl"):
        if key in payload:
            error = _validate_ai_base_url(key, payload[key])
            if error is not None:
                return error

    for key in ("cloudModel", "localModel"):
        if key in payload:
            error = _validate_ai_model(key, payload[key])
            if error is not None:
                return error

    return None


def _validate_ai_key_payload(payload: Any) -> Optional[str]:
    """Тело POST /api/ai/key: обязателен непустой apiKey, остальное опционально."""
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект с API-ключом."

    allowed = {"apiKey", "cloudProvider", "cloudBaseUrl", "cloudModel", "validate"}

    for key in payload:
        if key not in allowed:
            return f"Неизвестный ключ: «{key}»."

    if "apiKey" not in payload:
        return "Отсутствует обязательный ключ «apiKey»."

    api_key = payload["apiKey"]
    if not isinstance(api_key, str):
        return "Ключ «apiKey» должен быть строкой."

    if not api_key.strip():
        return "Ключ «apiKey» не может быть пустым."

    if len(api_key.strip()) > _MAX_AI_KEY_LENGTH:
        return f"Ключ «apiKey» длиннее {_MAX_AI_KEY_LENGTH} символов."

    if "validate" in payload and not isinstance(payload["validate"], bool):
        return "Ключ «validate» должен быть логическим значением."

    nested = {
        key: value
        for key, value in payload.items()
        if key in ("cloudProvider", "cloudBaseUrl", "cloudModel")
    }
    if nested:
        return _validate_ai_settings_payload(nested)

    return None


def _validate_ai_key_test_payload(payload: Any) -> Optional[str]:
    """Тело POST /api/ai/key/test: ключ можно не присылать (возьмём сохранённый)."""
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект."

    allowed = {"apiKey", "cloudProvider", "cloudBaseUrl", "cloudModel"}

    for key in payload:
        if key not in allowed:
            return f"Неизвестный ключ: «{key}»."

    api_key = payload.get("apiKey")
    if api_key is not None:
        if not isinstance(api_key, str):
            return "Ключ «apiKey» должен быть строкой."
        if api_key.strip() and len(api_key.strip()) > _MAX_AI_KEY_LENGTH:
            return f"Ключ «apiKey» длиннее {_MAX_AI_KEY_LENGTH} символов."

    nested = {
        key: value
        for key, value in payload.items()
        if key in ("cloudProvider", "cloudBaseUrl", "cloudModel")
    }
    if nested:
        return _validate_ai_settings_payload(nested)

    return None


def _validate_ai_local_payload(payload: Any) -> Optional[str]:
    """Тело POST /api/ai/local/test: необязательные адрес и модель."""
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект."

    allowed = {"localBaseUrl", "localModel"}

    for key in payload:
        if key not in allowed:
            return f"Неизвестный ключ: «{key}»."

    if "localBaseUrl" in payload:
        error = _validate_ai_base_url("localBaseUrl", payload["localBaseUrl"])
        if error is not None:
            return error

    if "localModel" in payload:
        error = _validate_ai_model("localModel", payload["localModel"])
        if error is not None:
            return error

    return None


def _validate_config_payload(payload: Any) -> Optional[str]:
    """Полная валидация Config по спеке (additionalProperties: false).

    Возвращает текст ошибки или None, если payload корректен.
    """
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект конфигурации."

    allowed = (
        set(_STRING_FIELDS)
        | set(_OPTIONAL_STRING_FIELDS)
        | set(_BOOL_FIELDS)
        | set(_OPTIONAL_BOOL_FIELDS)
        | {
            "voiceVolume",
            "ollamaTimeoutMinutes",
            # LLM-параметры скорости/стабильности (анализ S5, этап 1)
            "llmKeepAlive",
            "llmMaxTokens",
            "llmTimeoutSeconds",
        }
    )

    for key in payload:
        if key not in allowed:
            return f"Неизвестный ключ конфигурации: «{key}»."

    for key in allowed:
        if key in _OPTIONAL_STRING_FIELDS or key in _OPTIONAL_BOOL_FIELDS:
            continue  # необязательный: присутствие не требуется
        if key not in payload:
            return f"Отсутствует обязательный ключ: «{key}»."

    for key in _STRING_FIELDS:
        if not isinstance(payload[key], str):
            return f"Ключ «{key}» должен быть строкой."

    for key in _OPTIONAL_STRING_FIELDS:
        if key in payload and not isinstance(payload[key], str):
            return f"Ключ «{key}» должен быть строкой."

    for key in _BOOL_FIELDS:
        if not isinstance(payload[key], bool):
            return f"Ключ «{key}» должен быть логическим значением."

    for key in _OPTIONAL_BOOL_FIELDS:
        if key in payload and not isinstance(payload[key], bool):
            return f"Ключ «{key}» должен быть логическим значением."

    if payload["language"] not in ("ru", "en"):
        return "Ключ «language» допускает только «ru» или «en»."

    if payload["ttsEngine"] not in _ALLOWED_TTS_ENGINES:
        return "Ключ «ttsEngine» допускает только «pocket» или «chattts»."

    if "sttEngine" in payload and payload["sttEngine"] not in _ALLOWED_STT_ENGINES:
        return "Ключ «sttEngine» допускает только «gigaam» или «whisper»."

    volume = payload["voiceVolume"]
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        return "Ключ «voiceVolume» должен быть числом."
    if not 0 <= volume <= 1:
        return "Ключ «voiceVolume» должен быть в диапазоне 0…1."

    timeout = payload["ollamaTimeoutMinutes"]
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        return "Ключ «ollamaTimeoutMinutes» должен быть целым числом."
    if not 1 <= timeout <= 120:
        return "Ключ «ollamaTimeoutMinutes» должен быть в диапазоне 1…120."

    llm_ranges = (
        ("llmKeepAlive", -1, 86400),
        ("llmMaxTokens", 16, 4096),
        ("llmTimeoutSeconds", 5, 600),
    )
    for key, low, high in llm_ranges:
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, int):
            return f"Ключ «{key}» должен быть целым числом."
        if not low <= value <= high:
            return f"Ключ «{key}» должен быть в диапазоне {low}…{high}."

    return None


def _validate_voice_mode_payload(payload: Any) -> Optional[str]:
    """Тело POST /api/voice/mode: строго {enabled: boolean}."""
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект голосового режима."

    for key in payload:
        if key != "enabled":
            return f"Неизвестный ключ: «{key}»."

    if "enabled" not in payload:
        return "Отсутствует обязательный ключ «enabled»."

    if not isinstance(payload["enabled"], bool):
        return "Ключ «enabled» должен быть логическим значением."

    return None


def _validate_voice_payload(payload: Any) -> Optional[str]:
    """Подмножество голосовых ключей (POST /api/voice): строго, как config.

    Любое из пяти голосовых полей, но не пустой объект и без посторонних ключей.
    """
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект голосовых настроек."

    allowed = {
        "voiceEnabled", "voiceVolume", "ttsEngine", "voiceReferencePath", "audioProcessing"
    }

    for key in payload:
        if key not in allowed:
            return f"Неизвестный ключ голосовых настроек: «{key}»."

    if not payload:
        return "Не задано ни одного голосового поля."

    if "voiceEnabled" in payload and not isinstance(payload["voiceEnabled"], bool):
        return "Ключ «voiceEnabled» должен быть логическим значением."

    if "audioProcessing" in payload and not isinstance(payload["audioProcessing"], bool):
        return "Ключ «audioProcessing» должен быть логическим значением."

    if "voiceVolume" in payload:
        volume = payload["voiceVolume"]
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            return "Ключ «voiceVolume» должен быть числом."
        if not 0 <= volume <= 1:
            return "Ключ «voiceVolume» должен быть в диапазоне 0…1."

    if "ttsEngine" in payload and payload["ttsEngine"] not in _ALLOWED_TTS_ENGINES:
        return "Ключ «ttsEngine» допускает только «pocket» или «chattts»."

    if "voiceReferencePath" in payload and not isinstance(payload["voiceReferencePath"], str):
        return "Ключ «voiceReferencePath» должен быть строкой."

    return None
