"""Плагин Playwright MCP: управление браузером.

Сервер — `@playwright/mcp` (проверено на 0.0.83: 25 инструментов,
`protocolVersion` 2025-11-25). Плагин даёт ZERE то, чего у него не было
вовсе, — управление браузером, без облака и без vision-модели: Playwright MCP
работает по accessibility-снимкам страницы.

**Выбор браузера.** Рабочий браузер задаётся ключом `browser` в
`config/mcp.json` и меняется из чата командой «браузер выбери edge».
Поддерживаются Edge, Chrome, Opera GX и Chromium:

- Edge и Chrome подключаются каналом Playwright (`--browser msedge`/`chrome`);
- **Opera GX — только через `--executable-path`**: своего канала у Playwright
  для него нет, но как Chromium он управляется штатно (проверено вживую);
- Chromium — собственный браузер Playwright (`npx playwright install chromium`).

По умолчанию — Edge: он есть на любой Windows, и скачивать ничего не нужно.

**Про tool calling.** Его в ZERE нет, поэтому плагин разбирает русские фразы
сам и вызывает нужный инструмент напрямую. Полный набор из 25 инструментов
доступен через лазейку «браузер: <инструмент> {json}».

Инструменты, которые требуют ссылку на элемент (`browser_click`,
`browser_type`), работают в два шага: сначала «браузер найди <текст>» или
«браузер снимок» — сервер вернёт ссылки вида `e5`, затем
«браузер клик e5».
"""

from __future__ import annotations

import re
import time
from typing import Optional

from zere.core.mcp.client import McpError, McpStdioClient, McpToolResult
from zere.core.mcp.config import set_server_option
from zere.core.plugins.builtin.mcp.browser_profiles import (
    BROWSER_PROFILES,
    DEFAULT_BROWSER_ID,
    BrowserNotInstalled,
    BrowserProfile,
    browser_args,
    describe_available,
    find_profile,
    is_available,
    profile_by_id,
)
from zere.core.plugins.builtin.mcp.mcp_command import McpCommand
from zere.core.plugins.builtin.mcp.mcp_plugin_base import McpPluginBase

#: Признаки того, что браузер не установлен (текст реального сервера).
_BROWSER_MISSING_MARKERS = (
    "is not found at",
    "playwright install",
    "executable doesn't exist",
)

_URL_RE = re.compile(r"^(https?://|www\.)", re.IGNORECASE)

#: Как пользователь просит сменить браузер.
_SWITCH_PREFIXES = (
    "выбери ",
    "выбрать ",
    "переключись на ",
    "переключи на ",
    "переключи ",
    "используй ",
    "смени на ",
    "смени ",
    "работай в ",
)

#: Обрыв перехода на старте браузера (Opera GX открывает свои вкладки).
_TRANSIENT_NAVIGATION_ERRORS = ("ERR_ABORTED",)

