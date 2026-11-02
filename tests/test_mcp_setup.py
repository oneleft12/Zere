"""Тесты записи `config/mcp.json` при установке (zere/core/mcp/setup.py).

Установщик ставит Node.js и пакет `@playwright/mcp`, а этот модуль включает
сервер `playwright` в конфиг. Ломается здесь чаще всего одно: файл уже есть
(его правят вкладка «Плагины» и сам пользователь), и наивная перезапись
«по памяти» уничтожает выбранный браузер, сервер заметок или чужой запуск.

Запуск: `python3 tests/test_mcp_setup.py` или `pytest tests/ -q`.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.core.mcp.setup import (  # noqa: E402
    PACKAGE,
    SERVER_ID,
    VERSION,
    ensure_config_file,
    ensure_playwright_entry,
    main,
    npx_command,
    server_state,
)

NODE = r"C:\ZERE\tools\node\node.exe"
CLI_JS = r"C:\ZERE\tools\mcp\node_modules\@playwright\mcp\cli.js"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_creates_config_and_enables_server(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"

    assert ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS) == "created and enabled"

    config = read_json(path)
    server = config["servers"][SERVER_ID]

    assert server["enabled"] is True
    assert server["command"] == NODE
    assert server["args"] == [CLI_JS]
    assert server["browser"] == "edge"
    assert server["requestTimeoutSeconds"] > 0
    assert server["startupTimeoutSeconds"] > 0
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_migrates_npx_and_keeps_user_settings(tmp_path: Path) -> None:
    """Прежний запуск через npx переводится на локальный Node.js."""
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    SERVER_ID: {
                        "enabled": False,
                        "command": "npx",
                        "args": ["-y", "@playwright/mcp@0.0.83"],
                        "browser": "opera gx",
                        "browserPath": "C:\\Users\\me\\Opera GX\\opera.exe",
                        "startupTimeoutSeconds": 240,
                        "allowedTools": ["browser_navigate"],
                    },
                    "obsidian": {
                        "enabled": True,
                        "command": "npx",
                        "args": ["-y", "seekstone@0.22.1"],
                        "env": {"SEEKSTONE_VAULT": "D:\\Notes"},
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    action = ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS)

    server = read_json(path)["servers"][SERVER_ID]

    assert action == "updated from npx to the local Node.js"
    assert server["command"] == NODE
    assert server["args"] == [CLI_JS]
    # Настройки пользователя пережили миграцию.
    assert server["enabled"] is False
    assert server["browser"] == "opera gx"
    assert server["browserPath"] == r"C:\Users\me\Opera GX\opera.exe"
    assert server["startupTimeoutSeconds"] == 240
    assert server["allowedTools"] == ["browser_navigate"]
    # Чужой сервер не тронут.
    obsidian = read_json(path)["servers"]["obsidian"]
    assert obsidian["command"] == "npx"
    assert obsidian["env"] == {"SEEKSTONE_VAULT": "D:\\Notes"}


def test_custom_command_is_left_alone(tmp_path: Path) -> None:
    """Свой запуск (не npx и не наш tools\\mcp) не переписывается."""
    path = tmp_path / "mcp.json"
    original = {
        "servers": {
            SERVER_ID: {
                "enabled": True,
                "command": "C:\\custom\\mcp-server.exe",
                "args": ["--port", "1234"],
            }
        }
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    action = ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS)

    assert action == "kept as is (custom command)"
    assert read_json(path) == original


def test_second_run_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS)
    before = path.read_bytes()

    assert ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS) == "already configured"
    assert path.read_bytes() == before


def test_moved_install_updates_paths(tmp_path: Path) -> None:
    """Папку установки перенесли: пути в конфиге обновляются."""
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    SERVER_ID: {
                        "enabled": True,
                        "command": r"D:\Old\ZERE\tools\node\node.exe",
                        "args": [r"D:\Old\ZERE\tools\mcp\node_modules\@playwright\mcp\cli.js"],
                        "browser": "chrome",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    action = ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS)

    server = read_json(path)["servers"][SERVER_ID]

    assert action == "paths updated to the current install"
    assert server["command"] == NODE
    assert server["args"] == [CLI_JS]
    assert server["browser"] == "chrome"


def test_npx_fallback_when_package_missing(tmp_path: Path) -> None:
    """Пакет поставить не удалось — плагин всё равно включён через npx."""
    path = tmp_path / "mcp.json"

    assert ensure_config_file(path, npx_fallback=True) == "created and enabled"

    server = read_json(path)["servers"][SERVER_ID]
    command, args = npx_command()

    assert server["command"] == command
    assert server["args"] == args
    assert args == ["-y", f"{PACKAGE}@{VERSION}"]
    assert server["enabled"] is True


def test_broken_json_is_not_overwritten(tmp_path: Path) -> None:
    """Битый файл — отказ, а не замена: в нём могли быть чужие настройки."""
    path = tmp_path / "mcp.json"
    path.write_text("{ это не json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS)

    assert path.read_text(encoding="utf-8") == "{ это не json"


def test_invalid_servers_shape_raises() -> None:
    with pytest.raises(ValueError):
        ensure_playwright_entry(
            {"servers": ["playwright"]}, command=NODE, args=[CLI_JS]
        )
    with pytest.raises(ValueError):
        ensure_playwright_entry(
            {"servers": {SERVER_ID: "npx -y @playwright/mcp@0.0.83"}},
            command=NODE,
            args=[CLI_JS],
        )


def test_config_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS)

    if os.name == "nt":
        pytest.skip("на Windows права проверяются через icacls, а не mode")

    assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def test_state_reports_enabled_local_server(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"

    empty = server_state(path)
    assert empty["present"] is False and empty["enabled"] is False

    ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS)

    state = server_state(path)
    assert state["configured"] is True
    assert state["enabled"] is True
    assert state["local"] is True
    assert NODE in state["command"]


def test_cli_writes_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "mcp.json"

    code = main(["--config", str(path), "--node", NODE, "--package", CLI_JS])

    assert code == 0
    assert SERVER_ID in capsys.readouterr().out
    assert read_json(path)["servers"][SERVER_ID]["command"] == NODE


def test_cli_rejects_missing_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "mcp.json"

    assert main(["--config", str(path)]) == 2
    assert "required" in capsys.readouterr().err
    assert not path.exists()


def test_cli_reports_broken_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "mcp.json"
    path.write_text("{", encoding="utf-8")

    code = main(["--config", str(path), "--node", NODE, "--package", CLI_JS])

    assert code == 2
    assert "not changed" in capsys.readouterr().err


def test_cli_check_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "mcp.json"
    ensure_config_file(path, node_exe=NODE, cli_js=CLI_JS)

    assert main(["--config", str(path), "--check"]) == 0
    out = capsys.readouterr().out
    assert "enabled=True" in out and "local=True" in out
