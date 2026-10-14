"""Минимальный MCP-клиент (stdio, JSON-RPC 2.0).

Зачем свой клиент, а не официальный SDK: ZERE не тянет лишние зависимости
(официальный `mcp` везёт anyio/httpx/pydantic), а нужен здесь узкий срез
протокола — подключиться, узнать инструменты, вызвать инструмент. Ровно то же
решение принято для плагина Krita (свой JSON-протокол по TCP).

**Поколение протокола.** Поддерживается handshake-поколение (ревизии
`2025-11-25` и раньше): `initialize` → `notifications/initialized` →
`tools/list` → `tools/call`. Проверено на живых серверах: `@playwright/mcp`
0.0.83 и `seekstone` 0.22.1 оба согласовали `protocolVersion` `2025-11-25`.

Ревизия `2026-07-28` отказалась от handshake (версия и идентичность идут в
`_meta` каждого запроса, появился обязательный `server/discover`) — она здесь
не реализована осознанно: цель — работать с уже существующими серверами.
Если сервер поддерживает только новую ревизию, он вернёт
`UnsupportedProtocolVersionError` (-32022), и это будет видно в тексте ошибки.

**Формы ответов (проверены на живых серверах).** Ошибка протокола приходит как
JSON-RPC `error` (`-32601` на неизвестный метод), а ошибка инструмента — внутри
`result` с `isError: true`. Клиент различает эти случаи.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

#: Ревизия протокола, которую объявляет клиент. Сервер отвечает своей —
#: принимаем любую (реальная практика: серверы соглашаются на эту).
PROTOCOL_VERSION = "2025-11-25"

CLIENT_NAME = "ZERE"

#: Сколько строк stderr сервера держим для диагностики.
_STDERR_TAIL_LINES = 40


class McpError(RuntimeError):
    """Сбой MCP: запуск сервера, протокол, таймаут."""

    def __init__(self, message: str, *, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class McpTool:
    """Инструмент сервера (`tools/list`)."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class McpToolResult:
    """Результат `tools/call`.

    `is_error` — ошибка самого инструмента (сервер вернул `isError: true`),
    а не сбой протокола: текст всё равно пригоден для показа пользователю.
    """

    text: str
    is_error: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


def resolve_command(command: str) -> list[str]:
    """Путь к исполняемому файлу команды (или сама команда, если не нашли).

    Обёртка `cmd /c` для `.cmd`/`.bat` здесь больше НЕ добавляется: у cmd своя
    обработка кавычек, и командную строку для неё нужно собирать иначе, чем
    список argv (см. `build_batch_command_line`). Для показа пользователю
    (SEP-1024) возвращается логическая команда, без служебной обёртки.
    """
    resolved = shutil.which(command)

    if resolved is None:
        # Не нашли — пусть Popen сообщит об этом сам (текст ошибки понятнее).
        return [command]

    return [resolved]


def is_batch_file(path: str) -> bool:
    """`.cmd`/`.bat`: CreateProcess не запускает их напрямую (WinError 193)."""
    return os.name == "nt" and path.lower().endswith((".cmd", ".bat"))


def build_batch_command_line(script: str, args: Sequence[str]) -> str:
    """Командная строка для `.cmd`/`.bat`, которую правильно поймёт `cmd /c`.

    Windows не запускает `.cmd` напрямую, поэтому идём через `cmd /c`. Но у cmd
    собственная обработка кавычек: если кавычек в строке больше двух, он снимает
    первую и последнюю. Из-за этого путь с пробелом
    (`C:\\Program Files\\nodejs\\npx.CMD`) разваливался на `C:\\Program`, и
    Opera GX — её путь тоже с пробелом — не запускалась. Проверено на живой
    Windows.

    Лечится «классической» формой: `subprocess` при `shell=True` сам оборачивает
    строку в кавычки, и после снятия внешней пары внутреннее квотирование
    остаётся целым.
    """
    return subprocess.list2cmdline([script, *args])


def tool_result_text(result: dict[str, Any]) -> str:
    """Собирает текст из content-блоков ответа `tools/call`.

    Блоки бывают не только текстовые; нетекстовые помечаем коротко, чтобы
    ответ не терялся молча.
    """
    blocks = result.get("content") or []

    if not isinstance(blocks, list):
        return ""

    parts: list[str] = []

    for block in blocks:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")

        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        elif block_type == "image":
            parts.append("[изображение]")
        elif block_type == "resource":
            parts.append("[ресурс]")
        elif block_type:
            parts.append(f"[{block_type}]")

    return "\n".join(parts)


