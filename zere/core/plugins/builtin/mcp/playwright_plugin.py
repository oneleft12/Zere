"""Плагин Playwright MCP: управление браузером.

Сервер — `@playwright/mcp` (проверено на 0.0.83: 25 инструментов,
`protocolVersion` 2025-11-25). Плагин даёт ZERE то, чего у него не было
вовсе, — управление браузером, без облака и без vision-модели: Playwright MCP
работает по accessibility-снимкам страницы.

**Про tool calling.** Его в ZERE нет, поэтому плагин разбирает русские фразы
сам и вызывает нужный инструмент напрямую. Полный набор из 25 инструментов
доступен через лазейку «браузер: <инструмент> {json}» — так не нужно
придумывать синоним под каждый инструмент.

Инструменты, которые требуют ссылку на элемент (`browser_click`,
`browser_type`), работают в два шага: сначала «браузер найди <текст>» или
«браузер снимок» — сервер вернёт ссылки вида `e5`, затем
«браузер клик e5».
"""

from __future__ import annotations

import re
from typing import Optional

from zere.core.mcp.client import McpToolResult
from zere.core.plugins.builtin.mcp.mcp_command import McpCommand
from zere.core.plugins.builtin.mcp.mcp_plugin_base import McpPluginBase

#: Признаки того, что браузер не установлен (текст реального сервера).
_BROWSER_MISSING_MARKERS = (
    "is not found at",
    "playwright install",
    "executable doesn't exist",
)

_URL_RE = re.compile(r"^(https?://|www\.)", re.IGNORECASE)


def _looks_like_url(value: str) -> bool:
    """Похоже ли на адрес, а не на произвольный текст.

    «открой сайт знакомств» не должно превращаться в переход на «знакомств»:
    без домена это не адрес, и такое сообщение лучше отдать дальше по
    конвейеру (ИИ ответит словами).
    """
    candidate = value.strip()

    if not candidate or " " in candidate:
        return False

    if _URL_RE.match(candidate):
        return True

    host = candidate.split("/")[0]

    return "." in host and not host.startswith(".") and not host.endswith(".")


def _normalize_url(value: str) -> str:
    candidate = value.strip()

    if _URL_RE.match(candidate):
        return candidate

    return "https://" + candidate


class PlaywrightMcpPlugin(McpPluginBase):
    """Браузер через Playwright MCP."""

    server_id = "playwright"
    triggers = ("браузер", "browser")

    plugin_id = "playwright-mcp"
    plugin_name = "Playwright MCP (браузер)"
    plugin_description = (
        "Управление браузером через MCP-сервер Playwright: переход по адресу, "
        "снимок страницы, поиск на странице, клик и ввод, скриншот."
    )
    plugin_version = "1.0.0"

    #: Снимок страницы — самая «тяжёлая» выдача, режем раньше остальных.
    max_response_chars = 2500

    @property
    def supported_commands(self) -> list[str]:
        return [
            "браузер открой <адрес>",
            "перейди на <адрес>",
            "браузер назад",
            "браузер снимок (что на странице)",
            "браузер найди <текст>",
            "браузер клик <ссылка>",
            "браузер введи <ссылка>: <текст>",
            "браузер скриншот",
            "браузер закрой",
            "браузер инструменты",
            "браузер: <инструмент> {json}",
        ]

    # ── Разбор фраз ─────────────────────────────────────────────────

    def _parse_friendly(self, message: str) -> Optional[McpCommand]:
        text = (
            self._router.strip_trigger(message)
            if self._router.starts_with_trigger(message)
            else message.strip()
        )

        if not text:
            return None

        lower = text.lower()

        # Переход по адресу.
        for prefix in ("открой сайт ", "открой страницу ", "открой ссылку ", "перейди на ", "зайди на "):
            if lower.startswith(prefix):
                candidate = text[len(prefix):].strip()
                if _looks_like_url(candidate):
                    return McpCommand(
                        tool="browser_navigate",
                        arguments={"url": _normalize_url(candidate)},
                    )
                return None

        if lower.startswith("открой ") and _looks_like_url(text[len("открой "):]):
            return McpCommand(
                tool="browser_navigate",
                arguments={"url": _normalize_url(text[len("открой "):])},
            )

        # Навигация и состояние страницы.
        if lower in ("назад", "вернись назад", "страница назад"):
            return McpCommand(tool="browser_navigate_back")

        if lower in ("снимок", "снимок страницы", "что на странице", "страница"):
            return McpCommand(tool="browser_snapshot")

        if lower in ("скриншот", "снимок экрана"):
            return McpCommand(tool="browser_take_screenshot")

        if lower in ("закрой", "закрыть", "закрой браузер"):
            return McpCommand(tool="browser_close")

        # Поиск на странице.
        for prefix in ("найди на странице ", "найди ", "поиск на странице "):
            if lower.startswith(prefix):
                query = text[len(prefix):].strip()
                if query:
                    return McpCommand(tool="browser_find", arguments={"text": query})

        # Клик по ссылке из снимка.
        for prefix in ("клик по ", "клик ", "нажми на ", "нажми "):
            if lower.startswith(prefix):
                target = text[len(prefix):].strip()
                if target:
                    return McpCommand(
                        tool="browser_click",
                        arguments={"target": target, "element": target},
                    )

        # Ввод текста: «введи <ссылка>: <текст>».
        for prefix in ("введи в ", "введи ", "напиши в "):
            if lower.startswith(prefix):
                rest = text[len(prefix):]
                target, separator, value = rest.partition(":")
                if separator and target.strip() and value.strip():
                    return McpCommand(
                        tool="browser_type",
                        arguments={
                            "target": target.strip(),
                            "text": value.strip(),
                            "element": target.strip(),
                        },
                    )
                return None

        # Выполнить JavaScript.
        for prefix in ("выполни ", "выполни в браузере ", "js "):
            if lower.startswith(prefix):
                code = text[len(prefix):].strip()
                if code:
                    return McpCommand(
                        tool="browser_evaluate", arguments={"function": code}
                    )

        return None

    # ── Ответ ───────────────────────────────────────────────────────

    def _format(self, result: McpToolResult, command: McpCommand) -> str:
        text = result.text or "(сервер вернул пустой ответ)"

        if result.is_error and any(
            marker in text for marker in _BROWSER_MISSING_MARKERS
        ):
            return (
                "Браузер для Playwright MCP не установлен. Выполните в консоли:\n"
                "    npx playwright install chrome\n"
                "После установки повторите команду."
            )

        return super()._format(result, command)


__all__ = ["PlaywrightMcpPlugin"]
