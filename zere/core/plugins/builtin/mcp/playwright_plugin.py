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
from typing import Any, Optional

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

# ── Оформление ответов ─────────────────────────────────────────────
# Playwright MCP отвечает текстом «для модели»: служебный JS-код, список
# открытых вкладок, английские заголовки вида `### Page`. Пользователю это не
# нужно, а озвучка читала бы «решётка решётка Ran Playwright code». Поэтому
# ответы приводятся к человеческому виду, а ошибки — к русским подсказкам.
#
# Разбор применяется только к инструментам `browser_*`: лазейка
# «браузер: <инструмент> {json}» отдаёт ответ сервера как есть.

_CODE_BLOCK_RE = re.compile(r"### Ran Playwright code\s*```[a-zA-Z]*\s*.*?```\s*", re.DOTALL)
_OPEN_TABS_RE = re.compile(r"### Open tabs\s*(?:-\s.*\n?)*")
_PAGE_SECTION_RE = re.compile(r"### Page\s*(?:-\s.*\n?)*")
_SNAPSHOT_FILE_RE = re.compile(r"### Snapshot\s*-\s*\[Snapshot\]\([^)]*\)\s*")
_RESULT_HEADER_RE = re.compile(r"^### Result\s*\n", re.MULTILINE)
_SNAPSHOT_HEADER_RE = re.compile(r"^### Snapshot\s*\n", re.MULTILINE)
_BLANK_LINES_RE = re.compile(r"\n{3,}")

_PAGE_URL_RE = re.compile(r"^- Page URL:\s*(.+?)\s*$", re.MULTILINE)
_PAGE_TITLE_RE = re.compile(r"^- Page Title:\s*(.+?)\s*$", re.MULTILINE)

#: Команды-действия: важен факт выполнения, а не простыня со снимком.
_QUIET_TOOLS = frozenset(
    {
        "browser_click",
        "browser_type",
        "browser_press_key",
        "browser_select_option",
        "browser_hover",
        "browser_drag",
        "browser_file_upload",
        "browser_handle_dialog",
        "browser_resize",
        "browser_emulate_media",
        "browser_run_code_unsafe",
    }
)


def _strip_service_blocks(text: str) -> str:
    """Убирает служебные блоки Playwright, оставляя содержательную часть."""
    result = _CODE_BLOCK_RE.sub("", text)
    result = _OPEN_TABS_RE.sub("", result)
    result = _PAGE_SECTION_RE.sub("", result)
    result = _SNAPSHOT_FILE_RE.sub("", result)
    result = _RESULT_HEADER_RE.sub("", result)
    result = _SNAPSHOT_HEADER_RE.sub("", result)

    return _BLANK_LINES_RE.sub("\n\n", result).strip()


def _page_summary(text: str) -> str:
    """«Заголовок — адрес» из служебного блока `### Page`."""
    title_match = _PAGE_TITLE_RE.search(text)
    url_match = _PAGE_URL_RE.search(text)

    title = title_match.group(1).strip() if title_match else ""
    url = url_match.group(1).strip() if url_match else ""

    if title and url:
        return f"{title} — {url}"

    return title or url


def _human_error(text: str, profile: BrowserProfile) -> str:
    """Переводит ошибку сервера в русскую подсказку."""
    cleaned = re.sub(r"^###\s*Error\s*\n", "", text.strip())
    cleaned = re.sub(r"^Error:\s*", "", cleaned).strip()

    # Браузер не установлен — частая причина на новой машине.
    if any(marker in text for marker in _BROWSER_MISSING_MARKERS):
        return (
            f"Браузер «{profile.label}» для Playwright MCP не найден. "
            f"{profile.install_hint or 'Установите браузер.'}\n"
            "Выбрать другой: «браузер список», затем «браузер выбери edge»."
        )

    # Ссылка на элемент устарела или её не было: это не поломка, а порядок
    # работы — сервер адресует элементы ссылками из снимка.
    ref_match = re.search(r"Ref\s+(\S+)\s+not found", cleaned, re.IGNORECASE)

    if ref_match:
        return (
            f"Ссылка «{ref_match.group(1)}» не найдена на странице.\n"
            "Ссылки на элементы живут только внутри снимка: сначала "
            "«браузер снимок» или «браузер найди <текст>», затем "
            "«браузер клик <ссылка>» (например «браузер клик e5»)."
        )

    if "No open tabs" in text or "no open pages" in text.lower():
        return "Страница не открыта. Сначала «браузер открой <адрес>»."

    if "ERR_ABORTED" in cleaned:
        return (
            "Переход прерван страницей. Повторите команду или сделайте "
            "«браузер снимок», чтобы увидеть, где оказался браузер."
        )

    if "Timeout" in cleaned:
        return f"Страница не ответила вовремя: {cleaned}"

    if "has been closed" in cleaned:
        return "Браузер закрылся во время выполнения. Повторите команду."

    return f"Браузер не выполнил команду: {cleaned}"


