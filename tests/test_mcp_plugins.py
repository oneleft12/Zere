"""Тесты MCP-плагинов: браузер (Playwright) и заметки (Obsidian).

Живые серверы не нужны: `can_handle` обязан быть дешёвым и не запускать
процесс, а `handle` проверяется на фейковом сервере через подмену фабрики
клиента (как `tests/fake_http.py` подменяет HTTP в тестах ИИ).

Запуск: `python3 tests/test_mcp_plugins.py` или `pytest tests/ -q`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.core.mcp.client import McpStdioClient  # noqa: E402
from zere.core.mcp.config import McpServerSettings  # noqa: E402
from zere.core.plugins.builtin.mcp import (  # noqa: E402
    ObsidianMcpPlugin,
    PlaywrightMcpPlugin,
)
from zere.core.plugins.interfaces.plugin import PluginType  # noqa: E402

FAKE_SERVER = Path(__file__).resolve().parent / "fake_mcp_server.py"


def write_config(tmp: Path, **servers: dict[str, Any]) -> Path:
    """Пишет config/mcp.json во временный каталог."""
    path = tmp / "mcp.json"
    path.write_text(
        json.dumps({"servers": servers}, ensure_ascii=False), encoding="utf-8"
    )

    return path


def fake_factory(settings: McpServerSettings) -> McpStdioClient:
    """Фабрика клиента к фейковому серверу (реальный npx не запускаем)."""
    return McpStdioClient(
        sys.executable,
        [str(FAKE_SERVER)],
        env={"FAKE_MCP_MODE": "normal"},
        name=settings.server_id,
        request_timeout=10.0,
        startup_timeout=10.0,
    )


def enabled_config(tmp: Path, server_id: str) -> Path:
    return write_config(
        tmp,
        **{
            server_id: {
                "enabled": True,
                "command": sys.executable,
                "args": [str(FAKE_SERVER)],
            }
        },
    )


# ── Выключенный плагин инертен ─────────────────────────────────────


def test_plugins_are_inert_without_config() -> None:
    """Без config/mcp.json плагин не отвечает ни на что и ничего не запускает."""
    missing = Path("/нет/такого/mcp.json")

    for plugin in (PlaywrightMcpPlugin(config_path=missing), ObsidianMcpPlugin(config_path=missing)):
        plugin.initialize()

        assert plugin.enabled is False
        assert plugin.can_handle("браузер открой https://ya.ru") is False
        assert plugin.can_handle("заметки найди покупки") is False
        assert plugin.handle("заметки найди покупки") is None
        assert plugin.running is False, "сервер не должен запускаться сам"


def test_disabled_server_does_not_handle() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        path = write_config(
            Path(td),
            playwright={"enabled": False, "command": "npx", "args": ["@playwright/mcp"]},
        )
        plugin = PlaywrightMcpPlugin(config_path=path)
        plugin.initialize()

        assert plugin.enabled is False
        assert plugin.can_handle("браузер открой https://ya.ru") is False


# ── Разбор фраз (без сервера) ──────────────────────────────────────


def playwright_plugin(tmp: Path) -> PlaywrightMcpPlugin:
    plugin = PlaywrightMcpPlugin(config_path=enabled_config(tmp, "playwright"))
    plugin.initialize()

    return plugin


def obsidian_plugin(tmp: Path) -> ObsidianMcpPlugin:
    plugin = ObsidianMcpPlugin(config_path=enabled_config(tmp, "obsidian"))
    plugin.initialize()

    return plugin


def test_playwright_recognizes_browser_phrases() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = playwright_plugin(Path(td))

        for phrase in (
            "браузер открой https://example.com",
            "перейди на ya.ru",
            "браузер назад",
            "браузер снимок",
            "что на странице",
            "браузер найди Войти",
            "браузер клик e5",
            "браузер введи e3: привет",
            "браузер скриншот",
            "браузер закрой",
            "браузер инструменты",
        ):
            assert plugin.can_handle(phrase) is True, phrase


def test_playwright_ignores_non_browser_messages() -> None:
    """Плагин не должен перехватывать чужие команды и выдумывать адреса."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = playwright_plugin(Path(td))

        for phrase in (
            "включи музыку",
            "закрой процесс chrome.exe",
            "открой сайт знакомств",
            "сколько будет два плюс два",
        ):
            assert plugin.can_handle(phrase) is False, phrase


def test_navigation_adds_https_scheme() -> None:
    """«перейди на ya.ru» должно стать https://ya.ru, а не голым хостом."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = playwright_plugin(Path(td))
        command = plugin._parse("перейди на ya.ru")

    assert command is not None
    assert command.tool == "browser_navigate"
    assert command.arguments["url"] == "https://ya.ru"


def test_obsidian_recognizes_note_phrases() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = obsidian_plugin(Path(td))

        for phrase in (
            "заметки найди покупки",
            "найди в заметках покупки",
            "заметки список",
            "заметки теги",
            "заметки прочитай ZERE.md",
            "заметки создай Идеи.md",
            "заметки допиши Покупки.md: - сыр",
            "заметки инструменты",
        ):
            assert plugin.can_handle(phrase) is True, phrase


def test_obsidian_requires_body_for_append() -> None:
    """«допиши» без текста — не команда: нечего добавлять."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = obsidian_plugin(Path(td))

        assert plugin.can_handle("заметки допиши Покупки.md") is False
        assert plugin.can_handle("включи музыку") is False


# ── Лазейка «<триггер>: <инструмент> {json}» ───────────────────────


