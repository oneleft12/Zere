"""Разбор команд рисования.

Ключевое решение: «напиши …» само по себе командой НЕ считается — иначе
«напиши письмо другу» уходило бы в рисование вместо LLM. Текст на холсте
требует явного якоря: «нарисуй текст …», «напиши на холсте …»,
«напиши в пейнте …».
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

from zere.tools.drawing.drawing_command_type import DrawingCommandType
from zere.tools.drawing.drawing_target import DrawingTarget

# «в крите», «в krita», «на krita». Без предлога — только точные формы,
# чтобы «критично» не превращалось в цель рисования.
_KRITA_WITH_PREPOSITION = re.compile(
    r"\b(?:в|во|на)\s+(?:крит\w*|krita|crita)\b", re.IGNORECASE
)
_PAINT_WITH_PREPOSITION = re.compile(
    r"\b(?:в|во|на)\s+(?:пейнт\w*|пэйнт\w*|паинт\w*|paint)\b", re.IGNORECASE
)
_KRITA_BARE = re.compile(r"\b(?:крит[аеуы]|krita|crita)\b", re.IGNORECASE)
_PAINT_BARE = re.compile(r"\b(?:пейнт\w*|пэйнт\w*|паинт\w*|paint)\b", re.IGNORECASE)

# Глагол рисования: «нарисовать»/«нарисуешь» намеренно не в списке —
# это часть вопроса («как нарисовать круг?»), а не команда.
_DRAW_VERB = re.compile(
    r"\b(?:нарисуй|нарисуйте|начерти|начертите|изобрази|рисуй|рисуйте)\b",
    re.IGNORECASE,
)

# Переключение цели: после вырезания цели остаётся только глагол.
_SET_TARGET_ONLY = re.compile(
    r"^(?:рисуй|рисуйте|рисовать|переключись|переключи|перейди|выбери)"
    r"(?:\s+(?:тут|здесь|там|пожалуйста))?$",
    re.IGNORECASE,
)

_CLEAR_MARKERS = ("очист", "очисть", "сотри", "стереть", "сотрите")

# Явные якоря для текста на холсте.
_TEXT_PREFIXES = (
    r"нарисуй\s+текст\s+",
    r"нарисуй\s+надпись\s+",
    r"напиши\s+текст\s+",
    r"напиши\s+надпись\s+",
    r"напиши\s+на\s+холсте\s+",
    r"напиши\s+слова?\s+",
)

# Фигуры: порядок важен — «прямоугольник» проверяется раньше «угольник».
_SHAPE_PATTERNS: tuple[tuple[DrawingCommandType, str], ...] = (
    (DrawingCommandType.DRAW_RECTANGLE, r"\bпрямоугольник\w*\b"),
    (DrawingCommandType.DRAW_SQUARE, r"\bквадрат\w*\b"),
    (DrawingCommandType.DRAW_ELLIPSE, r"\b(?:овал|эллипс)\w*\b"),
    (DrawingCommandType.DRAW_CIRCLE, r"\b(?:круг|окружность|кружок)\w*\b"),
    (DrawingCommandType.DRAW_TRIANGLE, r"\bтреугольник\w*\b"),
    (DrawingCommandType.DRAW_STAR, r"\b(?:звезд\w*|звёзд\w*)\b"),
    (DrawingCommandType.DRAW_LINE, r"\b(?:лини\w*|черт\w*|отрезок)\b"),
)


class ParsedDrawingCommand(NamedTuple):
    """Разобранная команда рисования."""

    type: DrawingCommandType
    # Текст для WRITE_TEXT, иначе пустая строка.
    value: str = ""
    # Цель, если она названа прямо в команде («… в пейнте»).
    target: Optional[DrawingTarget] = None


class DrawingCommandRouter:
    """Разбирает фразу пользователя в команду рисования."""

    def parse(self, message: str) -> ParsedDrawingCommand:
        text = (message or "").strip()

        if not text:
            return ParsedDrawingCommand(DrawingCommandType.NONE)

        if self.is_negated(text):
            return ParsedDrawingCommand(DrawingCommandType.NONE)

        without_target, target = self._extract_target(text)
        rest = without_target.strip()

        if not rest:
            return ParsedDrawingCommand(DrawingCommandType.NONE)

        # 1) Переключение цели: «рисуй в крите», «переключись на пейнт».
        if target is not None and _SET_TARGET_ONLY.match(rest):
            return ParsedDrawingCommand(
                DrawingCommandType.SET_TARGET, target.value, target
            )

        lower = rest.lower()

        # 2) Очистка холста.
        if "холст" in lower and any(marker in lower for marker in _CLEAR_MARKERS):
            return ParsedDrawingCommand(
                DrawingCommandType.CLEAR_CANVAS, "", target
            )

        # 3) Текст с явным якорем.
        for prefix in _TEXT_PREFIXES:
            match = re.match(prefix, rest, re.IGNORECASE)
            if match:
                payload = self._clean_payload(rest[match.end():])
                if payload:
                    return ParsedDrawingCommand(
                        DrawingCommandType.WRITE_TEXT, payload, target
                    )

        # 4) Текст без якоря — только если цель названа явно
        #    («напиши в пейнте привет»). Иначе это просьба к LLM.
        match = re.match(r"напиши\s+", rest, re.IGNORECASE)
        if match and target is not None:
            payload = self._clean_payload(rest[match.end():])
            if payload:
                return ParsedDrawingCommand(
                    DrawingCommandType.WRITE_TEXT, payload, target
                )

        # 5) Фигуры — нужен глагол рисования.
        if _DRAW_VERB.search(lower):
            for command_type, pattern in _SHAPE_PATTERNS:
                if re.search(pattern, lower):
                    return ParsedDrawingCommand(command_type, "", target)

        return ParsedDrawingCommand(DrawingCommandType.NONE)

    @staticmethod
    def is_negated(text: str) -> bool:
        """«не рисуй», «нет, не надо» — не команда рисования."""
        lower = text.lower().strip(" .,!?:;")
        tokens = [token for token in lower.replace(",", " ").split() if token]

        if not tokens:
            return False

        if tokens[0] in ("не", "нет"):
            return True

        return bool(
            re.search(r"\bне\s+(?:рисуй|рисовать|нарисуй|начерти|изобрази)", lower)
        )

    @staticmethod
    def _clean_payload(payload: str) -> str:
        """Убирает кавычки и лишние пробелы вокруг текста для рисования."""
        return payload.strip().strip("\"'«»").strip()

    @staticmethod
    def _extract_target(text: str) -> tuple[str, Optional[DrawingTarget]]:
        """Вырезает упоминание цели и возвращает остаток фразы."""
        for pattern, target in (
            (_KRITA_WITH_PREPOSITION, DrawingTarget.KRITA),
            (_PAINT_WITH_PREPOSITION, DrawingTarget.PAINT),
            (_KRITA_BARE, DrawingTarget.KRITA),
            (_PAINT_BARE, DrawingTarget.PAINT),
        ):
            replaced, count = pattern.subn(" ", text, count=1)
            if count:
                return replaced, target

        return text, None
