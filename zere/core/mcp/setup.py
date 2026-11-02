"""Установка MCP-сервера браузера: запись `config/mcp.json`.

Установщик (`installer/install.ps1`) сам скачивает Node.js и пакет
`@playwright/mcp` в `tools\\`, но то, *чем* запускается плагин браузера,
задаётся файлом `config/mcp.json`. Этот модуль пишет туда сервер
`playwright` — и делает это кодом на Python, а не `ConvertTo-Json`, потому
что тот же файл правят ещё два места: вкладка «Плагины» панели (выбор
браузера) и ручное редактирование (свои серверы, хранилище заметок).

Правила слияния:

- файла нет — создаётся `{"servers": {"playwright": ...}}`, плагин включён;
- сервера нет — дописывается, остальные серверы и их ключи не трогаются;
- сервер запускается через `npx` (значение из `config/mcp.example.json`) —
  `command`/`args` заменяются на локальные `node.exe` + `cli.js`, а
  `enabled`, `browser`, `browserPath` и таймауты сохраняются;
- сервер уже запускается нашим локальным Node.js, но из другого места
  (папку установки перенесли) — пути обновляются;
- сервер запускается чем-то своим — файл не меняется: чужой запуск не
  переписываем, только сообщаем об этом.

CLI (его вызывает установщик; вывод — ASCII, чтобы не зависеть от кодовой
страницы консоли Windows, русский текст печатает сам установщик):

    python -m zere.core.mcp.setup --node C:\\ZERE\\tools\\node\\node.exe ^
        --package C:\\ZERE\\tools\\mcp\\node_modules\\@playwright\\mcp\\cli.js
    python -m zere.core.mcp.setup --npx-fallback
    python -m zere.core.mcp.setup --check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from zere import paths
from zere.core.security.file_access import restrict_to_owner

#: Ключ сервера в `config/mcp.json` (его читает PlaywrightMcpPlugin).
SERVER_ID = "playwright"
#: Пакет npm и его версия. Версия обязана совпадать с `$PlaywrightMcpVersion`
#: в `installer/install.ps1` — совпадение проверяет tests/test_installer.py.
PACKAGE = "@playwright/mcp"
VERSION = "0.0.83"

DEFAULT_BROWSER = "edge"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_STARTUP_TIMEOUT_SECONDS = 180.0

#: Имена `npx` на Windows (npm ставит `.cmd`).
_NPX_NAMES = frozenset({"npx", "npx.cmd", "npx.exe", "npx.bat"})
#: Имена `node`, которыми запускается установленный пакет.
_NODE_NAMES = frozenset({"node", "node.exe"})

#: Хвост пути к точке входа пакета: по нему узнаётся «наш» локальный запуск.
_ENTRY_TAIL = "node_modules/@playwright/mcp/cli.js"


def npx_command() -> tuple[str, list[str]]:
    """Команда запуска через `npx` (значение по умолчанию из образца)."""
    return "npx", ["-y", f"{PACKAGE}@{VERSION}"]


def _basename(command: str) -> str:
    """Имя исполняемого файла без каталога — для любых слэшей."""
    return command.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].strip().lower()


def _entry_command(entry: dict[str, Any]) -> str:
    return str(entry.get("command") or entry.get("Command") or "").strip()


def _entry_args(entry: dict[str, Any]) -> list[str]:
    raw = entry.get("args")
    if raw is None:
        raw = entry.get("arguments")

    return [str(item) for item in raw] if isinstance(raw, list) else []


def _is_npx_entry(entry: dict[str, Any]) -> bool:
    """Запуск через `npx` (наш собственный прежний вариант)."""
    command = _entry_command(entry)

    if not command:
        # Команды нет, но в аргументах уже указан наш пакет — считаем npx.
        return PACKAGE in " ".join(_entry_args(entry))

    return _basename(command) in _NPX_NAMES


def _is_local_entry(entry: dict[str, Any]) -> bool:
    """Запуск через установленный в `tools\\` пакет (наш прежний вариант)."""
    command = _entry_command(entry)

    if _basename(command) not in _NODE_NAMES:
        return False

    return any(
        arg.replace("\\", "/").lower().endswith(_ENTRY_TAIL) for arg in _entry_args(entry)
    )


def _same_entry(entry: dict[str, Any], command: str, args: Sequence[str]) -> bool:
    """Уже запускается ровно этой командой и аргументами."""
    current = _entry_command(entry)

    if current.lower() != str(command).lower():
        return False

    return [item.lower() for item in _entry_args(entry)] == [
        str(item).lower() for item in args
    ]


def server_entry(
    command: str,
    args: Sequence[str],
    *,
    browser: str = DEFAULT_BROWSER,
    enabled: bool = True,
) -> dict[str, Any]:
    """Запись сервера `playwright` в формате `config/mcp.json`."""
    return {
        "enabled": bool(enabled),
        "command": str(command),
        "args": [str(item) for item in args],
        "browser": browser,
        "browserPath": "",
        "requestTimeoutSeconds": DEFAULT_REQUEST_TIMEOUT_SECONDS,
        "startupTimeoutSeconds": DEFAULT_STARTUP_TIMEOUT_SECONDS,
        "allowedTools": [],
    }


def local_server_entry(
    node_exe: str, cli_js: str, *, browser: str = DEFAULT_BROWSER, enabled: bool = True
) -> dict[str, Any]:
    """Сервер на локальном `node.exe` + `cli.js` (так ставит установщик)."""
    return server_entry(node_exe, [cli_js], browser=browser, enabled=enabled)


def ensure_playwright_entry(
    config: dict[str, Any],
    *,
    command: str,
    args: Sequence[str],
    browser: str = DEFAULT_BROWSER,
    enabled: bool = True,
) -> tuple[dict[str, Any], str]:
    """Дописывает сервер `playwright` в конфиг. Возвращает (конфиг, что сделано).

    Функция чистая: ничего не пишет на диск, поэтому правила слияния
    проверяются тестами без временных файлов. `ValueError` — конфиг не той
    формы: файл тогда не перезаписывается (иначе чужие настройки потерялись
    бы при разборе битого JSON).
    """
    if not isinstance(config, dict):
        raise ValueError("config/mcp.json must be a JSON object")

    servers = config.get("servers")

    if servers is None:
        servers = {}
        config["servers"] = servers

    if not isinstance(servers, dict):
        raise ValueError("'servers' in config/mcp.json must be an object")

    current = servers.get(SERVER_ID)

    if current is None:
        servers[SERVER_ID] = server_entry(command, args, browser=browser, enabled=enabled)

        return config, "created and enabled"

    if not isinstance(current, dict):
        raise ValueError(f"'servers.{SERVER_ID}' in config/mcp.json must be an object")

    if _same_entry(current, command, args):
        return config, "already configured"

    was_npx = _is_npx_entry(current)
    was_local = _is_local_entry(current)

    if was_npx or was_local:
        # Наш прежний запуск: меняем только команду и аргументы, остальные
        # настройки (включённость, выбранный браузер, таймауты, allowlist)
        # сохраняются как есть.
        defaults = server_entry(command, args, browser=browser, enabled=enabled)
        current["command"] = defaults["command"]
        current["args"] = defaults["args"]

        for key, value in defaults.items():
            if key not in current:
                current[key] = value

        return config, (
            "updated from npx to the local Node.js"
            if was_npx
            else "paths updated to the current install"
        )

    return config, "kept as is (custom command)"


def read_config_file(path: Path) -> dict[str, Any]:
    """Читает `config/mcp.json`. Нет файла — пустой конфиг."""
    if not path.is_file():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8-sig"))

    if not isinstance(raw, dict):
        raise ValueError("config/mcp.json must be a JSON object")

    return raw


def write_config_file(path: Path, config: dict[str, Any]) -> None:
    """Пишет конфиг атомарно и сужает права (в env бывают токены серверов)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)
    restrict_to_owner(path)