def test_generic_form_calls_any_tool() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = playwright_plugin(Path(td))
        command = plugin._parse('браузер: browser_navigate {"url": "https://ya.ru"}')

    assert command is not None
    assert command.source == "generic"
    assert command.tool == "browser_navigate"
    assert command.arguments == {"url": "https://ya.ru"}


def test_generic_form_reports_bad_json() -> None:
    """Битый JSON — понятная ошибка, а не молчаливый пропуск команды."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = playwright_plugin(Path(td))

        assert plugin.can_handle("браузер: browser_navigate {url: ya.ru}") is True
        answer = plugin.handle("браузер: browser_navigate {url: ya.ru}")

    assert answer is not None
    assert "JSON" in answer


# ── Работа через фейковый сервер ───────────────────────────────────


def test_playwright_calls_tool_and_formats_answer() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = PlaywrightMcpPlugin(
            config_path=enabled_config(Path(td), "playwright"), client_factory=fake_factory
        )
        plugin.initialize()

        answer = plugin.handle('браузер: echo {"text": "привет"}')

    assert answer == "эхо: привет"


def test_plugin_reports_tool_error_in_russian() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = PlaywrightMcpPlugin(
            config_path=enabled_config(Path(td), "playwright"), client_factory=fake_factory
        )
        plugin.initialize()

        answer = plugin.handle("браузер: boom {}")

    assert answer is not None
    assert "Ошибка инструмента" in answer
    assert "инструмент сломался" in answer


def test_browser_not_installed_gives_actionable_hint() -> None:
    """Реальный текст Playwright MCP про отсутствующий браузер → подсказка.

    Проверено на живом сервере: без браузера он отвечает
    «Chromium distribution 'chrome' is not found … Run "npx playwright install chrome"».
    """
    import tempfile

    from zere.core.mcp.client import McpToolResult

    with tempfile.TemporaryDirectory() as td:
        plugin = playwright_plugin(Path(td))

    result = McpToolResult(
        text="### Error\nError: Chromium distribution 'chrome' is not found at "
        "/opt/google/chrome/chrome\nRun \"npx playwright install chrome\"",
        is_error=True,
    )
    answer = plugin._format(result, plugin._parse("браузер снимок"))

    assert "не установлен" in answer
    assert "npx playwright install chrome" in answer


def test_obsidian_humanizes_json_answers() -> None:
    """seekstone отвечает JSON — пользователю и озвучке нужен текст."""
    import tempfile

    from zere.core.mcp.client import McpToolResult

    with tempfile.TemporaryDirectory() as td:
        plugin = obsidian_plugin(Path(td))

    search = McpToolResult(
        text='[{"path":"Покупки.md","score":3.1,"excerpt":"# Список покупок\\n\\n- молоко"}]'
    )
    answer = plugin._format(search, plugin._parse("заметки найди покупки"))
    assert "Покупки.md" in answer
    assert "молоко" in answer
    assert answer.strip().startswith("—"), answer

    note = McpToolResult(text='{"path":"ZERE.md","content":"# Проект ZERE\\n\\nТекст."}')
    answer = plugin._format(note, plugin._parse("заметки прочитай ZERE.md"))
    assert answer == "# Проект ZERE\n\nТекст."


def test_obsidian_missing_vault_gives_hint() -> None:
    import tempfile

    from zere.core.mcp.client import McpToolResult

    with tempfile.TemporaryDirectory() as td:
        plugin = obsidian_plugin(Path(td))

    result = McpToolResult(text="Error: SEEKSTONE_VAULT is not set", is_error=True)
    answer = plugin._format(result, plugin._parse("заметки список"))

    assert "хранилище" in answer.lower()
    assert "SEEKSTONE_VAULT" in answer


# ── Настройки ──────────────────────────────────────────────────────


def test_allowlist_blocks_tool() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        path = write_config(
            Path(td),
            obsidian={
                "enabled": True,
                "command": sys.executable,
                "args": [str(FAKE_SERVER)],
                "allowedTools": ["search"],
            },
        )
        plugin = ObsidianMcpPlugin(config_path=path, client_factory=fake_factory)
        plugin.initialize()

        answer = plugin.handle("заметки: echo {}")

    assert answer is not None
    assert "запрещён настройками" in answer


def test_command_description_is_shown_for_consent() -> None:
    """Панель показывает точную команду запуска (требование SEP-1024)."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = playwright_plugin(Path(td))
        description = plugin.settings.describe_command()
        status = plugin.status()

    assert "fake_mcp_server.py" in description
    assert status["enabled"] is True
    assert status["serverId"] == "playwright"
    assert status["running"] is False, "статус не должен поднимать сервер"


def test_plugin_metadata_matches_interface() -> None:
    plugin = PlaywrightMcpPlugin()

    assert plugin.id == "playwright-mcp"
    assert plugin.name
    assert plugin.description
    assert plugin.version
    assert plugin.author
    assert plugin.type is PluginType.CommandHandler
    assert plugin.supported_commands, "панель показывает примеры команд"


def test_tools_overview_lists_server_tools() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        plugin = PlaywrightMcpPlugin(
            config_path=enabled_config(Path(td), "playwright"), client_factory=fake_factory
        )
        plugin.initialize()

        answer = plugin.handle("браузер инструменты")

    assert answer is not None
    assert "echo" in answer and "boom" in answer


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]

    for test in tests:
        test()
        print(f"OK  {test.__name__}")

    print(f"ПРОЙДЕНО: {len(tests)} тестов MCP-плагинов")


if __name__ == "__main__":
    main()
