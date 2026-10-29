"""Тесты минимального MCP-клиента (без сети и без npx).

Сервер подменяется `tests/fake_mcp_server.py` — он говорит на том же
stdio-JSON-RPC протоколе и умеет воспроизводить сбои. Живые серверы
(`@playwright/mcp`, `seekstone`) проверяются отдельным тестом по флагу
`ZERE_MCP_LIVE=1`.

Запуск: `python3 tests/test_mcp_client.py` или `pytest tests/ -q`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.core.mcp.client import (  # noqa: E402
    PROTOCOL_VERSION,
    McpError,
    McpStdioClient,
    build_batch_command_line,
    is_batch_file,
    resolve_command,
    tool_result_text,
)

FAKE_SERVER = Path(__file__).resolve().parent / "fake_mcp_server.py"


def fake_client(mode: str = "normal", **kwargs: Any) -> McpStdioClient:
    """Клиент к фейковому серверу в нужном режиме."""
    env = {"FAKE_MCP_MODE": mode}
    defaults: dict[str, Any] = {
        "request_timeout": 10.0,
        "startup_timeout": 10.0,
        "name": f"fake-{mode}",
    }
    defaults.update(kwargs)

    return McpStdioClient(
        sys.executable, [str(FAKE_SERVER)], env=env, **defaults
    )


# ── Обычная работа ─────────────────────────────────────────────────


def test_handshake_reports_server_info() -> None:
    with fake_client() as client:
        assert client.server_info.get("name") == "fake-mcp"
        assert client.protocol_version == PROTOCOL_VERSION
        assert "tools" in client.capabilities


def test_list_tools_parses_names_and_schemas() -> None:
    with fake_client() as client:
        tools = client.list_tools()

    names = [tool.name for tool in tools]
    assert names == ["echo", "boom", "secret"]

    echo = next(tool for tool in tools if tool.name == "echo")
    assert echo.description
    assert echo.input_schema.get("required") == ["text"]


def test_call_tool_returns_text() -> None:
    with fake_client() as client:
        result = client.call_tool("echo", {"text": "привет"})

    assert result.is_error is False
    assert result.text == "эхо: привет"


def test_call_tool_reports_tool_error_without_raising() -> None:
    """Ошибка инструмента — нормальный ответ (`isError`), а не исключение.

    Так отвечают живые серверы: у Playwright MCP отсутствие браузера приходит
    именно так.
    """
    with fake_client() as client:
        result = client.call_tool("boom")

    assert result.is_error is True
    assert "инструмент сломался" in result.text


def test_argv_exposes_exact_command_for_consent() -> None:
    """Панель обязана показать точную команду запуска (SEP-1024)."""
    client = fake_client()
    assert client.argv[0] == sys.executable
    assert client.argv[-1].endswith("fake_mcp_server.py")


# ── Сбои ───────────────────────────────────────────────────────────


def test_protocol_error_raises_with_code() -> None:
    with fake_client("protocol_error") as client:
        try:
            client.call_tool("echo", {"text": "x"})
        except McpError as ex:
            assert ex.code == -32601
            assert "Method not found" in str(ex)
        else:
            raise AssertionError("ожидали McpError на ошибку протокола")


def test_unsupported_protocol_version_is_explained() -> None:
    """-32022 должен читаться человеком, а не как «ошибка -32022»."""
    client = fake_client("bad_version")

    try:
        client.start()
    except McpError as ex:
        assert ex.code == -32022
        assert "не поддерживает протокол" in str(ex)
        assert "2026-07-28" in str(ex), "сервер сообщил свои версии — их надо показать"
    else:
        raise AssertionError("ожидали McpError на неподдерживаемую версию")
    finally:
        client.close()


def test_timeout_raises_mcp_error() -> None:
    client = fake_client("hang", request_timeout=1.5)

    with client:
        try:
            client.call_tool("echo", {"text": "x"})
        except McpError as ex:
            assert "таймаут" in str(ex)
        else:
            raise AssertionError("ожидали McpError на таймаут")


def test_server_death_is_reported_as_exit_not_timeout() -> None:
    """Падение сервера — «сервер завершился», а не «таймаут».

    Регрессия: без пробуждения ожидающих по EOF клиент ждал бы полный
    таймаут и вводил в заблуждение.
    """
    client = fake_client("crash_after_init", request_timeout=20.0)
    client.start()

    try:
        client.list_tools()
    except McpError as ex:
        assert "завершился" in str(ex), str(ex)
    else:
        raise AssertionError("ожидали McpError после падения сервера")
    finally:
        client.close()


def test_missing_command_raises_helpful_error() -> None:
    client = McpStdioClient("нет-такой-команды-zere", [], request_timeout=5.0)

    try:
        client.start()
    except McpError as ex:
        assert "не удалось запустить" in str(ex)
    else:
        raise AssertionError("ожидали McpError на отсутствующую команду")


def test_non_json_stdout_is_tolerated() -> None:
    """Сервер, который логирует в stdout, не должен ломать клиент."""
    with fake_client("noise") as client:
        tools = client.list_tools()

    assert [tool.name for tool in tools] == ["echo", "boom", "secret"]


def test_server_request_is_answered() -> None:
    """На запрос сервера клиент отвечает ошибкой, а не молчит.

    Молчание заставило бы сервер ждать ответа до собственного таймаута.
    """
    with fake_client("server_request") as client:
        tools = client.list_tools()

    assert tools, "после запроса сервера работа обязана продолжиться"


# ── Вспомогательное ────────────────────────────────────────────────


def test_tool_result_text_handles_non_text_blocks() -> None:
    assert tool_result_text({"content": [{"type": "text", "text": "привет"}]}) == "привет"
    assert tool_result_text({"content": [{"type": "image"}]}) == "[изображение]"
    assert tool_result_text({"content": [{"type": "text", "text": "a"}, {"type": "image"}]}) == "a\n[изображение]"
    assert tool_result_text({}) == ""


def test_resolve_command_keeps_plain_executable() -> None:
    """Обычная команда не оборачивается в cmd (иначе сломается Linux/macOS)."""
    argv = resolve_command(sys.executable)

    assert argv == [sys.executable]


def test_resolve_command_wraps_cmd_files_on_windows() -> None:
    """`.cmd` запускается строкой для cmd, а не списком argv.

    Регрессия: при списке argv и пути с пробелом
    (`C:\\Program Files\\nodejs\\npx.CMD`) `cmd /c` снимал первую и последнюю
    кавычку и падал на «C:\\Program» — Opera GX (её путь тоже с пробелом)
    не запускалась. Проверено на живой Windows.
    """
    line = build_batch_command_line(
        r"C:\Program Files\nodejs\npx.CMD",
        ["-y", "@playwright/mcp@0.0.83", "--executable-path",
         r"C:\Users\U\Programs\Opera GX\opera.exe"],
    )

    assert line.startswith('"C:\\Program Files\\nodejs\\npx.CMD"'), line
    assert '"C:\\Users\\U\\Programs\\Opera GX\\opera.exe"' in line
    assert "-y @playwright/mcp@0.0.83" in line


def test_batch_file_detection() -> None:
    if os.name != "nt":
        return  # .cmd существует только на Windows

    assert is_batch_file(r"C:\Program Files\nodejs\npx.CMD") is True
    assert is_batch_file(r"C:\Program Files\nodejs\npx.bat") is True
    assert is_batch_file(r"C:\Program Files\nodejs\node.exe") is False


def test_live_servers_are_opt_in() -> None:
    """Живая проверка реальных серверов — только по флагу (нужны сеть и node)."""
    if os.environ.get("ZERE_MCP_LIVE") != "1":
        return

    command = os.environ.get("ZERE_MCP_LIVE_COMMAND")
    args = os.environ.get("ZERE_MCP_LIVE_ARGS", "").split()

    assert command, "ZERE_MCP_LIVE_COMMAND не задан"

    with McpStdioClient(command, args, request_timeout=120.0, startup_timeout=120.0) as client:
        tools = client.list_tools()

    assert tools, "живой сервер не отдал инструментов"


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]

    for test in tests:
        test()
        print(f"OK  {test.__name__}")

    print(f"ПРОЙДЕНО: {len(tests)} тестов MCP-клиента")


if __name__ == "__main__":
    main()
