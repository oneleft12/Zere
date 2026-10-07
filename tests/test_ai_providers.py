"""Тесты выбора ИИ: облачный ключ пользователя или локальная модель.

Проверяют требования задачи: приоритет провайдеров, проверку ключа рабочим
запросом, понятные ошибки, проверку локального сервера и модели, загрузку
модели через Ollama, безопасность ключа (маска, отсутствие в логах).

Сеть не используется: облачный клиент и локальные проверки получают
`tests/fake_http.FakeSession`.

Запуск:
- `python3 tests/test_ai_providers.py` — без зависимостей (кроме requests);
- `pytest tests/ -q` — в CI.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from zere import paths
from zere.ai.ai_service import (
    MESSAGE_NOT_CONFIGURED,
    AiProviderProxy,
    AiService,
)
from zere.ai.ai_settings import (
    KEY_INVALID,
    KEY_OK,
    MODE_CLOUD,
    MODE_LOCAL,
    PROVIDER_PRESETS,
    SOURCE_NONE,
    SOURCE_OWNER,
    SOURCE_USER,
    AiSettings,
    mask_key,
)
from zere.ai.cloud_client import (
    CODE_KEY_INVALID,
    CODE_MODEL_UNAVAILABLE,
    CODE_NETWORK,
    CODE_NO_CREDITS,
    CODE_RATE_LIMIT,
    AiError,
    CloudClient,
)
from zere.ai.local_model import (
    CODE_LOCAL_MODEL_MISSING,
    CODE_LOCAL_SERVER_DOWN,
    CODE_PULL_UNSUPPORTED,
    LocalModelService,
    model_installed,
    native_root,
)
from zere.core.logging.log_service import redact_secrets

from tests.fake_http import (
    FakeSession,
    chat_response,
    error_response,
    models_response,
    ollama_pull_response,
    ollama_tags_response,
)

ENV_KEYS = (
    "ZERE_AI_MODE",
    "ZERE_CLOUD_API_KEY",
    "ZERE_CLOUD_BASE_URL",
    "ZERE_CLOUD_MODEL",
    "ZERE_CLOUD_PROVIDER",
    "ZERE_LOCAL_BASE_URL",
    "ZERE_LOCAL_MODEL",
)

GOOD_KEY = "sk-test-abcdefghijklmnop"


@contextmanager
def temp_config(*, clear_env: bool = True) -> Iterator[Path]:
    """Временный config/ai.json: реальные настройки пользователя не трогаются."""
    original_path = paths.config_path
    saved_env = {key: os.environ.pop(key) for key in ENV_KEYS if key in os.environ} if clear_env else {}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        paths.config_path = lambda: tmp / "config.json"  # type: ignore[assignment]
        try:
            yield tmp
        finally:
            paths.config_path = original_path  # type: ignore[assignment]
            if clear_env:
                for key in ENV_KEYS:
                    os.environ.pop(key, None)
                os.environ.update(saved_env)
            else:
                os.environ.update(saved_env)


class FakeLocalClient:
    """Подмена OllamaClient: фиксирует вызов и возвращает заданный ответ."""

    def __init__(self, model: str, answer: str = "локальный ответ") -> None:
        self.model = model
        self.answer = answer
        self.calls: list[tuple[Any, ...]] = []
        self.warmed = 0
        self.closed = 0

    def generate(self, prompt, system_prompt=None, temperature=None, max_tokens=None) -> str:
        self.calls.append((prompt, system_prompt, temperature, max_tokens))
        return self.answer

    def warmup(self) -> None:
        self.warmed += 1

    def close(self) -> None:
        self.closed += 1


def ollama_session(
    models: list[str], *, pulls: Optional[list[str]] = None, answer: str = "локальный ответ"
) -> FakeSession:
    """Сессия «запущена Ollama»: native /api/tags (+ опционально /api/pull).

    Ollama отвечает и на OpenAI-совместимый /v1/chat/completions — это нужно
    тестовому запросу к модели.
    """
    session = FakeSession().route("GET", "/api/tags", ollama_tags_response(models))
    session.route("POST", "/chat/completions", chat_response(answer))
    if pulls is not None:
        session.route("POST", "/api/pull", ollama_pull_response(pulls))
    return session


def openai_local_session(models: list[str], answer: str = "локальный openai ответ") -> FakeSession:
    """Сессия «локальный OpenAI-совместимый сервер без нативного API Ollama»."""
    return FakeSession().route("GET", "/models", models_response(models)).route(
        "POST", "/chat/completions", chat_response(answer)
    )


def empty_session() -> FakeSession:
    return FakeSession()


# ── 1. Маска и хранение ключа (безопасность) ───────────────────────


def test_mask_key_shows_only_edges() -> None:
    assert mask_key("sk-1234567890abcdef") == "sk-...cdef"
    assert mask_key("") == ""
    assert mask_key("short") == "***"
    assert mask_key(None) == ""


def test_settings_persist_and_hide_key() -> None:
    with temp_config() as tmp:
        settings = AiSettings.load()
        settings.cloud_api_key = GOOD_KEY
        settings.cloud_key_status = KEY_OK
        settings.mode = MODE_CLOUD
        settings.save()

        raw = (tmp / "ai.json").read_text(encoding="utf-8")
        assert GOOD_KEY in raw, "ключ обязан лежать в config/ai.json"

        if os.name != "nt":
            mode = stat.S_IMODE((tmp / "ai.json").stat().st_mode)
            assert mode == 0o600, f"права файла с ключом: {oct(mode)}"

        loaded = AiSettings.load()
        assert loaded.cloud_api_key == GOOD_KEY
        assert loaded.mode == MODE_CLOUD

        # Наружу (в API) ключ не уходит: только маска.
        public = loaded.to_public_dict()
        assert public["cloud"]["keyMask"] == "sk-...mnop"
        assert GOOD_KEY not in json.dumps(public)
        assert GOOD_KEY not in json.dumps(loaded.to_camel_dict())


def test_settings_owner_key_from_env_has_priority_rules() -> None:
    with temp_config() as tmp:
        os.environ["ZERE_CLOUD_API_KEY"] = "sk-owner-111111111111"
        os.environ["ZERE_AI_MODE"] = "cloud"

        settings = AiSettings.load()
        key, source = settings.active_key()
        assert (key, source) == ("sk-owner-111111111111", SOURCE_OWNER)
        assert settings.mode == MODE_CLOUD

        # Ключ пользователя важнее ключа владельца.
        settings.cloud_api_key = GOOD_KEY
        settings.save()
        key, source = settings.active_key()
        assert (key, source) == (GOOD_KEY, SOURCE_USER)

        # Удаление ключа пользователя (как в UI) не трогает ключ владельца.
        restored = AiSettings.load()
        restored.cloud_api_key = ""
        restored.save()
        key, source = AiSettings.load().active_key()
        assert (key, source) == ("sk-owner-111111111111", SOURCE_OWNER)

        del os.environ["ZERE_CLOUD_API_KEY"]
        os.environ.pop("ZERE_AI_MODE", None)
        key, source = AiSettings.load().active_key()
        assert (key, source) == ("", SOURCE_NONE)


def test_settings_broken_file_falls_back_to_defaults() -> None:
    with temp_config() as tmp:
        (tmp / "ai.json").write_text("{ это не json", encoding="utf-8")
        settings = AiSettings.load()
        assert settings.mode == "auto"
        assert settings.cloud_api_key == ""
        assert settings.local_model == "qwen3.5:2b"


def test_redact_secrets_masks_keys_in_logs() -> None:
    assert GOOD_KEY not in redact_secrets(f"Authorization: Bearer {GOOD_KEY}")
    masked = redact_secrets(f"ключ {GOOD_KEY} не подошёл")
    assert GOOD_KEY not in masked
    assert "***" in masked
    assert GOOD_KEY not in redact_secrets(f'{{"apiKey": "{GOOD_KEY}"}}')
    # Обычный текст не портится.
    assert redact_secrets("Модель qwen3.5:2b готова") == "Модель qwen3.5:2b готова"


# ── 2. Проверка облачного ключа ────────────────────────────────────


def test_cloud_test_key_ok_via_models() -> None:
    session = FakeSession().route("GET", "/models", models_response(["gpt-4o-mini", "o3-mini"]))
    result = CloudClient(session).test_key("https://api.openai.com/v1", GOOD_KEY, "gpt-4o-mini")

    assert result["ok"] is True
    assert result["checkedWith"] == "models"
    assert result["models"] == ["gpt-4o-mini", "o3-mini"]
    # Ключ уходит в заголовке Authorization — и нигде больше.
    _method, _url, kwargs = session.calls[0]
    assert kwargs["headers"]["Authorization"] == f"Bearer {GOOD_KEY}"


def test_cloud_test_key_falls_back_to_chat_probe() -> None:
    session = FakeSession().route("GET", "/models", error_response(404, "Not Found")).route(
        "POST", "/chat/completions", chat_response("pong")
    )
    result = CloudClient(session).test_key("https://api.deepseek.com/v1", GOOD_KEY, "deepseek-chat")

    assert result["ok"] is True
    assert result["checkedWith"] == "chat"
    probe = session.json_bodies("POST")[0]
    assert probe["max_tokens"] == 1, "тестовая проверка обязана быть минимальной"


def test_cloud_key_errors_are_friendly() -> None:
    cases = (
        (401, "invalid api key", CODE_KEY_INVALID, "Неверный API-ключ"),
        (403, "forbidden", CODE_KEY_INVALID, "Неверный API-ключ"),
        (402, "insufficient balance", CODE_NO_CREDITS, "На балансе нет средств"),
        (429, "rate limit", CODE_RATE_LIMIT, "Превышен лимит запросов"),
    )

    for status, body, expected_code, expected_message in cases:
        session = FakeSession().route("GET", "/models", error_response(status, body)).route(
            "POST", "/chat/completions", error_response(status, body)
        )
        try:
            CloudClient(session).test_key("https://api.example.com/v1", GOOD_KEY, "m")
        except AiError as ex:
            assert ex.code == expected_code, f"HTTP {status}: {ex.code}"
            assert ex.message == expected_message, f"HTTP {status}: {ex.message}"
        else:
            raise AssertionError(f"HTTP {status} должен был дать ошибку")


def test_cloud_unknown_model_is_reported() -> None:
    session = FakeSession().route(
        "GET", "/models", error_response(404, '{"error": {"message": "model not found"}}')
    ).route(
        "POST",
        "/chat/completions",
        error_response(400, '{"error": {"code": "model_not_found"}}'),
    )

    try:
        CloudClient(session).test_key("https://api.example.com/v1", GOOD_KEY, "нет-такой")
    except AiError as ex:
        assert ex.code == CODE_MODEL_UNAVAILABLE
        assert ex.message == "Модель недоступна"
    else:
        raise AssertionError("отсутствующая модель должна давать ошибку")


def test_cloud_unreachable_server_is_network_error() -> None:
    try:
        CloudClient(empty_session()).test_key("https://api.example.com/v1", GOOD_KEY, "m")
    except AiError as ex:
        assert ex.code == CODE_NETWORK
    else:
        raise AssertionError("недоступный сервер должен давать AI_NETWORK")


def test_cloud_generate_parses_answer() -> None:
    session = FakeSession().route("POST", "/chat/completions", chat_response("Привет, я ZERE"))
    answer = CloudClient(session).generate(
        "привет",
        system_prompt="ты ассистент",
        base_url="https://api.openai.com/v1",
        api_key=GOOD_KEY,
        model="gpt-4o-mini",
        temperature=0.4,
        max_tokens=64,
    )
    assert answer == "Привет, я ZERE"

    body = session.json_bodies("POST")[0]
    assert body["messages"][0] == {"role": "system", "content": "ты ассистент"}
    assert body["messages"][1] == {"role": "user", "content": "привет"}
    assert body["temperature"] == 0.4
    assert body["max_tokens"] == 64


def test_cloud_error_message_never_contains_key() -> None:
    session = FakeSession().route(
        "GET",
        "/models",
        error_response(500, f"server exploded, header was Bearer {GOOD_KEY}"),
    ).route(
        "POST",
        "/chat/completions",
        error_response(500, f"server exploded, header was Bearer {GOOD_KEY}"),
    )

    try:
        CloudClient(session).test_key("https://api.example.com/v1", GOOD_KEY, "m")
    except AiError as ex:
        assert GOOD_KEY not in ex.message, ex.message
    else:
        raise AssertionError("HTTP 500 должен был дать ошибку")


# ── 3. Локальная модель ────────────────────────────────────────────


def test_local_model_name_matching() -> None:
    assert model_installed("qwen3.5:2b", ["qwen3.5:2b"])
    assert model_installed("qwen3.5", ["qwen3.5:latest"])
    assert model_installed("qwen3.5:latest", ["qwen3.5"])
    assert not model_installed("qwen2.5:0.5b", ["qwen2.5:1.5b"])
    assert not model_installed("qwen3.5:2b", [])
    assert not model_installed("", ["qwen3.5:2b"])


def test_local_native_root_strips_v1() -> None:
    assert native_root("http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434"
    assert native_root("http://192.168.1.5:11434") == "http://192.168.1.5:11434"


def test_local_probe_reports_down_without_server() -> None:
    status = LocalModelService(empty_session()).probe("http://127.0.0.1:11434/v1")
    assert status["server"] == "down"
    assert status["api"] == ""
    assert status["models"] == []
    assert status["detail"] == "Локальный сервер не запущен"


def test_local_probe_detects_ollama_and_models() -> None:
    status = LocalModelService(ollama_session(["qwen3.5:2b"])).probe("http://127.0.0.1:11434/v1")
    assert status["server"] == "up"
    assert status["api"] == "ollama"
    assert status["models"] == ["qwen3.5:2b"]
    assert status["baseUrl"] == "http://127.0.0.1:11434/v1"


def test_local_probe_detects_openai_compatible_server() -> None:
    status = LocalModelService(openai_local_session(["qwen3.5:2b"])).probe(
        "http://192.168.1.5:8000/v1"
    )
    assert status["server"] == "up"
    assert status["api"] == "openai"
    # Чужой адрес не подменяется локальным: fallback-адреса не пробуются.
    assert status["baseUrl"] == "http://192.168.1.5:8000/v1"


def test_local_test_reports_missing_model() -> None:
    service = LocalModelService(ollama_session(["llama3.2:3b"]))

    try:
        service.test("http://127.0.0.1:11434/v1", "qwen3.5:2b")
    except AiError as ex:
        assert ex.code == CODE_LOCAL_MODEL_MISSING
        assert "ollama pull qwen3.5:2b" in ex.message
    else:
        raise AssertionError("отсутствующая модель должна давать ошибку")


def test_local_test_reports_stopped_server() -> None:
    try:
        LocalModelService(empty_session()).test("http://127.0.0.1:11434/v1", "qwen3.5:2b")
    except AiError as ex:
        assert ex.code == CODE_LOCAL_SERVER_DOWN
        assert ex.message == "Локальный сервер не запущен"
    else:
        raise AssertionError("выключенный сервер должен давать ошибку")


def test_local_test_ok_sends_minimal_chat_request() -> None:
    session = openai_local_session(["qwen3.5:2b"])
    result = LocalModelService(session).test("http://127.0.0.1:11434/v1", "qwen3.5:2b")

    assert result["ok"] is True
    body = session.json_bodies("POST")[0]
    assert body["max_tokens"] == 1
    assert body["model"] == "qwen3.5:2b"


def test_local_pull_streams_progress_and_finishes() -> None:
    session = ollama_session(
        ["qwen3.5:2b"],
        pulls=[
            '{"status":"pulling manifest"}',
            '{"status":"downloading","total":200,"completed":50}',
            '{"status":"success"}',
        ],
    )
    events = list(LocalModelService(session).pull("http://127.0.0.1:11434/v1", "qwen3.5:2b"))

    assert [event["status"] for event in events] == ["pulling", "pulling", "pulling", "done"]
    assert events[1]["percent"] == 25.0
    assert events[-1]["model"] == "qwen3.5:2b"


def test_local_pull_reports_ollama_error() -> None:
    session = ollama_session(
        [], pulls=['{"error": "model not found in registry"}']
    )
    events = list(LocalModelService(session).pull("http://127.0.0.1:11434/v1", "нет-такой"))

    assert events[-1]["status"] == "error"
    assert "model not found" in events[-1]["message"]


def test_local_pull_unsupported_for_non_ollama() -> None:
    events = list(
        LocalModelService(openai_local_session(["qwen3.5:2b"])).pull(
            "http://192.168.1.5:8000/v1", "qwen3.5:2b"
        )
    )
    assert events[0]["status"] == "error"
    assert events[0]["code"] == CODE_PULL_UNSUPPORTED


def test_local_install_hint_has_command_and_steps() -> None:
    hint = LocalModelService.install_hint("qwen3.5:2b")

    assert hint["title"] == "Локальная модель не найдена"
    assert hint["command"] == "ollama pull qwen3.5:2b"
    assert hint["downloadUrl"] == "https://ollama.com/download"
    assert any("ollama pull qwen3.5:2b" in step for step in hint["steps"])
    assert len(hint["steps"]) >= 4


# ── 4. Выбор провайдера (приоритет) ────────────────────────────────


def test_status_without_key_and_without_local_model() -> None:
    with temp_config():
        service = AiService(session=empty_session())
        status = service.status()

        assert status["activeProvider"] == "none"
        assert status["ready"] is False
        assert status["summary"] == "Подключите API-ключ или используйте локальную модель"
        assert status["local"]["status"] == "server-down"
        assert status["local"]["installHint"]["command"] == "ollama pull qwen3.5:2b"
        assert service.generate("привет") == MESSAGE_NOT_CONFIGURED


def test_status_reports_cloud_connection() -> None:
    with temp_config():
        settings = AiSettings.load()
        settings.cloud_api_key = GOOD_KEY
        settings.cloud_key_status = KEY_OK
        settings.save()

        status = AiService(session=empty_session()).status()

        assert status["activeProvider"] == "cloud"
        assert status["cloud"]["keySaved"] is True
        assert status["cloud"]["keySource"] == SOURCE_USER
        assert status["cloud"]["keyMask"] == "sk-...mnop"
        assert "Подключено: облачная модель" in status["summary"]
        assert GOOD_KEY not in json.dumps(status)


def test_status_reports_local_connection() -> None:
    with temp_config():
        service = AiService(session=ollama_session(["qwen3.5:2b"]))
        status = service.status()

        assert status["activeProvider"] == "local"
        assert status["local"]["status"] == "available"
        assert status["local"]["statusText"] == "Локальная модель доступна"
        assert status["local"]["canPull"] is True
        assert status["summary"] == "Подключено: локальная модель · qwen3.5:2b"


def test_local_model_missing_shows_instruction() -> None:
    with temp_config():
        service = AiService(session=ollama_session(["llama3.2:3b"]))
        status = service.status()

        assert status["activeProvider"] == "none"
        assert status["local"]["status"] == "model-missing"
        assert status["local"]["modelInstalled"] is False
        assert status["local"]["installHint"] is not None
        assert status["local"]["models"] == ["llama3.2:3b"]


def test_auto_prefers_cloud_over_local() -> None:
    with temp_config():
        settings = AiSettings.load()
        settings.cloud_api_key = GOOD_KEY
        settings.cloud_key_status = KEY_OK
        settings.save()

        session = FakeSession().route("POST", "/chat/completions", chat_response("облако"))
        session.route("GET", "/api/tags", ollama_tags_response(["qwen3.5:2b"]))

        service = AiService(session=session)
        assert service.status()["activeProvider"] == "cloud"
        assert service.generate("привет") == "облако"


def test_auto_uses_local_when_no_key() -> None:
    with temp_config():
        client = FakeLocalClient("qwen3.5:2b", "локально")
        session = FakeSession().route("GET", "/api/tags", ollama_tags_response(["qwen3.5:2b"]))

        service = AiService(session=session, local_client_factory=lambda m: client)
        status = service.status()

        assert status["activeProvider"] == "local"
        assert service.generate("привет", "система", 0.5, 16) == "локально"
        # Прокси передаёт аргументы ровно как прежний OllamaClient.
        assert client.calls == [("привет", "система", 0.5, 16)]


def test_auto_falls_back_to_local_when_cloud_key_fails() -> None:
    with temp_config():
        settings = AiSettings.load()
        settings.cloud_api_key = GOOD_KEY
        settings.cloud_key_status = KEY_OK
        settings.save()

        client = FakeLocalClient("qwen3.5:2b", "локальный запасной ответ")
        session = FakeSession().route("GET", "/api/tags", ollama_tags_response(["qwen3.5:2b"]))
        session.route("POST", "/chat/completions", error_response(401, "invalid api key"))

        service = AiService(session=session, local_client_factory=lambda m: client)
        assert service.generate("привет") == "локальный запасной ответ"


def test_cloud_mode_without_key_asks_for_key() -> None:
    with temp_config():
        settings = AiSettings.load()
        settings.mode = MODE_CLOUD
        settings.save()

        # Локальная модель есть, но режим «только облако» её не использует.
        service = AiService(session=ollama_session(["qwen3.5:2b"]))
        assert service.status()["activeProvider"] == "none"
        assert service.generate("привет") == MESSAGE_NOT_CONFIGURED


def test_local_mode_reports_stopped_server() -> None:
    with temp_config():
        settings = AiSettings.load()
        settings.mode = MODE_LOCAL
        settings.save()

        service = AiService(session=empty_session())
        answer = service.generate("привет")

        assert "Локальный сервер не запущен" in answer
        assert "ollama.com/download" in answer


def test_invalid_key_is_not_saved() -> None:
    with temp_config() as tmp:
        session = FakeSession().route("GET", "/models", error_response(401, "bad key")).route(
            "POST", "/chat/completions", error_response(401, "bad key")
        )
        service = AiService(session=session)

        try:
            service.save_key({"apiKey": GOOD_KEY, "cloudProvider": "openai"})
        except AiError as ex:
            assert ex.code == CODE_KEY_INVALID
        else:
            raise AssertionError("нерабочий ключ не должен сохраняться")

        assert service.settings.cloud_api_key == ""
        assert not (tmp / "ai.json").exists() or GOOD_KEY not in (tmp / "ai.json").read_text(
            encoding="utf-8"
        )


def test_working_key_is_validated_and_saved() -> None:
    with temp_config() as tmp:
        session = FakeSession().route("GET", "/models", models_response(["gpt-4o-mini"]))
        service = AiService(session=session)

        status = service.save_key(
            {"apiKey": GOOD_KEY, "cloudProvider": "deepseek", "cloudBaseUrl": "https://api.deepseek.com/v1", "cloudModel": "deepseek-chat"}
        )

        assert status["activeProvider"] == "cloud"
        assert status["cloud"]["keyMask"] == "sk-...mnop"
        assert status["cloud"]["keyStatus"] == KEY_OK
        assert status["cloud"]["keyCheckedAt"] is not None
        assert AiSettings.load().cloud_api_key == GOOD_KEY
        assert GOOD_KEY in (tmp / "ai.json").read_text(encoding="utf-8")


def test_key_test_does_not_save_probe_key() -> None:
    with temp_config():
        session = FakeSession().route("GET", "/models", models_response(["gpt-4o-mini"]))
        service = AiService(session=session)

        result = service.test_key({"apiKey": GOOD_KEY, "cloudModel": "gpt-4o-mini"})

        assert result["ok"] is True
        assert result["keyMask"] == "sk-...mnop"
        assert service.settings.cloud_api_key == "", "проверка не сохраняет ключ"


def test_delete_key_keeps_owner_key() -> None:
    with temp_config():
        os.environ["ZERE_CLOUD_API_KEY"] = "sk-owner-999999999999"

        session = FakeSession().route("GET", "/models", models_response(["gpt-4o-mini"]))
        service = AiService(session=session)
        service.save_key({"apiKey": GOOD_KEY})

        assert service.settings.active_key()[1] == SOURCE_USER

        service.delete_key()

        key, source = service.settings.active_key()
        assert source == SOURCE_OWNER, "ключ владельца удалять нельзя"
        assert key == "sk-owner-999999999999"
        os.environ.pop("ZERE_CLOUD_API_KEY", None)


def test_settings_update_and_validation() -> None:
    with temp_config():
        service = AiService(session=empty_session())

        status = service.update_settings({"mode": MODE_LOCAL, "localModel": "qwen2.5:0.5b"})
        assert status["mode"] == MODE_LOCAL
        assert status["local"]["model"] == "qwen2.5:0.5b"

        try:
            service.update_settings({"mode": "магия"})
        except AiError as ex:
            assert ex.code == "AI_VALIDATION"
        else:
            raise AssertionError("неизвестный режим должен отклоняться")


def test_local_test_and_pull_through_service() -> None:
    with temp_config():
        session = ollama_session(
            ["qwen3.5:2b"], pulls=['{"status":"downloading","total":10,"completed":10}']
        )
        service = AiService(session=session)

        assert service.test_local({})["ok"] is True

        events = list(service.pull_model("qwen3.5:2b"))
        assert events[-1]["status"] == "done"
        # После загрузки кэш пробы сброшен — статус пересобирается.
        assert service.status()["local"]["modelInstalled"] is True


def test_proxy_matches_ollama_client_interface() -> None:
    with temp_config():
        service = AiService(session=empty_session())
        proxy = AiProviderProxy(service)

        assert proxy.generate("привет") == MESSAGE_NOT_CONFIGURED
        assert proxy.warmup() is None
        assert proxy.close() is None
        assert proxy.service is service


def test_presets_cover_requested_providers() -> None:
    ids = [preset["id"] for preset in PROVIDER_PRESETS]
    assert ids[:4] == ["openai", "deepseek", "openrouter", "groq"]
    assert ids[-1] == "custom"

    for preset in PROVIDER_PRESETS:
        assert preset["label"]
        if preset["id"] != "custom":
            assert preset["baseUrl"].startswith("https://")
            assert preset["model"]


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов ИИ")


if __name__ == "__main__":
    main()
