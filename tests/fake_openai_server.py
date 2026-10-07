"""Фейковый OpenAI-совместимый провайдер для проверки ИИ без интернета.

Поднимается локально (по умолчанию http://127.0.0.1:8123/v1) и отвечает как
облачный API: `GET /models` и `POST /chat/completions`, а на «плохих»
ключах — понятными ошибками провайдера:

| Ключ                       | Ответ                          |
|----------------------------|--------------------------------|
| `sk-good-abcdefghijklmnop` | 200 (список моделей, ответ чата) |
| `sk-nocredit-000000000000` | 402 — «нет средств»             |
| `sk-ratelimit-00000000000` | 429 — «лимит запросов»          |
| любой другой               | 401 — «неверный ключ»           |

Запуск:
    python tests/fake_openai_server.py [порт]

Используется проверкой `tests/check_ai_contract_external.py --full` и
CI-джобой C#-редакции: так путь «ключ → проверка → облачный чат»
проверяется на обеих редакциях без обращения к настоящим API.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD_KEY = "sk-good-abcdefghijklmnop"
NO_CREDIT_KEY = "sk-nocredit-000000000000"
RATE_LIMIT_KEY = "sk-ratelimit-00000000000"
DEFAULT_PORT = 8123


class FakeOpenAiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:
        """Тишина в логах: сервер поднимается в фоне тестов и CI."""

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _key(self) -> str:
        auth = self.headers.get("Authorization", "")

        return auth[len("Bearer ") :] if auth.startswith("Bearer ") else ""

    def _failure(self) -> tuple[int, str] | None:
        """Ответ-отказ по ключу: (статус, код) или None, если ключ рабочий."""
        key = self._key()

        if key == GOOD_KEY:
            return None
        if key == NO_CREDIT_KEY:
            return 402, "AI_NO_CREDITS"
        if key == RATE_LIMIT_KEY:
            return 429, "AI_RATE_LIMIT"
        return 401, "AI_KEY_INVALID"

    def do_GET(self) -> None:  # noqa: N802 — имя из BaseHTTPRequestHandler
        if not self.path.endswith("/models"):
            self._json(404, {"error": "not found"})
            return

        failure = self._failure()

        if failure is not None:
            status, code = failure
            self._json(status, {"error": {"message": code}})
            return

        self._json(200, {"object": "list", "data": [{"id": "test-model"}]})

    def do_POST(self) -> None:  # noqa: N802 — имя из BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)

        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": "not found"})
            return

        failure = self._failure()

        if failure is not None:
            status, code = failure
            self._json(status, {"error": {"message": code}})
            return

        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        # Минимальный тестовый запрос (max_tokens=1) и обычный чат
        if body.get("max_tokens") == 1:
            content = "pong"
        else:
            messages = body.get("messages") or [{}]
            prompt = messages[-1].get("content", "")
            system = messages[0].get("content", "") if len(messages) > 1 else ""
            content = (
                f"ОТВЕТ ОБЛАКА [{body.get('model', '?')}]: {prompt[:40]}"
                f" | system: {'да' if system else 'нет'}"
            )

        self._json(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), FakeOpenAiHandler)
    print(f"[fake-openai] http://127.0.0.1:{port}/v1 (ключ: {GOOD_KEY})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
