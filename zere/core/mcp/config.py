"""Настройки MCP-серверов: `config/mcp.json`.

Файл локальный (в .gitignore): в нём пути к хранилищу заметок и другие
машинно-зависимые значения. Образец — `config/mcp.example.json`.

Формат намеренно совпадает по духу с `config/ai.json`: ключи snake_case,
читается и camelCase (у проекта две редакции, и обе уже наступали на то,
что чужие настройки молча сбрасывались).

```json
{
  "servers": {
    "playwright": {
      "enabled": false,
      "command": "npx",
      "args": ["-y", "@playwright/mcp@0.0.83"],
      "requestTimeoutSeconds": 60
    }
  }
}
```
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from zere import paths
from zere.core.security.file_access import restrict_to_owner

DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
DEFAULT_STARTUP_TIMEOUT_SECONDS = 60.0

#: Поля, которые разбираются в именованные атрибуты McpServerSettings.
#: Всё остальное попадает в `options` и читается конкретным плагином.
_KNOWN_SERVER_KEYS = frozenset(
    {
        "enabled",
        "Enabled",
        "command",
        "Command",
        "args",
        "arguments",
        "env",
        "environment",
        "cwd",
        "workingDirectory",
        "requestTimeoutSeconds",
        "request_timeout_seconds",
        "startupTimeoutSeconds",
        "startup_timeout_seconds",
        "allowedTools",
        "allowed_tools",
    }
)


@dataclass
class McpServerSettings:
    """Один сервер из `config/mcp.json`."""

    server_id: str
    enabled: bool = False
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT_SECONDS
    #: Необязательный allowlist имён инструментов. Пусто — разрешены все.
    allowed_tools: list[str] = field(default_factory=list)
    #: Ключи, которых нет в общих полях (например `browser` у Playwright).
    #: Их читает конкретный плагин: у каждого сервера свои настройки, и
    #: тащить их в общую схему незачем.
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        """Есть ли чем запускать сервер (команда задана)."""
        return bool(self.command.strip())

    def allows(self, tool_name: str) -> bool:
        """Разрешён ли инструмент этим сервером (allowlist из настроек)."""
        if not self.allowed_tools:
            return True

        return tool_name in self.allowed_tools

    def describe_command(self) -> str:
        """Точная команда запуска для показа пользователю (SEP-1024)."""
        parts = [self.command, *self.args]
        return " ".join(f'"{part}"' if " " in part else part for part in parts)


def _first(data: dict[str, Any], *keys: str) -> Any:
    """Первое непустое значение по списку ключей (snake_case и camelCase)."""
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]

    return None


def _as_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    return number if number > 0 else default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item) for item in value if isinstance(item, (str, int, float))]


def _as_str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    return {str(key): str(item) for key, item in value.items()}


def _server_from_dict(server_id: str, data: Any) -> McpServerSettings:
    if not isinstance(data, dict):
        return McpServerSettings(server_id=server_id)

    cwd = _first(data, "cwd", "workingDirectory")

    return McpServerSettings(
        server_id=server_id,
        enabled=bool(_first(data, "enabled", "Enabled") or False),
        command=str(_first(data, "command", "Command") or ""),
        args=_as_str_list(_first(data, "args", "arguments")),
        env=_as_str_dict(_first(data, "env", "environment")),
        cwd=str(cwd) if cwd else None,
        request_timeout=_as_float(
            _first(data, "requestTimeoutSeconds", "request_timeout_seconds"),
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
        startup_timeout=_as_float(
            _first(data, "startupTimeoutSeconds", "startup_timeout_seconds"),
            DEFAULT_STARTUP_TIMEOUT_SECONDS,
        ),
        allowed_tools=_as_str_list(_first(data, "allowedTools", "allowed_tools")),
        options={
            key: value
            for key, value in data.items()
            if key not in _KNOWN_SERVER_KEYS
        },
    )


def load_mcp_config(path: Optional[Path] = None) -> dict[str, McpServerSettings]:
    """Читает настройки серверов. Отсутствие файла — не ошибка (пусто).

    Битый JSON тоже не роняет старт: MCP — расширение, и его поломка не
    должна мешать ZERE отвечать.
    """
    config_path = path if path is not None else paths.mcp_config_path()

    if not config_path.is_file():
        return {}

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    servers = raw.get("servers")

    if not isinstance(servers, dict):
        return {}

    return {
        str(server_id): _server_from_dict(str(server_id), data)
        for server_id, data in servers.items()
    }


def load_server(server_id: str, path: Optional[Path] = None) -> McpServerSettings:
    """Настройки одного сервера (или пустые, если его нет в конфиге)."""
    return load_mcp_config(path).get(server_id, McpServerSettings(server_id=server_id))


def set_server_option(
    server_id: str,
    key: str,
    value: Any,
    path: Optional[Path] = None,
) -> bool:
    """Меняет один ключ сервера в `config/mcp.json`, сохраняя остальное.

    Нужно для смены браузера из чата: выбор должен пережить перезапуск ZERE,
    а не жить до конца процесса. Файл не переписывается целиком «по памяти» —
    читаем текущий JSON, правим один ключ и пишем обратно, поэтому чужие
    настройки и комментарии-поля не теряются.

    Возвращает False, если файла нет (тогда менять нечего — плагин выключен).
    """
    config_path = path if path is not None else paths.mcp_config_path()

    if not config_path.is_file():
        return False

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(raw, dict):
        return False

    servers = raw.get("servers")

    if not isinstance(servers, dict):
        return False

    server = servers.get(server_id)

    if not isinstance(server, dict):
        return False

    server[key] = value

    try:
        config_path.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError:
        return False

    # Файл локальный, но у части серверов в env бывают токены — сужаем права,
    # как для config/ai.json и config/panel.token.
    restrict_to_owner(config_path)

    return True