#: Пауза перед повтором: браузеру нужно досоздать свои стартовые вкладки.
_NAVIGATION_RETRY_DELAY_SECONDS = 1.0


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
        "снимок страницы, поиск на странице, клик и ввод, скриншот. "
        "Браузер выбирается (Edge, Chrome, Opera GX, Chromium) и меняется из чата."
    )
    plugin_version = "1.1.0"

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
            "браузер какой (текущий браузер)",
            "браузер список (доступные браузеры)",
            "браузер выбери edge | chrome | opera gx | chromium",
            "браузер инструменты",
            "браузер: <инструмент> {json}",
        ]

    # ── Выбор браузера ──────────────────────────────────────────────

    def browser_profile(self) -> BrowserProfile:
        """Профиль браузера из настроек (по умолчанию — Edge)."""
        name = str(self._settings.options.get("browser") or "").strip()

        if name:
            found = find_profile(name)
            if found is not None:
                return found

        fallback = profile_by_id(DEFAULT_BROWSER_ID)

        return fallback if fallback is not None else BROWSER_PROFILES[0]

    def _browser_path(self) -> Optional[str]:
        """Явный путь к исполняемому файлу из настроек (`browserPath`)."""
        value = str(self._settings.options.get("browserPath") or "").strip()

        return value or None

    def _effective_args(self) -> list[str]:
        """Аргументы сервера + флаги выбранного браузера."""
        args = list(self._settings.args)
        profile = self.browser_profile()

        try:
            args.extend(browser_args(profile, self._browser_path()))
        except BrowserNotInstalled as ex:
            # Текст подсказки уходит в общий путь ошибки запуска сервера.
            raise McpError(str(ex)) from ex

        return args

    def _describe_current_browser(self) -> str:
        profile = self.browser_profile()
        explicit = self._browser_path()
        name = str(self._settings.options.get("browser") or "").strip()

        lines = [f"Текущий браузер: {profile.label} ({profile.id})."]

        if explicit:
            lines.append(f"Задан явный путь (browserPath): {explicit}")

        if name and find_profile(name) is None:
            lines.append(
                f"В настройках неизвестное имя «{name}» — используется {profile.label}."
            )

        if not is_available(profile) and profile.install_hint:
            lines.append(profile.install_hint)

        lines.append(f"Сменить: «браузер выбери {profile.id}» или «браузер список».")

        return "\n".join(lines)

    def _describe_browsers(self) -> str:
        current = self.browser_profile()
        lines = ["Доступные браузеры для Playwright MCP:"]

        # Только ASCII-маркеры: вывод уходит в консоль Windows, где кодовая
        # страница (cp866/cp1251) не знает «✓» и «←» — ZERE заменил бы их
        # на «?», и список выглядел бы сломанным.
        for profile, available in describe_available():
            mark = "[+]" if available else "[-]"
            current_mark = " (текущий)" if profile.id == current.id else ""
            lines.append(f"{mark} {profile.id} — {profile.label}{current_mark}")

        lines.append("Сменить: «браузер выбери opera gx».")
        lines.append("Метка [-] означает, что браузер не найден по стандартным путям.")

        return "\n".join(lines)

    def _switch_browser(self, name: str) -> str:
        profile = find_profile(name)

        if profile is None:
            available = ", ".join(p.id for p in BROWSER_PROFILES)

            return f"Не знаю браузер «{name}». Доступны: {available}."

        # Opera GX и прочие «только по пути» обязаны существовать на диске,
        # иначе команда сменит настройку на заведомо нерабочую.
        if profile.channel is None:
            try:
                browser_args(profile)
            except BrowserNotInstalled as ex:
                return str(ex)

        saved = set_server_option(
            self.server_id, "browser", profile.id, self._config_path
        )
        # Явный путь перебивает профиль — сбрасываем его, раз браузер выбран.
        set_server_option(self.server_id, "browserPath", "", self._config_path)

        # Настройки перечитываем и сервер гасим: следующий вызов поднимет его
        # уже с новыми аргументами.
        self.reload_settings()

        note = "" if saved else " (config/mcp.json недоступен — выбор до перезапуска)"

        return f"Браузер переключён на {profile.label}.{note}"

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

        # Выбор браузера.
        if lower in ("какой", "какой браузер", "текущий браузер", "текущий"):
            return McpCommand(tool="", source="current-browser")

        if lower in ("список", "браузеры", "список браузеров", "какие браузеры"):
            return McpCommand(tool="", source="browsers")

        for prefix in _SWITCH_PREFIXES:
            if lower.startswith(prefix):
                name = text[len(prefix):].strip()
                if name:
                    return McpCommand(
                        tool="", arguments={"browser": name}, source="switch-browser"
                    )
                return None

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

    def _handle_local(self, command: McpCommand) -> Optional[str]:
        if command.source == "current-browser":
            return self._describe_current_browser()

        if command.source == "browsers":
            return self._describe_browsers()

        if command.source == "switch-browser":
            return self._switch_browser(str(command.arguments.get("browser") or ""))

        return super()._handle_local(command)

    def _call_tool(self, client: McpStdioClient, command: McpCommand) -> McpToolResult:
        """Переход повторяем один раз при обрыве.

        Opera GX на старте открывает свои вкладки (GX Corner, приветствие) и
        отменяет наш переход: `net::ERR_ABORTED`. Проверено на живой Windows —
        без повтора первый переход падал примерно в половине запусков, с
        повтором проходит. Другие ошибки не повторяем: у них свои причины.
        """
        result = super()._call_tool(client, command)

        if (
            command.tool == "browser_navigate"
            and result.is_error
            and any(marker in result.text for marker in _TRANSIENT_NAVIGATION_ERRORS)
        ):
            time.sleep(_NAVIGATION_RETRY_DELAY_SECONDS)
            result = super()._call_tool(client, command)

        return result

    # ── Ответ ───────────────────────────────────────────────────────

    def _format(self, result: McpToolResult, command: McpCommand) -> str:
        text = result.text or "(сервер вернул пустой ответ)"

        if result.is_error and any(
            marker in text for marker in _BROWSER_MISSING_MARKERS
        ):
            profile = self.browser_profile()

            return (
                f"Браузер «{profile.label}» для Playwright MCP не найден. "
                f"{profile.install_hint or 'Установите браузер.'}\n"
                "Выбрать другой: «браузер список», затем «браузер выбери edge»."
            )

        return super()._format(result, command)


__all__ = ["PlaywrightMcpPlugin"]
