"""Фейковый HTTP-слой для тестов ИИ: имитирует requests.Session.

Ни один тест не должен ходить в сеть и зависеть от запущенного Ollama,
поэтому облачный клиент и проверка локальной модели получают этот объект
вместо `requests.Session`: маршруты задаются подстрокой URL.

Пример:
    session = FakeSession([
        ("GET", "/models", models_response(["gpt-4o-mini"])),
        ("POST", "/chat/completions", chat_response("Привет")),
    ])
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional, Union

import requests

ResponseOrFactory = Union["FakeResponse", Callable[[str, dict[str, Any]], "FakeResponse"]]


class FakeResponse:
    """Мини-ответ requests: status_code, text, json(), iter_lines()."""

    def __init__(
        self,
        status_code: int = 200,
        payload: Any = None,
        *,
        text: str = "",
        lines: Optional[list[str]] = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        if text:
            self.text = text
        elif payload is not None:
            self.text = json.dumps(payload, ensure_ascii=False)
        else:
            self.text = ""
        self._lines = lines or []

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("в ответе нет JSON")
        return self._payload

    def iter_lines(self):
        for line in self._lines:
            yield line.encode("utf-8") if isinstance(line, str) else line

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def close(self) -> None:
        pass


class FakeSession:
    """requests.Session-совместимый объект с маршрутами по подстроке URL."""

    def __init__(self, routes: Optional[list[tuple[str, str, ResponseOrFactory]]] = None) -> None:
        self.routes: list[tuple[str, str, ResponseOrFactory]] = list(routes or [])
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False

    def route(self, method: str, contains: str, response: ResponseOrFactory) -> "FakeSession":
        self.routes.append((method, contains, response))
        return self

    def _handle(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))

        for route_method, contains, response in self.routes:
            if route_method == method and contains in url:
                if callable(response):
                    return response(url, kwargs)
                return response

        # Неизвестный маршрут = сервер недоступен (как закрытый порт).
        raise requests.exceptions.ConnectionError(f"нет маршрута: {method} {url}")

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._handle("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._handle("POST", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._handle("DELETE", url, **kwargs)

    def close(self) -> None:
        self.closed = True

    # ── Удобные проверки ────────────────────────────────────────────

    def urls(self, method: Optional[str] = None) -> list[str]:
        return [
            url for call_method, url, _ in self.calls if method is None or call_method == method
        ]

    def json_bodies(self, method: str) -> list[dict[str, Any]]:
        return [
            kwargs.get("json") or {}
            for call_method, _url, kwargs in self.calls
            if call_method == method
        ]


# ── Готовые ответы ──────────────────────────────────────────────────


def models_response(model_ids: list[str]) -> FakeResponse:
    return FakeResponse(200, {"object": "list", "data": [{"id": m} for m in model_ids]})


def chat_response(content: str) -> FakeResponse:
    return FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


def error_response(status_code: int, text: str = "") -> FakeResponse:
    return FakeResponse(status_code, None, text=text or f"HTTP {status_code}")


def ollama_tags_response(models: list[str]) -> FakeResponse:
    return FakeResponse(200, {"models": [{"name": m} for m in models]})


def ollama_pull_response(lines: list[str]) -> FakeResponse:
    return FakeResponse(200, None, lines=lines)


def network_failure(url: str = "", kwargs: Optional[dict[str, Any]] = None) -> FakeResponse:
    """Фабрика, бросающая ConnectionError на любой запрос (сервер недоступен)."""
    raise requests.exceptions.ConnectionError(f"сервер недоступен: {url}")