class McpStdioClient:
    """Клиент одного MCP-сервера, запущенного как подпроцесс (stdio).

    Жизненный цикл: `start()` → `list_tools()` / `call_tool()` → `close()`.
    Класс не потокобезопасен по множественным одновременным вызовам, но
    сериализует запросы замком: конвейер ZERE вызывает инструменты
    последовательно, а замок защищает от случайного параллельного вызова.
    """

    def __init__(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
        name: str = "mcp",
        request_timeout: float = 60.0,
        startup_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self._program: str = resolve_command(command)[0]
        self._args: list[str] = [str(argument) for argument in args]
        self._argv: list[str] = [self._program, *self._args]
        self._env = {**os.environ, **(env or {})}
        self._cwd = cwd
        self._request_timeout = float(request_timeout)
        self._startup_timeout = float(startup_timeout)

        self._process: Optional[subprocess.Popen[str]] = None
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._stderr_tail: list[str] = []
        self._readers: list[threading.Thread] = []

        self.server_info: dict[str, Any] = {}
        self.protocol_version: str = ""
        self.capabilities: dict[str, Any] = {}

    # ── Жизненный цикл ──────────────────────────────────────────────

    @property
    def argv(self) -> list[str]:
        """Точная команда запуска — её показывает панель (требование SEP-1024)."""
        return list(self._argv)

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _spawn(self) -> subprocess.Popen[str]:
        """Запускает процесс сервера.

        Обычная команда запускается списком argv. `.cmd`/`.bat` (на Windows это
        `npx`) — строкой через `shell=True`: только так `cmd /c` не ломает
        кавычки в путях с пробелами.
        """
        options: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "env": self._env,
            "cwd": self._cwd,
        }

        if is_batch_file(self._program):
            return subprocess.Popen(
                build_batch_command_line(self._program, self._args),
                shell=True,
                **options,
            )

        return subprocess.Popen([self._program, *self._args], **options)

    def _kill_process(self, process: subprocess.Popen[str]) -> None:
        """Гасит сервер; для `.cmd` через `cmd /c` — вместе с потомками."""
        if is_batch_file(self._program) and os.name == "nt":
            # cmd.exe не убивает запущенный им процесс: без /T после каждого
            # перезапуска сервера оставался бы висящий node.exe.
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
                return
            except (OSError, subprocess.SubprocessError):
                pass  # ниже обычный путь

        try:
            process.terminate()
        except OSError:
            pass

    def start(self) -> None:
        """Запускает сервер и выполняет handshake."""
        if self.alive:
            return

        try:
            self._process = self._spawn()
        except OSError as ex:
            raise McpError(
                f"не удалось запустить «{self._program}»: {ex}. "
                f"Проверьте, что команда установлена и доступна в PATH."
            ) from ex

        self._start_readers()

        try:
            self._handshake()
        except McpError:
            self.close()
            raise
        except Exception as ex:  # noqa: BLE001 — любой сбой старта → McpError
            self.close()
            raise McpError(f"сбой инициализации MCP-сервера: {ex}") from ex

    def close(self) -> None:
        """Останавливает сервер. Повторный вызов безопасен."""
        process, self._process = self._process, None

        if process is None:
            return

        try:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass

        try:
            self._kill_process(process)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

        # Разбудить ожидающих: ответа уже не будет.
        self._wake_all_waiters()

    def _wake_all_waiters(self) -> None:
        """Сообщает всем ожидающим, что ответа не будет (`None`)."""
        with self._pending_lock:
            waiters = list(self._pending.values())
            self._pending.clear()

        for waiter in waiters:
            waiter.put(None)

    def __enter__(self) -> "McpStdioClient":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ── Протокол ────────────────────────────────────────────────────

    def list_tools(self) -> list[McpTool]:
        """`tools/list` → список инструментов сервера."""
        result = self._request("tools/list", {}, timeout=self._request_timeout)
        raw_tools = result.get("tools")

        if not isinstance(raw_tools, list):
            return []

        tools: list[McpTool] = []

        for item in raw_tools:
            if not isinstance(item, dict):
                continue

            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue

            schema = item.get("inputSchema")
            tools.append(
                McpTool(
                    name=name,
                    description=str(item.get("description") or ""),
                    input_schema=schema if isinstance(schema, dict) else {},
                )
            )

        return tools

    def call_tool(
        self, name: str, arguments: Optional[dict[str, Any]] = None
    ) -> McpToolResult:
        """`tools/call` → текст результата.

        Ошибка инструмента (`isError`) не поднимается исключением: это
        нормальный ответ, который нужно показать пользователю.
        """
        result = self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=self._request_timeout,
        )

        return McpToolResult(
            text=tool_result_text(result),
            is_error=bool(result.get("isError")),
            raw=result,
        )

    # ── Внутреннее ──────────────────────────────────────────────────

    def _handshake(self) -> None:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": _client_version()},
            },
            timeout=self._startup_timeout,
        )

        self.protocol_version = str(result.get("protocolVersion") or "")
        info = result.get("serverInfo")
        self.server_info = info if isinstance(info, dict) else {}
        caps = result.get("capabilities")
        self.capabilities = caps if isinstance(caps, dict) else {}

        # Уведомление об окончании инициализации: без него сервер не
        # обязан принимать обычные запросы.
        self._notify("notifications/initialized")

    def _start_readers(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        def pump_stdout() -> None:
            try:
                for line in process.stdout:
                    self._on_line(line)
            finally:
                # Процесс закрыл stdout — ответов больше не будет. Без этого
                # ожидающие запросы висели бы до таймаута и сообщали
                # «таймаут» вместо «сервер завершился».
                self._wake_all_waiters()

        def pump_stderr() -> None:
            if process.stderr is None:
                return
            for line in process.stderr:
                self._stderr_tail.append(line.rstrip("\n"))
                del self._stderr_tail[:-_STDERR_TAIL_LINES]

        self._readers = [
            threading.Thread(target=pump_stdout, name=f"mcp-{self.name}-out", daemon=True),
            threading.Thread(target=pump_stderr, name=f"mcp-{self.name}-err", daemon=True),
        ]

        for reader in self._readers:
            reader.start()

    def _on_line(self, line: str) -> None:
        text = line.strip()

        if not text:
            return

        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            # Сервер написал в stdout не-JSON (частая причина — логи не в
            # stderr). Молча пропускаем: это диагностика, не протокол.
            self._stderr_tail.append(f"[stdout не JSON] {text[:200]}")
            del self._stderr_tail[:-_STDERR_TAIL_LINES]
            return

        if not isinstance(message, dict):
            return

        message_id = message.get("id")

        # Ответ на наш запрос.
        if "method" not in message and message_id is not None:
            with self._pending_lock:
                waiter = self._pending.pop(message_id, None)
            if waiter is not None:
                waiter.put(message)
            return

        # Запрос сервера к клиенту (sampling/elicitation и пр.). Мы их не
        # поддерживаем, но обязаны ответить — иначе сервер будет ждать.
        if "method" in message and message_id is not None:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {
                        "code": -32601,
                        "message": f"Клиент ZERE не поддерживает метод {message.get('method')}",
                    },
                }
            )

        # Уведомления сервера (в том числе notifications/message) игнорируем.

    def _send(self, payload: dict[str, Any]) -> None:
        process = self._process

        if process is None or process.stdin is None:
            raise McpError("MCP-сервер не запущен")

        line = json.dumps(payload, ensure_ascii=False)

        with self._write_lock:
            try:
                process.stdin.write(line + "\n")
                process.stdin.flush()
            except (OSError, ValueError) as ex:
                raise McpError(
                    f"сервер закрыл ввод ({ex}).{self._stderr_hint()}"
                ) from ex

    def _notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        self._send(payload)

    def _request(
        self, method: str, params: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        with self._pending_lock:
            self._next_id += 1
            request_id = self._next_id
            waiter: queue.Queue = queue.Queue()
            self._pending[request_id] = waiter

        self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )

        try:
            message = waiter.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise McpError(
                f"таймаут {timeout:.0f} с на «{method}» MCP-сервера.{self._stderr_hint()}"
            ) from None

        if message is None:
            raise McpError(
                f"MCP-сервер завершился во время «{method}»."
                f"{self._stderr_hint()}"
            )

        error = message.get("error")

        if isinstance(error, dict):
            code = error.get("code")
            text = str(error.get("message") or "неизвестная ошибка")

            if code == -32022:
                data = error.get("data")
                supported = ""
                if isinstance(data, dict) and data.get("supported"):
                    supported = f" Сервер поддерживает: {data['supported']}."
                raise McpError(
                    f"сервер не поддерживает протокол {PROTOCOL_VERSION}.{supported}",
                    code=-32022,
                )

            raise McpError(f"ошибка MCP на «{method}»: {text}", code=code)

        result = message.get("result")

        return result if isinstance(result, dict) else {}

    def _stderr_hint(self) -> str:
        tail = [line for line in self._stderr_tail[-5:] if line.strip()]

        if not tail:
            return ""

        return " Вывод сервера: " + " | ".join(tail)


def _client_version() -> str:
    """Версия ZERE для clientInfo (без жёсткой константы в модуле)."""
    try:
        from zere.core.configuration.zere_config import ZereConfig

        return str(ZereConfig.load().version or "1.0.0")
    except Exception:  # noqa: BLE001 — версия не должна мешать подключению
        return "1.0.0"


def stop_all(clients: Iterable[McpStdioClient]) -> None:
    """Закрывает пачку клиентов, не роняя вызывающего."""
    for client in clients:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
