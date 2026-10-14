"""Разбор общих форм MCP-команды.

Свои «человеческие» фразы у каждого плагина свои (браузер, заметки), а вот
две формы общие для всех:

- `<триггер> инструменты` — показать список инструментов сервера;
- `<триггер>: <имя_инструмента> {json}` — вызвать любой инструмент напрямую.

Вторая форма — намеренная «лазейка»: MCP-серверы отдают десятки инструментов
(у Playwright их 25, у seekstone 25), и описывать фразы под каждый бессмысленно.
Так весь набор доступен без tool calling и без выдумывания синонимов.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class McpCommand:
    """Разобранная команда: что вызвать и с чем."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    #: Как поняли команду: `phrase` (своя фраза), `generic` (лазейка), `list`.
    source: str = "phrase"


class McpCommandParseError(ValueError):
    """Команда похожа на MCP-вызов, но аргументы не разобрать."""


class McpCommandRouter:
    """Общие формы команд для MCP-плагина."""

    def __init__(self, triggers: Sequence[str]) -> None:
        #: Слова-триггеры («браузер», «заметки») в нижнем регистре.
        self._triggers = tuple(trigger.lower() for trigger in triggers)

    @property
    def triggers(self) -> tuple[str, ...]:
        return self._triggers

    def starts_with_trigger(self, message: str) -> bool:
        lower = message.strip().lower()

        return any(
            lower == trigger or lower.startswith(trigger + " ")
            or lower.startswith(trigger + ":") or lower.startswith(trigger + ",")
            for trigger in self._triggers
        )

    def strip_trigger(self, message: str) -> str:
        """Убирает слово-триггер и разделитель, возвращает остаток."""
        text = message.strip()

        for trigger in self._triggers:
            if text.lower().startswith(trigger):
                text = text[len(trigger):].lstrip()
                break

        return text.lstrip(":,-—").strip()

    def parse(self, message: str) -> Optional[McpCommand]:
        """Разбирает общие формы. `None` — это не общая форма.

        `McpCommandParseError` — форма узнана, но аргументы битые: вызывающий
        покажет понятную ошибку, а не отдаст сообщение дальше по конвейеру.
        """
        if not self.starts_with_trigger(message):
            return None

        rest = self.strip_trigger(message)

        if not rest:
            return None

        lower = rest.lower()

        if lower in ("инструменты", "tools", "список инструментов", "команды"):
            return McpCommand(tool="", source="list")

        # «<tool> {json}» — имя инструмента первым словом, дальше JSON.
        name, _, tail = rest.partition(" ")
        tail = tail.strip()

        if not tail:
            return None

        if not tail.startswith("{"):
            return None

        try:
            arguments = json.loads(tail)
        except json.JSONDecodeError as ex:
            raise McpCommandParseError(
                f"аргументы должны быть JSON-объектом: {ex.msg} (позиция {ex.pos})"
            ) from ex

        if not isinstance(arguments, dict):
            raise McpCommandParseError("аргументы должны быть JSON-объектом в фигурных скобках")

        return McpCommand(tool=name.strip(), arguments=arguments, source="generic")


__all__ = ["McpCommand", "McpCommandParseError", "McpCommandRouter"]
