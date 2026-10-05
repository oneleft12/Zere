"""Типы команд рисования."""

from __future__ import annotations

from enum import Enum


class DrawingCommandType(Enum):
    NONE = 0
    SET_TARGET = 1
    DRAW_CIRCLE = 2
    DRAW_ELLIPSE = 3
    DRAW_RECTANGLE = 4
    DRAW_SQUARE = 5
    DRAW_TRIANGLE = 6
    DRAW_LINE = 7
    DRAW_STAR = 8
    WRITE_TEXT = 9
    CLEAR_CANVAS = 10
