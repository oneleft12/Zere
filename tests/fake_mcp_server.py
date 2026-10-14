"""Фейковый MCP-сервер для тестов (stdio, JSON-RPC 2.0).

Живой сервер в тестах не поднять: `npx @playwright/mcp` тянет из сети
зависимости и требует установленного браузера. Этот скрипт говорит на том же
протоколе и умеет воспроизводить нужные сбои — по образцу `tests/fake_http.py`.

Режим задаётся переменной `FAKE_MCP_MODE`:

- `normal` — обычная работа: `echo` отвечает текстом, `boom` — ошибкой
  инструмента (`isError: true`, как у реальных серверов);
- `protocol_error` — `tools/call` отвечает JSON-RPC ошибкой (-32601);
- `crash_after_init` — выходит сразу после инициализации;
- `hang` — не отвечает на `tools/call` (проверка таймаута);
- `noise` — пишет в stdout не-JSON (сервер логирует не в stderr);
- `bad_version` — отвечает UnsupportedProtocolVersionError (-32022);
- `server_request` — посылает клиенту запрос и ждёт ответа.

Запуск: `python3 tests/fake_mcp_server.py` (argv не используется).
"""

from __future__ import annotations

import json
import os
import sys
import time

MODE = os.environ.get("FAKE_MCP_MODE", "normal")

TOOLS = [
    {
        "name": "echo",
        "description": "Возвращает переданный текст",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "boom",
        "description": "Всегда возвращает ошибку инструмента",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "secret",
        "description": "Инструмент для проверки allowlist",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def result(request_id: object, payload: dict) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": payload})


def error(request_id: object, code: int, message: str, data: object = None) -> None:
    payload: dict = {"code": code, "message": message}

    if data is not None:
        payload["data"] = data

    send({"jsonrpc": "2.0", "id": request_id, "error": payload})


def handle(message: dict) -> None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        if MODE == "bad_version":
            error(
                request_id,
                -32022,
                "Unsupported protocol version",
                {"supported": ["2026-07-28"], "requested": "2025-11-25"},
            )
            return

        result(
            request_id,
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "fake-mcp", "version": "0.1.0"},
            },
        )

        if MODE == "crash_after_init":
            sys.exit(0)

        if MODE == "server_request":
            # Запрос от сервера к клиенту: клиент обязан ответить, иначе
            # сервер будет ждать вечно.
            send(
                {
                    "jsonrpc": "2.0",
                    "id": "srv-1",
                    "method": "sampling/createMessage",
                    "params": {},
                }
            )
        return

    if method == "notifications/initialized":
        return

    if method == "tools/list":
        result(request_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")

        if MODE == "protocol_error":
            error(request_id, -32601, "Method not found")
            return

        if MODE == "hang":
            time.sleep(60)
            return

        if name == "echo":
            text = (params.get("arguments") or {}).get("text", "")
            result(
                request_id,
                {"content": [{"type": "text", "text": f"эхо: {text}"}]},
            )
            return

        if name == "boom":
            result(
                request_id,
                {
                    "content": [{"type": "text", "text": "инструмент сломался"}],
                    "isError": True,
                },
            )
            return

        if name == "secret":
            result(request_id, {"content": [{"type": "text", "text": "секрет"}]})
            return

        error(request_id, -32602, f"Unknown tool: {name}")
        return

    if request_id is not None:
        error(request_id, -32601, "Method not found")


def main() -> None:
    if MODE == "noise":
        sys.stdout.write("это не JSON, а лог сервера\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()

        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log(f"не разобрал строку: {line[:80]}")
            continue

        handle(message)


if __name__ == "__main__":
    main()