def _human_success(text: str, tool: str) -> str:
    """Приводит успешный ответ сервера к человеческому виду."""
    where = _page_summary(text)

    if tool == "browser_navigate":
        return f"Открыл: {where}" if where else "Страница открыта."

    if tool == "browser_navigate_back":
        return f"Вернулся назад: {where}" if where else "Вернулся назад."

    if tool == "browser_close":
        if "No open tabs" in text:
            return "Страница не была открыта — закрывать нечего."
        return "Браузер закрыт."

    if tool == "browser_take_screenshot":
        return "Скриншот сохранён."

    if tool in _QUIET_TOOLS:
        return f"Готово: {where}" if where else "Готово."

    body = _strip_service_blocks(text)

    if tool == "browser_snapshot" and where:
        return f"Страница: {where}\n{body}".rstrip() if body else f"Страница: {where}"

    return body or (f"Готово: {where}" if where else "Готово.")


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
        """Ответ на команду «браузер выбери …» (текст уходит пользователю)."""
        _ok, message = self.select_browser(name)

        return message

    def select_browser(self, name: str) -> tuple[bool, str]:
        """Выбирает браузер: (получилось, ответ для пользователя).

        Одна реализация на два входа — команду из чата и выбор во вкладке
        «Плагины» панели: правила одни (неизвестное имя не принимаем, для
        браузера без канала Playwright проверяем наличие файла), выбор
        сохраняется в `config/mcp.json` и переживает перезапуск ZERE.
        """
        available = ", ".join(profile.id for profile in BROWSER_PROFILES)

        if not name.strip():
            return False, f"Не указан браузер. Доступны: {available}."

        profile = find_profile(name)

        if profile is None:
            return False, f"Не знаю браузер «{name}». Доступны: {available}."

        # Opera GX и прочие «только по пути» обязаны существовать на диске,
        # иначе команда сменит настройку на заведомо нерабочую.
        if profile.channel is None:
            try:
                browser_args(profile)
            except BrowserNotInstalled as ex:
                return False, str(ex)

        saved = set_server_option(
            self.server_id, "browser", profile.id, self._config_path
        )
        # Явный путь перебивает профиль — сбрасываем его, раз браузер выбран.
        set_server_option(self.server_id, "browserPath", "", self._config_path)

        # Настройки перечитываем и сервер гасим: следующий вызов поднимет его
        # уже с новыми аргументами.
        self.reload_settings()

        note = "" if saved else " (config/mcp.json недоступен — выбор до перезапуска)"

        return True, f"Браузер переключён на {profile.label}.{note}"

    def browser_state(self) -> dict[str, Any]:
        """Состояние выбора браузера для панели (сервер при этом не поднимается).

        `options` отдаём целиком, с отметкой «есть на машине»: панель не
        должна предлагать Opera GX там, где его нет, — иначе выбор молча
        обернётся отказом при первом же переходе.
        """
        profile = self.browser_profile()

        return {
            "current": profile.id,
            "currentLabel": profile.label,
            "channel": profile.channel or "",
            "path": self._browser_path() or "",
            "options": [
                {
                    "id": option.id,
                    "label": option.label,
                    "available": is_available(option),
                    "hint": option.install_hint,
                }
                for option in BROWSER_PROFILES
            ],
        }

    def panel_status(self) -> dict[str, Any]:
        """`status()` + выбор браузера — то, что показывает вкладка «Плагины»."""
        state = self.status()
        state["browser"] = self.browser_state()

        return state

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
        # Лазейка «браузер: <инструмент> {json}» отдаёт ответ сервера как есть:
        # там может быть любой инструмент, и угадывать его смысл нечем.
        if not command.tool.startswith("browser_"):
            return super()._format(result, command)

        if result.is_error:
            return self._truncate(_human_error(result.text, self.browser_profile()))

        return self._truncate(_human_success(result.text, command.tool))


__all__ = ["PlaywrightMcpPlugin"]