def ensure_config_file(
    path: Optional[Path] = None,
    *,
    node_exe: Optional[str] = None,
    cli_js: Optional[str] = None,
    npx_fallback: bool = False,
    browser: str = DEFAULT_BROWSER,
    enabled: bool = True,
) -> str:
    """Приводит `config/mcp.json` к рабочему состоянию. Возвращает действие.

    `npx_fallback` — пакет поставить не удалось (нет сети/npm): пишем
    запуск через `npx`, чтобы плагин заработал, как только появится сеть.
    """
    target = path if path is not None else paths.mcp_config_path()

    if npx_fallback or not node_exe or not cli_js:
        command, args = npx_command()
    else:
        command, args = str(node_exe), [str(cli_js)]

    config = read_config_file(target)
    config, action = ensure_playwright_entry(
        config, command=command, args=args, browser=browser, enabled=enabled
    )

    write_config_file(target, config)

    return action


def server_state(path: Optional[Path] = None) -> dict[str, Any]:
    """Состояние сервера `playwright` для отчёта: без правок и запуска."""
    target = path if path is not None else paths.mcp_config_path()
    state: dict[str, Any] = {
        "config": str(target),
        "present": target.is_file(),
        "configured": False,
        "enabled": False,
        "command": "",
        "local": False,
    }

    try:
        config = read_config_file(target)
    except (OSError, ValueError):
        state["error"] = "unreadable"
        return state

    servers = config.get("servers")
    entry = servers.get(SERVER_ID) if isinstance(servers, dict) else None

    if not isinstance(entry, dict):
        return state

    state["configured"] = bool(_entry_command(entry))
    state["enabled"] = bool(entry.get("enabled") or entry.get("Enabled") or False)
    state["command"] = " ".join([_entry_command(entry), *_entry_args(entry)]).strip()
    state["local"] = _is_local_entry(entry)

    return state


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m zere.core.mcp.setup",
        description="Записать сервер браузера (Playwright MCP) в config/mcp.json.",
    )
    parser.add_argument("--config", default="", help="путь к mcp.json (по умолчанию config/mcp.json)")
    parser.add_argument("--node", default="", help="путь к node.exe из установки")
    parser.add_argument("--package", default="", help="путь к cli.js пакета @playwright/mcp")
    parser.add_argument(
        "--npx-fallback",
        action="store_true",
        help="пакет не установлен: писать запуск через npx",
    )
    parser.add_argument("--no-enable", action="store_true", help="не включать сервер")
    parser.add_argument("--check", action="store_true", help="только показать состояние")
    arguments = parser.parse_args(argv)

    path = Path(arguments.config) if arguments.config else None

    if arguments.check:
        state = server_state(path)
        print(
            "mcp server %s: configured=%s enabled=%s local=%s command=%s"
            % (
                SERVER_ID,
                state["configured"],
                state["enabled"],
                state["local"],
                state["command"] or "-",
            )
        )

        return 0

    if not arguments.npx_fallback and not (arguments.node and arguments.package):
        print(
            "mcp config: --node and --package are required (or --npx-fallback)",
            file=sys.stderr,
        )

        return 2

    try:
        action = ensure_config_file(
            path,
            node_exe=arguments.node or None,
            cli_js=arguments.package or None,
            npx_fallback=arguments.npx_fallback,
            enabled=not arguments.no_enable,
        )
    except (OSError, ValueError) as ex:
        print(f"mcp config: not changed ({ex})", file=sys.stderr)

        return 2

    print(f"mcp server {SERVER_ID}: {action}")

    return 0


if __name__ == "__main__":  # pragma: no cover - тонкая обёртка CLI
    raise SystemExit(main())
