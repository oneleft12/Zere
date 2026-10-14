"""Плагин Obsidian MCP: заметки локального хранилища.

Сервер — `seekstone` (проверено на 0.22.1: 25 инструментов, `protocolVersion`
2025-11-25). Выбран осознанно: он **файловый** — читает хранилище напрямую,
без плагина Obsidian Local REST API, без ключа и без запущенного приложения.
Для проекта с офлайн-принципом это единственный подходящий вариант: остальные
Obsidian MCP-серверы требуют работающего Obsidian и токена REST API.

Хранилище задаётся переменной окружения `SEEKSTONE_VAULT` в
`config/mcp.json` (секция `env`). Плагин дополняет память ZERE: память —
факты о пользователе в SQLite, заметки — его собственная база знаний.

Полный набор инструментов доступен через «заметки: <инструмент> {json}».
"""

from __future__ import annotations

import json
from typing import Any, Optional

from zere.core.mcp.client import McpToolResult
from zere.core.plugins.builtin.mcp.mcp_command import McpCommand
from zere.core.plugins.builtin.mcp.mcp_plugin_base import McpPluginBase

#: Признаки незаданного хранилища (текст реального сервера).
_VAULT_MISSING_MARKERS = (
    "SEEKSTONE_VAULT",
    "vault",
)

#: Сколько записей показываем в списке, прежде чем ответ станет «простынёй».
_MAX_LIST_ITEMS = 20


def _shorten(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())

    return text if len(text) <= limit else text[: limit - 3] + "..."


def _render_items(items: list[Any]) -> str:
    lines: list[str] = []

    for item in items[:_MAX_LIST_ITEMS]:
        if isinstance(item, str):
            lines.append(f"— {_shorten(item)}")
            continue

        if not isinstance(item, dict):
            continue

        title = item.get("path") or item.get("name") or item.get("tag") or "?"
        excerpt = item.get("excerpt") or item.get("text") or item.get("content") or ""
        excerpt = _shorten(excerpt)

        lines.append(f"— {title}: {excerpt}" if excerpt else f"— {title}")

    if len(items) > _MAX_LIST_ITEMS:
        lines.append(f"…и ещё {len(items) - _MAX_LIST_ITEMS}")

    return "\n".join(lines)


def _humanize(text: str) -> str:
    """Превращает JSON-выдачу seekstone в читаемый текст.

    Сервер отвечает компактным JSON (он рассчитан на модель, а не на человека),
    а ответ ZERE читает пользователь и озвучка — JSON в этом месте бесполезен.
    """
    stripped = text.strip()

    if not stripped.startswith(("{", "[")):
        return text

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return text

    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, str) and content.strip():
            return content.rstrip()

        for key in ("results", "notes", "items", "tags", "matches"):
            value = data.get(key)
            if isinstance(value, list):
                rendered = _render_items(value)
                return rendered or text

        return text

    if isinstance(data, list):
        return _render_items(data) or text

    return text


class ObsidianMcpPlugin(McpPluginBase):
    """Заметки Obsidian через MCP-сервер seekstone."""

    server_id = "obsidian"
    triggers = ("заметки", "заметка", "obsidian")

    plugin_id = "obsidian-mcp"
    plugin_name = "Obsidian MCP (заметки)"
    plugin_description = (
        "Поиск, чтение и правка заметок локального хранилища Obsidian через "
        "MCP-сервер seekstone (файловый доступ, без плагина Obsidian)."
    )
    plugin_version = "1.0.0"

    #: Выдержки из заметок бывают длинными — режем, чтобы озвучка не «читала книгу».
    max_response_chars = 2500

    @property
    def supported_commands(self) -> list[str]:
        return [
            "заметки найди <запрос>",
            "заметки список [папка]",
            "заметки теги",
            "заметки прочитай <путь>",
            "заметки создай <путь>[: текст]",
            "заметки допиши <путь>: <текст>",
            "заметки инструменты",
            "заметки: <инструмент> {json}",
        ]

    # ── Разбор фраз ─────────────────────────────────────────────────

    def _parse_friendly(self, message: str) -> Optional[McpCommand]:
        with_trigger = self._router.starts_with_trigger(message)
        text = self._router.strip_trigger(message) if with_trigger else message.strip()

        if not text:
            return None

        lower = text.lower()

        # Список заметок и теги.
        if lower in ("список", "список заметок", "все заметки"):
            return McpCommand(tool="list_notes", arguments={})

        if lower in ("теги", "теги заметок", "список тегов"):
            return McpCommand(tool="list_tags", arguments={})

        # Поиск: с триггером — «заметки найди X», без — «найди в заметках X».
        for prefix in (
            "найди в заметках ",
            "поиск в заметках ",
            "поищи в заметках ",
            "найди ",
            "поиск ",
        ):
            if lower.startswith(prefix):
                query = text[len(prefix):].strip()
                if query:
                    return McpCommand(tool="search", arguments={"query": query})

        # Чтение заметки.
        for prefix in ("прочитай заметку ", "открой заметку ", "покажи заметку ", "прочитай "):
            if lower.startswith(prefix):
                path = text[len(prefix):].strip()
                if path:
                    return McpCommand(tool="read_note", arguments={"path": path})

        # Создание заметки (с необязательным телом после двоеточия).
        for prefix in ("создай заметку ", "новая заметка ", "создай "):
            if lower.startswith(prefix):
                rest = text[len(prefix):].strip()
                if not rest:
                    return None

                path, separator, content = rest.partition(":")
                arguments = {"path": path.strip()}

                if separator and content.strip():
                    arguments["content"] = content.strip()

                return McpCommand(tool="create_note", arguments=arguments)

        # Дописывание в заметку — тело обязательно.
        for prefix in ("допиши в заметку ", "допиши заметку ", "добавь в заметку ", "допиши "):
            if lower.startswith(prefix):
                rest = text[len(prefix):]
                path, separator, content = rest.partition(":")

                if not separator or not path.strip() or not content.strip():
                    return None

                return McpCommand(
                    tool="append_note",
                    arguments={"path": path.strip(), "content": content.strip()},
                )

        return None

    # ── Ответ ───────────────────────────────────────────────────────

    def _format(self, result: McpToolResult, command: McpCommand) -> str:
        text = result.text or "(сервер вернул пустой ответ)"

        if result.is_error and "SEEKSTONE_VAULT" in text:
            return (
                "Не задано хранилище Obsidian. Укажите путь к нему в "
                "config/mcp.json, сервер «obsidian», секция env:\n"
                '    "env": { "SEEKSTONE_VAULT": "C:\\\\Путь\\\\к\\\\хранилищу" }'
            )

        if result.is_error:
            return super()._format(result, command)

        return self._truncate(_humanize(text))


__all__ = ["ObsidianMcpPlugin"]
