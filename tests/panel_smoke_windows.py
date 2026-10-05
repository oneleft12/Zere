"""Проверка опубликованной C#-панели (Windows-сторона, только stdlib).

Запускается Windows-интерпретатором Python: сервер панели слушает 127.0.0.1
на Windows, поэтому из WSL он недоступен (виртуальные сети не пересекаются).
Проверяет, что живые эндпоинты отвечают и что статические файлы отдаются
с подставленным токеном.

Запуск:
    python.exe tests/panel_smoke_windows.py --token <из config/panel.token>
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"

# (метод, путь, тело|None) — по одному представителю каждого экрана панели
REQUESTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/health", None),
    ("GET", "/api/config", None),
    ("GET", "/api/personality", None),
    ("GET", "/api/voice/mode", None),
    ("GET", "/api/processes?limit=5", None),
    ("GET", "/api/apps?limit=5", None),
    ("GET", "/api/plugins", None),
    ("GET", "/api/logs?limit=5", None),
    ("GET", "/api/history?limit=5", None),
    ("GET", "/api/memory?limit=5", None),
    ("GET", "/api/voice", None),
]


def call(method: str, path: str, body: dict | None, token: str) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("X-ZERE-Token", token)

    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    failures = 0

    for method, path, body in REQUESTS:
        status, payload = call(method, path, body, args.token)
        ok = status == 200
        failures += 0 if ok else 1
        print(f"{'OK ' if ok else 'FAIL'} {status} {method} {path} {payload[:90]}")

    # Статика: сервер обязан подставить токен в meta (имя — zere-token)
    status, html = call("GET", "/", None, args.token)

    if status == 200 and "__ZERE_TOKEN__" not in html and 'name="zere-token"' in html:
        print("OK  200 GET / (токен подставлен, meta zere-token на месте)")
    else:
        failures += 1
        print(f"FAIL {status} GET / (плейсхолдер токена или meta zere-token)")

    # Без токена — 401 (значение только ASCII: HTTP-заголовок кодируется latin-1)
    status, _ = call("GET", "/api/health", None, "wrong-token")
    if status == 401:
        print("OK  401 GET /api/health без верного токена")
    else:
        failures += 1
        print(f"FAIL {status} GET /api/health — ожидался 401")

    print(f"\nПРОВЕРЕНО: {len(REQUESTS) + 2} запросов, ошибок: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
