"""Контрактные тесты локальной панели JARVIS против docs/api/openapi.yaml.

Этап 1 «API-ядро» (docs/GUI_DEVELOPMENT_PLAN.md §7): контракт один на обе
реализации, тесты проверяют ответы именно по спеке (required/enum/type).

Запуск:
- `python3 tests/test_panel_api.py` — без зависимостей (только pyyaml);
- `pytest tests/ -q` — в CI (функции test_* без аргументов);
- `JARVIS_PANEL_EXTERNAL=1` — против уже запущенной панели в отдельном
  процессе (CI-джоба C#: `dotnet run --project JARVIS.App -- --panel`),
  тогда контракт проверяется на второй реализации тем же набором тестов.
"""

from __future__ import annotations

import enum
import http.client
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import quote

import yaml

# Корень репозитория — чтобы `python3 tests/test_panel_api.py` работал
# без установки пакета (pytest это делает сам, но дубликат не вредит).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis import paths as paths_module
from jarvis.api.server import PanelServer
from jarvis.core.configuration.jarvis_config import JarvisConfig
from jarvis.core.plugins.plugin_config import PluginConfig

SPEC: dict[str, Any] = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.yaml").read_text(
        encoding="utf-8"
    )
)

TOKEN = "b" * 64
_UNSET = object()

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = os.environ.get("JARVIS_PANEL_EXTERNAL") == "1"
EXTERNAL_PORT = int(os.environ.get("JARVIS_PANEL_PORT", "8080"))

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


class FakePluginManager:
    def __init__(self) -> None:
        self.active_personality = FakePersonality()


class FakeEngine:
    """Подмена JarvisEngine: детерминированный ответ без LLM."""

    def __init__(self) -> None:
        self.processed: list[str] = []
        self.plugin_manager = FakePluginManager()

    def process(self, text: str) -> str:
        self.processed.append(text)
        return f"ответ: {text}"


class FakeMemory:
    def get_all(self) -> list[Any]:
        return []


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


@contextmanager
def running_panel() -> Iterator[tuple[Any, Path]]:
    """Панель на эфемерном порту, config.json — во временной папке.

    В режиме JARVIS_PANEL_EXTERNAL — уже запущенная панель в отдельном
    процессе, конфигурация берётся из config/ репозитория.
    """
    if EXTERNAL:
        yield _wait_external_panel(), REPO_ROOT / "config"
        return

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        original_config_path = paths_module.config_path
        original_plugins_config_path = paths_module.plugins_config_path
        paths_module.config_path = lambda: tmp / "config.json"
        paths_module.plugins_config_path = lambda: tmp / "plugins.json"
        try:
            panel = PanelServer(
                engine=FakeEngine(),
                config=JarvisConfig(),
                memory=FakeMemory(),
                plugin_config=PluginConfig(),
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
        headers["X-JARVIS-Token"] = token

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

        reloaded = JarvisConfig.load()
        assert reloaded.voice_volume == 0.8
        assert reloaded.model == "qwen3.5:4b"


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
            headers={"X-JARVIS-Token": panel.token, "Content-Type": "application/json"},
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
