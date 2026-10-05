"""Обработчик рисования: фигуры и текст в Krita и Paint.

Стоит перед AIHandler, но после команд системы: без него «нарисуй круг»
уходило бы в LLM, а «напиши письмо другу» — наоборот, не должно попадать сюда,
поэтому тексты на холсте требуют явного якоря (см. DrawingCommandRouter).
"""

from __future__ import annotations

from zere.core.handlers.i_zere_handler import IZereHandler
from zere.tools.drawing.drawing_command_router import DrawingCommandRouter
from zere.tools.drawing.drawing_command_type import DrawingCommandType
from zere.tools.drawing.drawing_service import DrawingService

# Быстрый предфильтр: без этих слов команда рисования невозможна.
_ANCHORS = (
    "рисуй",
    "нарисуй",
    "начерти",
    "изобраз",
    "напиши",
    "холст",
    "крит",
    "пейнт",
    "пэйнт",
    "паинт",
    "paint",
    "krita",
)


class DrawingHandler(IZereHandler):
    def __init__(self, service: DrawingService) -> None:
        self._service = service
        self._router = DrawingCommandRouter()

    def can_handle(self, message: str) -> bool:
        lower = message.lower()

        if not any(anchor in lower for anchor in _ANCHORS):
            return False

        # Решает разбор: он требует либо глагол рисования с фигурой,
        # либо явный якорь для текста, либо точную команду смены цели.
        return self._router.parse(message).type is not DrawingCommandType.NONE

    def handle(self, message: str) -> str:
        return self._service.execute(self._router.parse(message))
