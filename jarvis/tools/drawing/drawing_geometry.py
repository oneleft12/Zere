"""Геометрия рисования: фигуры и перевод координат — чистые функции.

Все фигуры возвращаются в нормализованных координатах холста: x и y от 0 до 1,
(0, 0) — левый верхний угол. В экранные пиксели их переводит
DrawingCanvas.to_screen, поэтому и фигуры, и канвас тестируются без Windows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

Point = Tuple[float, float]
Stroke = List[Point]

# 72 отрезка на окружность: на экране выглядит гладко, но не тормозит рисование.
CIRCLE_SEGMENTS = 72


def circle(cx: float = 0.5, cy: float = 0.5, radius: float = 0.35,
           segments: int = CIRCLE_SEGMENTS) -> List[Stroke]:
    """Окружность (замкнутая ломаная)."""
    return ellipse(cx, cy, radius, radius, segments)


def ellipse(cx: float = 0.5, cy: float = 0.5, rx: float = 0.42,
            ry: float = 0.30, segments: int = CIRCLE_SEGMENTS) -> List[Stroke]:
    """Эллипс с заданными полуосями."""
    steps = max(8, int(segments))
    points: Stroke = []

    for index in range(steps):
        angle = 2.0 * math.pi * index / steps
        points.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))

    # Замыкаем точно первым узлом: cos(2π) не равен 1.0 побитово.
    points.append(points[0])

    return [points]


def rectangle(x0: float = 0.15, y0: float = 0.20,
              x1: float = 0.85, y1: float = 0.80) -> List[Stroke]:
    """Прямоугольник по двум углам (замкнутый)."""
    return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]


def square(cx: float = 0.5, cy: float = 0.5, side: float = 0.6) -> List[Stroke]:
    """Квадрат по центру."""
    half = side / 2.0
    return rectangle(cx - half, cy - half, cx + half, cy + half)


def triangle(cx: float = 0.5, cy: float = 0.45, radius: float = 0.38) -> List[Stroke]:
    """Равносторонний треугольник вершиной вверх (замкнутый)."""
    points: Stroke = []

    for index in range(3):
        angle = -math.pi / 2.0 + 2.0 * math.pi * index / 3.0
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    points.append(points[0])
    return [points]


def line(x0: float = 0.15, y0: float = 0.85,
         x1: float = 0.85, y1: float = 0.15) -> List[Stroke]:
    """Отрезок по диагонали холста."""
    return [[(x0, y0), (x1, y1)]]


def star(cx: float = 0.5, cy: float = 0.5, points_count: int = 5,
         r_outer: float = 0.40, r_inner: float = 0.16) -> List[Stroke]:
    """Пятиконечная звезда (замкнутая)."""
    total = max(3, int(points_count))
    points: Stroke = []

    for index in range(total * 2):
        radius = r_outer if index % 2 == 0 else r_inner
        angle = -math.pi / 2.0 + math.pi * index / total
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    # Замыкаем точно первым узлом (см. ellipse).
    points.append(points[0])

    return [points]


def polyline_from_bitmap(rows: Sequence[Sequence[bool]]) -> List[Stroke]:
    """Превращает растр в горизонтальные штрихи — «рисование плоттером».

    Каждая непрерывная полоса тёмных пикселей в строке становится отрезком.
    Так текст рисуется без ручного набора глифов и работает для любого языка.
    """
    strokes: List[Stroke] = []

    height = len(rows)
    if height == 0:
        return strokes

    width = max((len(row) for row in rows), default=0)
    if width == 0:
        return strokes

    for y, row in enumerate(rows):
        x = 0
        row_length = len(row)

        while x < row_length:
            if not row[x]:
                x += 1
                continue

            start = x
            while x < row_length and row[x]:
                x += 1
            end = x

            center_y = (y + 0.5) / height
            strokes.append([(start / width, center_y), (end / width, center_y)])

    return strokes


def fit_strokes(
    strokes: Sequence[Stroke],
    source_cols: int,
    source_rows: int,
    canvas_width: int,
    canvas_height: int,
    max_fraction: float = 0.9,
) -> List[Stroke]:
    """Вписывает штрихи в холст, сохраняя пропорции исходного растра.

    Штрихи приходят нормализованными в свои 0..1; здесь они масштабируются так,
    чтобы пиксель растра оставался квадратным на экране, и центрируются.
    """
    if not strokes or source_cols <= 0 or source_rows <= 0:
        return []

    if canvas_width <= 0 or canvas_height <= 0:
        return []

    limit = min(max(max_fraction, 0.05), 1.0)

    # Аспект источника в «клетках»: ширина / высота.
    source_aspect = source_cols / source_rows

    width_fraction = limit
    height_fraction = width_fraction * canvas_width / (source_aspect * canvas_height)

    if height_fraction > limit:
        height_fraction = limit
        width_fraction = height_fraction * source_aspect * canvas_height / canvas_width

    offset_x = (1.0 - width_fraction) / 2.0
    offset_y = (1.0 - height_fraction) / 2.0

    return [
        [(offset_x + x * width_fraction, offset_y + y * height_fraction)
         for (x, y) in stroke]
        for stroke in strokes
    ]


@dataclass(frozen=True)
class DrawingCanvas:
    """Область рисования в экранных координатах (пиксели)."""

    left: int
    top: int
    width: int
    height: int

    @classmethod
    def from_client(
        cls,
        client_left: int,
        client_top: int,
        client_width: int,
        client_height: int,
        insets: Tuple[int, int, int, int] = (0, 0, 0, 0),
        min_size: int = 120,
    ) -> "DrawingCanvas":
        """Холст = клиентская область окна минус отступы (лента, доки).

        Если окно слишком маленькое, холст центрируется и сжимается до
        размеров клиентской области, чтобы координаты остались внутри окна.
        """
        inset_left, inset_top, inset_right, inset_bottom = insets

        width = client_width - inset_left - inset_right
        height = client_height - inset_top - inset_bottom

        if width < min_size:
            width = min(client_width, min_size)
        if height < min_size:
            height = min(client_height, min_size)

        left = client_left + max(0, (client_width - width) // 2)
        top = client_top + max(0, (client_height - height) // 2)

        return cls(left, top, width, height)

    def to_screen(self, x: float, y: float) -> Tuple[int, int]:
        """Нормализованная точка холста (0..1) → пиксели экрана."""
        clamped_x = min(max(x, 0.0), 1.0)
        clamped_y = min(max(y, 0.0), 1.0)

        return (
            int(self.left + round(clamped_x * (self.width - 1))),
            int(self.top + round(clamped_y * (self.height - 1))),
        )
