"""Локальная панель JARVIS: HTTP API (этап 1 «API-ядро»).

Контракт: docs/api/openapi.yaml. Правила безопасности (§6 плана):

- слушаем только 127.0.0.1 (loopback-only);
- Host должен быть 127.0.0.1/localhost — защита от DNS-rebinding;
- Origin, если задан, — только собственный — защита от CSRF;
- каждый запрос требует заголовок X-JARVIS-Token (config/panel.token);
- ошибки нормализованы: {code, message} — без сырых исключений и путей.
"""

from __future__ import annotations

import enum
import hmac
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from jarvis import paths
from jarvis.api.token import load_or_create_token
from jarvis.ai.ollama_url_resolver import OllamaUrlResolver
from jarvis.core.configuration.jarvis_config import JarvisConfig
from jarvis.core.logging.log_service import log_error
from jarvis.core.plugins.plugin_config import PluginConfig

DEFAULT_PORT = 8080
_MAX_BODY_BYTES = 64 * 1024
_MAX_TEXT_LENGTH = 4000

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
_ALLOWED_TTS_ENGINES = ("pocket", "piper")

# Путь → допустимые методы (маршрутизация до проверки токена не доходит).
_ROUTES = {
    "/api/health": frozenset({"GET"}),
    "/api/config": frozenset({"GET", "POST"}),
    "/api/chat/stream": frozenset({"GET"}),
    "/api/personality": frozenset({"GET"}),
    "/api/personality/set": frozenset({"POST"}),
    "/api/history": frozenset({"GET", "DELETE"}),
    "/api/memory": frozenset({"GET", "POST"}),
}

_MEMORY_PREFIX = "/api/memory/"
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
        config: JarvisConfig,
        memory: Any,
        *,
        conversation: Optional[Any] = None,
        plugin_config: Optional[PluginConfig] = None,
        token: Optional[str] = None,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._engine = engine
        self._config = config
        self._memory = memory
        self._conversation = conversation
        self._plugin_config = plugin_config
        self._token = token if token is not None else load_or_create_token()
        self._requested_port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[Thread] = None

    # ── Доступ из обработчика ─────────────────────────────────────

    @property
    def engine(self) -> Any:
        return self._engine

    @property
    def config(self) -> JarvisConfig:
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

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


class _PanelHandler(BaseHTTPRequestHandler):
    """Один запрос → одна проверка безопасности → один маршрут."""

    # Не раскрываем версию Python в заголовке Server.
    server_version = "JARVISPanel/1.0"
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
        supplied = self.headers.get("X-JARVIS-Token", "")
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
            self._send_json(401, "UNAUTHORIZED", "Требуется X-JARVIS-Token.")
            return

        # Динамический маршрут DELETE /api/memory/{id}
        if path.startswith(_MEMORY_PREFIX):
            if method != "DELETE":
                self._send_json(405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.")
                return

            self._handle_memory_delete(path[len(_MEMORY_PREFIX):])
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
                "__JARVIS_TOKEN__", self.panel.token
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
            engine_name = "piper"

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
                "jarvisResponse": c.jarvis_response,
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

    # ── Помощники ─────────────────────────────────────────────────

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
_BOOL_FIELDS = ("voiceEnabled", "autoMemory")


def _validate_config_payload(payload: Any) -> Optional[str]:
    """Полная валидация Config по спеке (additionalProperties: false).

    Возвращает текст ошибки или None, если payload корректен.
    """
    if not isinstance(payload, dict):
        return "Ожидался JSON-объект конфигурации."

    allowed = set(_STRING_FIELDS) | set(_BOOL_FIELDS) | {"voiceVolume", "ollamaTimeoutMinutes"}

    for key in payload:
        if key not in allowed:
            return f"Неизвестный ключ конфигурации: «{key}»."

    for key in allowed:
        if key not in payload:
            return f"Отсутствует обязательный ключ: «{key}»."

    for key in _STRING_FIELDS:
        if not isinstance(payload[key], str):
            return f"Ключ «{key}» должен быть строкой."

    for key in _BOOL_FIELDS:
        if not isinstance(payload[key], bool):
            return f"Ключ «{key}» должен быть логическим значением."

    if payload["language"] not in ("ru", "en"):
        return "Ключ «language» допускает только «ru» или «en»."

    if payload["ttsEngine"] not in _ALLOWED_TTS_ENGINES:
        return "Ключ «ttsEngine» допускает только «pocket» или «piper»."

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

    return None
