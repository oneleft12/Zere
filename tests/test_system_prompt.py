"""P1-2: system-промпт передаётся ровно один раз — полем system Ollama API.

Раньше модель получала его дважды: PromptBuilder встраивал в prompt,
клиент дополнительно префиксовал prompt, а поле system не заполнялось.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.ai.ollama_client import OllamaClient
from zere.ai.system_prompt import SystemPrompt
from zere.core.handlers.ai_handler import AIHandler

SYSTEM_PROMPT = "Ты — ZERE. Отвечай кратко."
USER_MESSAGE = "привет, что такое гравитация"


# ── Подменные объекты для AIHandler ───────────────────────────────


class _FakeAI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, float | None]] = []

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        self.calls.append((prompt, system_prompt, temperature))
        return "ответ модели"


class _FakeContext:
    def build_memory(self) -> str:
        return "любит пиццу"

    def build_history(self) -> str:
        return "Вы: привет"


class _FakePluginManager:
    active_personality = None


# ── Захват запроса к «Ollama» ─────────────────────────────────────


class _CaptureHandler(BaseHTTPRequestHandler):
    captured: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        type(self).captured.append(json.loads(body.decode("utf-8")))

        payload = b'{"response":"ok","done":true}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        pass


def _start_stub() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/"


# ── Тесты ─────────────────────────────────────────────────────────


def test_handler_does_not_embed_system_into_prompt() -> None:
    fake_ai = _FakeAI()
    handler = AIHandler(fake_ai, _FakeContext(), _FakePluginManager())  # type: ignore[arg-type]

    result = handler.handle(USER_MESSAGE)

    assert result == "ответ модели"
    prompt, system_prompt, temperature = fake_ai.calls[0]

    # system передан отдельно...
    assert system_prompt is not None
    assert system_prompt.startswith("Ты — ZERE.")
    # ...но НЕ встроен в prompt (иначе двойной system prompt, P1-2)
    assert "Ты — ZERE" not in prompt
    # контекст и сообщение при этом на месте
    assert "любит пиццу" in prompt
    assert USER_MESSAGE in prompt
    # без личности температура не навязывается
    assert temperature is None


class _FakePersonality:
    system_prompt = "Ты — ZERE, дружелюбный AI-ассистент."
    temperature = 0.7
    style = "Friendly"


class _FakePluginManagerWithPersonality:
    active_personality = _FakePersonality()


def test_personality_prompt_keeps_russian_rule() -> None:
    """Правило «отвечай только по-русски» обязано быть и при активной личности.

    Промпты личностей (Friendly и др.) про язык не говорят ничего, а раньше
    правило жило только в SystemPrompt.Zere — то есть в обычном режиме
    (личность включена по умолчанию) модель его вообще не получала и уходила
    в английский/китайский.
    """
    fake_ai = _FakeAI()
    handler = AIHandler(  # type: ignore[arg-type]
        fake_ai, _FakeContext(), _FakePluginManagerWithPersonality()
    )

    handler.handle(USER_MESSAGE)
    _, system_prompt, _ = fake_ai.calls[0]

    assert system_prompt is not None
    assert _FakePersonality.system_prompt in system_prompt, "промпт личности потерялся"
    assert "ЯЗЫК ОТВЕТА" in system_prompt
    assert "только на русском языке" in system_prompt
    assert "не переключайся на английский" in system_prompt


def test_client_sends_system_field_not_prompt_prefix() -> None:
    _CaptureHandler.captured.clear()
    server, url = _start_stub()

    try:
        client = OllamaClient(model="test-model", timeout_minutes=1)
        client._resolved_url = url

        answer = client.generate(USER_MESSAGE, system_prompt=SYSTEM_PROMPT, temperature=0.7)
    finally:
        server.shutdown()
        server.server_close()

    assert answer == "ok"
    assert len(_CaptureHandler.captured) == 1

    body = _CaptureHandler.captured[0]

    # system — отдельным полем Ollama API
    assert body["system"] == SYSTEM_PROMPT
    # prompt несёт сообщение пользователя как есть (без префикса и дубля)
    assert body["prompt"] == USER_MESSAGE
    assert SYSTEM_PROMPT not in body["prompt"]
    assert "Пользователь:" not in body["prompt"]
    assert body["model"] == "test-model"
    # options: temperature + num_ctx (этап 1 — фиксированный размер
    # контекста ускоряет инференс, анализ S5)
    assert body["options"] == {"num_ctx": 2048, "temperature": 0.7}
    # keep_alive из конфига: -1 — модель не выгружается из Ollama (S5)
    assert body["keep_alive"] == -1
    # think=false: reasoning-трейс на английском съедает сотни токенов,
    # на слабом CPU это десятки секунд на ответ (и русский «уплывает»)
    assert body["think"] is False


def test_client_falls_back_to_builtin_system_prompt() -> None:
    _CaptureHandler.captured.clear()
    server, url = _start_stub()

    try:
        client = OllamaClient(model="test-model", timeout_minutes=1)
        client._resolved_url = url

        client.generate(USER_MESSAGE)
    finally:
        server.shutdown()
        server.server_close()

    body = _CaptureHandler.captured[0]
    assert body["system"] == SystemPrompt.Zere
    assert body["prompt"] == USER_MESSAGE


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов P1-2")


if __name__ == "__main__":
    main()
