"""Тесты «YouTube и музыка»: разбор фраз, сервис и обработчик.

Живой браузер и сеть не нужны: Playwright-драйвер и открытие ссылки
подменяются фейками, как HTTP в `tests/fake_http.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.core.handlers.media_handler import MediaHandler  # noqa: E402
from zere.core.mcp.client import McpError, McpToolResult  # noqa: E402
from zere.tools.media.youtube_command import (  # noqa: E402
    DEFAULT_QUERY,
    NEXT,
    OPEN,
    PAUSE,
    PLAY,
    PREVIOUS,
    RESUME,
    STATUS,
    YouTubeCommand,
)
from zere.tools.media.youtube_command_router import YouTubeCommandRouter  # noqa: E402
from zere.tools.media.youtube_service import (  # noqa: E402
    YOUTUBE_URL,
    YouTubeService,
    search_url,
)

# ── Фейки ────────────────────────────────────────────────────────────


class FakeDriver:
    """Драйвер браузера: отдаёт заранее заданные ответы и копит код."""

    def __init__(
        self,
        payloads: Optional[list[dict[str, Any]]] = None,
        *,
        enabled: bool = True,
        error: Optional[Exception] = None,
    ) -> None:
        self._payloads = list(payloads or [])
        self._enabled = enabled
        self._error = error
        self.codes: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def run_code(self, code: str) -> McpToolResult:
        self.codes.append(code)

        if self._error is not None:
            raise self._error

        payload = self._payloads.pop(0) if self._payloads else {"ok": True}
        text = (
            "### Result\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n### Ran Playwright code\n```js\nawait (page) => {};\n```"
        )

        return McpToolResult(text=text)


class FakeOpener:
    """Открытие ссылки: запоминает адреса, отвечает `result`."""

    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.urls: list[str] = []

    def __call__(self, url: str) -> bool:
        self.urls.append(url)

        return self.result


# ── Роутер ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message, expected",
    [
        ("включи музыку", YouTubeCommand(PLAY)),
        ("Включи музыку!", YouTubeCommand(PLAY)),
        ("включи музыку, пожалуйста", YouTubeCommand(PLAY)),
        ("включи ютуб музыку", YouTubeCommand(PLAY)),
        ("ютуб музыка", YouTubeCommand(PLAY)),
        ("включи джаз на ютубе", YouTubeCommand(PLAY, "джаз")),
        ("включи на ютубе лофай", YouTubeCommand(PLAY, "лофай")),
        ("поставь рок на youtube", YouTubeCommand(PLAY, "рок")),
        ("включи музыку классика", YouTubeCommand(PLAY, "классика")),
        ("открой ютуб", YouTubeCommand(OPEN)),
        ("ютуб", YouTubeCommand(OPEN)),
        ("включи youtube", YouTubeCommand(OPEN)),
        ("пауза", YouTubeCommand(PAUSE)),
        ("выключи музыку", YouTubeCommand(PAUSE)),
        ("продолжи", YouTubeCommand(RESUME)),
        ("сними с паузы", YouTubeCommand(RESUME)),
        ("следующий трек", YouTubeCommand(NEXT)),
        ("предыдущая песня", YouTubeCommand(PREVIOUS)),
        ("что играет", YouTubeCommand(STATUS)),
        ("какой трек играет", YouTubeCommand(STATUS)),
    ],
)
def test_router_parses_commands(message: str, expected: YouTubeCommand) -> None:
    assert YouTubeCommandRouter().parse(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "",
        "привет",
        "включи звук",
        "сделай громче",
        "включи музыку громче",
        "почему не играет музыка",
        "открой папку музыка",
        "закрой процесс chrome",
        "расскажи про ютуб",
        "что такое музыка",
    ],
)
def test_router_ignores_other_phrases(message: str) -> None:
    assert YouTubeCommandRouter().parse(message) is None


def test_default_query_is_used_for_empty_play() -> None:
    assert DEFAULT_QUERY == "музыка"


# ── Сервис: открытие сайта ──────────────────────────────────────────


def test_open_uses_driver_when_available() -> None:
    driver = FakeDriver([{"ok": True, "title": "YouTube"}])
    opener = FakeOpener()
    service = YouTubeService(driver=driver, open_url=opener)

    assert service.open_youtube() == "Открыл YouTube."
    assert driver.codes and "youtube.com" in driver.codes[0]
    assert opener.urls == []


def test_open_falls_back_to_default_browser() -> None:
    driver = FakeDriver([{"ok": False, "error": "браузер не запустился"}])
    opener = FakeOpener()
    service = YouTubeService(driver=driver, open_url=opener)

    assert "по умолчанию" in service.open_youtube()
    assert opener.urls == [YOUTUBE_URL]


def test_open_without_driver_uses_default_browser() -> None:
    opener = FakeOpener()
    service = YouTubeService(open_url=opener)

    assert "по умолчанию" in service.open_youtube()
    assert opener.urls == [YOUTUBE_URL]


def test_open_reports_missing_browser() -> None:
    service = YouTubeService(open_url=FakeOpener(result=False))

    assert "не найден" in service.open_youtube().lower()


# ── Сервис: включение музыки ────────────────────────────────────────


def test_play_music_starts_track_and_returns_title() -> None:
    driver = FakeDriver(
        [{"ok": True, "stage": "playing", "track": "Lofi Hip Hop Radio"}]
    )
    opener = FakeOpener()
    service = YouTubeService(driver=driver, open_url=opener)

    answer = service.play_music("лофай")

    assert "Включаю на YouTube" in answer
    assert "Lofi Hip Hop Radio" in answer
    assert "лофай" in driver.codes[0]
    assert opener.urls == []


def test_play_music_without_query_uses_default() -> None:
    driver = FakeDriver([{"ok": True, "stage": "playing", "track": "Музыка"}])
    service = YouTubeService(driver=driver)

    service.play_music("")

    assert DEFAULT_QUERY in driver.codes[0]


def test_play_music_reports_no_results() -> None:
    driver = FakeDriver([{"ok": False, "stage": "no-results"}])
    service = YouTubeService(driver=driver, open_url=FakeOpener())

    assert "ничего не нашлось" in service.play_music("абракадабра")


def test_play_music_reports_not_playing() -> None:
    driver = FakeDriver([{"ok": False, "stage": "not-playing"}])
    service = YouTubeService(driver=driver, open_url=FakeOpener())

    assert "нажмите Play" in service.play_music("рок")


def test_play_music_falls_back_when_plugin_disabled() -> None:
    driver = FakeDriver(enabled=False)
    opener = FakeOpener()
    service = YouTubeService(driver=driver, open_url=opener)

    answer = service.play_music("джаз")

    assert "Автовоспроизведение недоступно" in answer
    assert "Playwright MCP" in answer
    assert opener.urls == [search_url("джаз")]
    assert driver.codes == []


def test_play_music_falls_back_on_driver_error() -> None:
    driver = FakeDriver(error=McpError("npx не найден"))
    opener = FakeOpener()
    service = YouTubeService(driver=driver, open_url=opener)

    answer = service.play_music("рок")

    assert "npx не найден" in answer
    assert opener.urls == [search_url("рок")]


def test_play_music_does_not_lie_when_browser_is_missing() -> None:
    service = YouTubeService(
        driver=FakeDriver(enabled=False), open_url=FakeOpener(result=False)
    )

    assert "Не удалось включить музыку" in service.play_music("рок")


# ── Сервис: управление воспроизведением ────────────────────────────


def test_control_requires_driver() -> None:
    service = YouTubeService(driver=FakeDriver(enabled=False))

    assert "Playwright MCP" in service.control(PAUSE)


def test_control_pause_and_status() -> None:
    driver = FakeDriver(
        [
            {"ok": True, "stage": "video", "paused": True, "track": "Трек"},
            {"ok": True, "stage": "video", "paused": False, "track": "Трек"},
        ]
    )
    service = YouTubeService(driver=driver)

    assert service.control(PAUSE) == "Пауза."
    assert service.control(STATUS) == "Сейчас играет: Трек."
    assert '"pause"' in driver.codes[0]


def test_control_next_returns_new_track() -> None:
    driver = FakeDriver(
        [{"ok": True, "stage": "video", "paused": False, "track": "Новый трек"}]
    )
    service = YouTubeService(driver=driver)

    assert service.control(NEXT) == "Следующий трек: Новый трек."


def test_control_no_video_is_explained() -> None:
    driver = FakeDriver([{"ok": False, "stage": "no-video"}])
    service = YouTubeService(driver=driver)

    assert "нет видео" in service.control(PAUSE)


def test_control_errors_do_not_raise() -> None:
    service = YouTubeService(driver=FakeDriver(error=McpError("сервер упал")))

    assert "сервер упал" in service.control(RESUME)


# ── Обработчик ───────────────────────────────────────────────────────


def test_handler_claims_youtube_phrases() -> None:
    handler = MediaHandler(YouTubeService(open_url=FakeOpener()))

    assert handler.can_handle("открой ютуб")
    assert handler.can_handle("включи музыку")
    assert not handler.can_handle("открой блокнот")


def test_handler_dispatches_commands() -> None:
    driver = FakeDriver(
        [
            {"ok": True, "stage": "playing", "track": "Трек"},
            {"ok": True, "stage": "video", "paused": True, "track": "Трек"},
        ]
    )
    handler = MediaHandler(YouTubeService(driver=driver, open_url=FakeOpener()))

    assert "Включаю на YouTube" in handler.handle("включи музыку")
    assert handler.handle("пауза") == "Пауза."


def test_handler_returns_none_for_foreign_phrase() -> None:
    handler = MediaHandler(YouTubeService(open_url=FakeOpener()))

    assert handler.handle("открой блокнот") is None


# ── Плагин браузера: публичный run_code ─────────────────────────────


def test_playwright_run_code_requires_enabled_plugin() -> None:
    from zere.core.plugins.builtin.mcp.playwright_plugin import PlaywrightMcpPlugin

    plugin = PlaywrightMcpPlugin(config_path=Path("/нет/такого/mcp.json"))

    with pytest.raises(McpError):
        plugin.run_code("async (page) => page.title()")


def test_playwright_run_code_calls_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    from zere.core.mcp.config import McpServerSettings
    from zere.core.plugins.builtin.mcp.playwright_plugin import PlaywrightMcpPlugin

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def call_tool(self, name: str, arguments: dict[str, Any]) -> McpToolResult:
            self.calls.append((name, arguments))
            return McpToolResult(text="### Result\n{\"ok\": true}")

    client = FakeClient()
    plugin = PlaywrightMcpPlugin(config_path=Path("/нет/такого/mcp.json"))
    plugin._settings = McpServerSettings(
        server_id="playwright", enabled=True, command="npx"
    )
    monkeypatch.setattr(plugin, "_ensure_client", lambda: client)

    result = plugin.run_code("async (page) => page.title()")

    assert result.text.startswith("### Result")
    assert client.calls == [
        ("browser_run_code_unsafe", {"code": "async (page) => page.title()"})
    ]


def test_playwright_run_code_respects_allowed_tools() -> None:
    from zere.core.mcp.config import McpServerSettings
    from zere.core.plugins.builtin.mcp.playwright_plugin import PlaywrightMcpPlugin

    plugin = PlaywrightMcpPlugin(config_path=Path("/нет/такого/mcp.json"))
    plugin._settings = McpServerSettings(
        server_id="playwright",
        enabled=True,
        command="npx",
        allowed_tools=["browser_navigate"],
    )

    with pytest.raises(McpError):
        plugin.run_code("async (page) => page.title()")


# ── Сборка сервисов: драйвер находится среди плагинов ───────────────


def test_services_take_playwright_plugin_as_driver() -> None:
    from zere.core import services as services_module
    from zere.core.plugins.builtin.mcp.playwright_plugin import PlaywrightMcpPlugin
    from zere.core.plugins.plugin_manager import PluginManager
    from zere.core.services import ServiceContainer

    class StubManager:
        def __init__(self, handlers: list[Any]) -> None:
            self.command_handlers = handlers

    plugin = PlaywrightMcpPlugin(config_path=Path("/нет/такого/mcp.json"))
    container = ServiceContainer()
    container.add_singleton_factory(
        lambda: StubManager([object(), plugin]), PluginManager
    )

    service = services_module._create_youtube_service(container)

    assert service._driver is plugin


def test_services_work_without_playwright_plugin() -> None:
    from zere.core import services as services_module
    from zere.core.plugins.plugin_manager import PluginManager
    from zere.core.services import ServiceContainer

    class StubManager:
        command_handlers: list[Any] = []

    container = ServiceContainer()
    container.add_singleton_factory(lambda: StubManager(), PluginManager)

    service = services_module._create_youtube_service(container)

    assert service._driver is None
