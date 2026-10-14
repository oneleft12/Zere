"""Общая основа MCP-плагинов: ленивый запуск сервера и вызов инструментов.

Что здесь решается один раз для обоих плагинов (браузер и заметки):

- **Сервер не запускается на старте ZERE.** `npx` — это подпроцесс на сотни
  мегабайт; на слабом ПК (целевое железо проекта) поднимать его ради того,
  что пользователь, может быть, не откроет, нельзя. Клиент создаётся при
  первой подходящей команде.
- **Плагин инертен, пока не включён в `config/mcp.json`.** `can_handle`
  возвращает `False`, если сервер выключен или не настроен, — то есть
  установка плагина сама по себе ничего не запускает.
- **Сбой MCP не роняет конвейер.** Ошибка запуска или вызова превращается в
  понятный русский ответ, а не в исключение: плагин — расширение, и его
  поломка не должна мешать ZERE отвечать.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from zere.core.logging.log_service import log_error
from zere.core.mcp.client import McpError, McpStdioClient, McpTool, McpToolResult
from zere.core.mcp.config import McpServerSettings, load_server
from zere.core.plugins.builtin.mcp.mcp_command import (
    McpCommand,
    McpCommandParseError,
    McpCommandRouter,
)
from zere.core.plugins.interfaces.command_handler_plugin import ICommandHandlerPlugin
from zere.core.plugins.interfaces.plugin import IPlugin, PluginType

#: Ограничение длины ответа: ответ уходит в консоль и в озвучку, а снимок
#: страницы или выдержка из заметки легко дают десятки тысяч символов.
DEFAULT_MAX_RESPONSE_CHARS = 2000

ClientFactory = Callable[[McpServerSettings], McpStdioClient]


class McpPluginBase(ICommandHandlerPlugin):
    """Базовый класс MCP-плагина. Наследник задаёт метаданные и разбор фраз.

    Наследуемся только от `ICommandHandlerPlugin`: он уже включает `IPlugin`,
    а `class X(IPlugin, ICommandHandlerPlugin)` даёт несогласованный MRO.
    """

    #: Ключ сервера в config/mcp.json.
    server_id: str = ""

    #: Слова-триггеры команд («браузер», «заметки»).
    triggers: tuple[str, ...] = ()

    #: Метаданные плагина (IПлагин): задаются в наследнике.
    plugin_id: str = ""
    plugin_name: str = ""
    plugin_description: str = ""
    plugin_version: str = "1.0.0"
    plugin_author: str = "ZERE"

    max_response_chars: int = DEFAULT_MAX_RESPONSE_CHARS

    def __init__(
        self,
        *,
        config_path: Optional[Path] = None,
        client_factory: Optional[ClientFactory] = None,
    ) -> None:
        self._config_path = config_path
        self._client_factory = client_factory
        self._router = McpCommandRouter(self.triggers)
        self._settings: McpServerSettings = McpServerSettings(server_id=self.server_id)
        self._client: Optional[McpStdioClient] = None
        self._last_error: str = ""
        self._tools_cache: Optional[list[McpTool]] = None

    # ── IPlugin ─────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self.plugin_id

    @property
    def name(self) -> str:
        return self.plugin_name

    @property
    def description(self) -> str:
        return self.plugin_description

    @property
    def version(self) -> str:
        return self.plugin_version

    @property
    def author(self) -> str:
        return self.plugin_author

    @property
    def type(self) -> PluginType:
        return PluginType.CommandHandler

    def initialize(self) -> None:
        """Читает настройки. Сервер НЕ запускает — это делается лениво."""
        self._settings = load_server(self.server_id, self._config_path)

    def dispose(self) -> None:
        self.close()

    # ── Состояние (для панели) ──────────────────────────────────────

    @property
    def settings(self) -> McpServerSettings:
        return self._settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.enabled and self._settings.configured)

    @property
    def running(self) -> bool:
        return self._client is not None and self._client.alive

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict[str, Any]:
        """Состояние плагина для API панели (без запуска сервера)."""
        return {
            "id": self.plugin_id,
            "serverId": self.server_id,
            "enabled": self.enabled,
            "running": self.running,
            "command": self._settings.describe_command() if self._settings.configured else "",
            "server": dict(self._client.server_info) if self.running and self._client else {},
            "lastError": self._last_error,
        }

    def panel_status(self) -> dict[str, Any]:
        """`status()` плюс настройки, которые показывает вкладка «Плагины».

        База отдаёт только общее состояние; плагин с настройками (выбор
        браузера у Playwright) дополняет словарь своими полями. Панель
        показывает это как есть — без второй модели «что умеет плагин».
        """
        return self.status()

    def close(self) -> None:
        """Останавливает сервер, если он был запущен."""
        client, self._client = self._client, None
        self._tools_cache = None

        if client is None:
            return

        try:
            client.close()
        except Exception as ex:  # noqa: BLE001 — выгрузка не должна падать
            log_error("McpPlugin", f"{self.plugin_id}: сбой остановки сервера: {ex}")

    # ── ICommandHandlerPlugin ───────────────────────────────────────

    @property
    def supported_commands(self) -> list[str]:
        """Примеры фраз для панели. Наследник дополняет."""
        return [f"{self.triggers[0]}: <инструмент> {{json}}" if self.triggers else ""]

    def can_handle(self, message: str) -> bool:
        """Дешёвая проверка без запуска сервера."""
        if not self.enabled:
            return False

        try:
            return self._parse(message) is not None
        except McpCommandParseError:
            # Форма узнана, но аргументы битые: пусть handle покажет ошибку.
            return True

    def handle(self, message: str) -> Optional[str]:
        # Выключенный плагин не делает ничего, даже если handle позвали
        # напрямую (минуя can_handle): иначе пустая команда из конфига
        # превратилась бы в попытку запуска процесса с пустым argv.
        if not self.enabled:
            return None

        try:
            command = self._parse(message)
        except McpCommandParseError as ex:
            return f"Не понял аргументы команды: {ex}."

        if command is None:
            return None

        # Команды, которые плагин выполняет сам (список инструментов, выбор
        # браузера и т. п.) — без обращения к MCP-инструменту.
        local = self._handle_local(command)

        if local is not None:
            return local

        if not self._settings.allows(command.tool):
            return (
                f"Инструмент «{command.tool}» запрещён настройками сервера "
                f"«{self.server_id}» (allowedTools в config/mcp.json)."
            )

        try:
            client = self._ensure_client()
        except McpError as ex:
            self._last_error = str(ex)
            log_error("McpPlugin", f"{self.plugin_id}: {ex}")
            return self._start_failure_message(ex)

        try:
            result = self._call_tool(client, command)
        except McpError as ex:
            self._last_error = str(ex)
            log_error("McpPlugin", f"{self.plugin_id}: вызов {command.tool}: {ex}")
            return f"MCP-сервер «{self.server_id}» не ответил: {ex}"

        self._last_error = ""

        return self._format(result, command)

    # ── Точки расширения ────────────────────────────────────────────

    def _parse_friendly(self, message: str) -> Optional[McpCommand]:
        """Разбор «человеческих» фраз плагина. Наследник переопределяет."""
        return None

    def _handle_local(self, command: McpCommand) -> Optional[str]:
        """Команды, которые плагин выполняет сам, без вызова MCP-инструмента.

        `None` — команда требует вызова инструмента, обработка продолжается.
        """
        if command.source == "list":
            return self._tools_overview()

        return None

    def _format(self, result: McpToolResult, command: McpCommand) -> str:
        """Ответ пользователю. Наследник может добавить подсказки."""
        text = result.text or "(сервер вернул пустой ответ)"

        if result.is_error:
            return self._truncate(f"Ошибка инструмента «{command.tool}»: {text}")

        return self._truncate(text)

    def _call_tool(self, client: McpStdioClient, command: McpCommand) -> McpToolResult:
        """Вызывает инструмент. Наследник может повторить при сбое."""
        return client.call_tool(command.tool, command.arguments)

    def _start_failure_message(self, error: McpError) -> str:
        return f"Не удалось запустить MCP-сервер «{self.server_id}»: {error}"

    # ── Внутреннее ──────────────────────────────────────────────────

    def _parse(self, message: str) -> Optional[McpCommand]:
        generic = self._router.parse(message)

        if generic is not None:
            return generic

        return self._parse_friendly(message)

    def _ensure_client(self) -> McpStdioClient:
        """Возвращает живой клиент, запуская сервер при первом обращении."""
        client = self._client

        if client is not None and client.alive:
            return client

        if client is not None:
            # Сервер умер — поднимаем заново, старый закрываем.
            client.close()
            self._client = None
            self._tools_cache = None

        client = self._build_client()
        client.start()
        self._client = client

        return client

    def _build_client(self) -> McpStdioClient:
        """Создаёт клиента к серверу.

        Фабрика, переданная в конструктор (тесты), имеет приоритет: она
        позволяет проверять плагин без запуска сторонних процессов.
        """
        if self._client_factory is not None:
            return self._client_factory(self._settings)

        return McpStdioClient(
            self._settings.command,
            self._effective_args(),
            env=self._settings.env,
            cwd=self._settings.cwd,
            name=self._settings.server_id,
            request_timeout=self._settings.request_timeout,
            startup_timeout=self._settings.startup_timeout,
        )

    def _effective_args(self) -> list[str]:
        """Аргументы запуска сервера. Наследник может дополнить.

        Например, плагин браузера добавляет сюда `--browser`/`--executable-path`
        выбранного браузера, не трогая сам файл настроек.
        """
        return list(self._settings.args)

    def reload_settings(self) -> None:
        """Перечитывает `config/mcp.json` и гасит запущенный сервер.

        Нужно после смены параметров на лету (выбор браузера): следующая
        команда поднимет сервер уже с новыми аргументами.
        """
        self._settings = load_server(self.server_id, self._config_path)
        self.close()

    def _tools(self) -> list[McpTool]:
        if self._tools_cache is None:
            self._tools_cache = self._ensure_client().list_tools()

        return self._tools_cache

    def _tools_overview(self) -> str:
        try:
            tools = self._tools()
        except McpError as ex:
            self._last_error = str(ex)
            return self._start_failure_message(ex)

        if not tools:
            return f"MCP-сервер «{self.server_id}» не отдал ни одного инструмента."

        lines = [f"Инструменты MCP-сервера «{self.server_id}» ({len(tools)}):"]

        for tool in tools:
            description = " ".join(tool.description.split())
            if len(description) > 80:
                description = description[:77] + "..."
            lines.append(f"— {tool.name}: {description}" if description else f"— {tool.name}")

        lines.append(
            f"Вызов любого: «{self.triggers[0]}: <имя> {{json-аргументы}}»."
            if self.triggers
            else "Вызов любого: «<имя> {json-аргументы}»."
        )

        return self._truncate("\n".join(lines))

    def _truncate(self, text: str) -> str:
        limit = self.max_response_chars

        if limit <= 0 or len(text) <= limit:
            return text

        return text[:limit].rstrip() + f"\n…(сокращено, всего {len(text)} символов)"


__all__ = ["DEFAULT_MAX_RESPONSE_CHARS", "McpPluginBase"]
