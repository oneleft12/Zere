"""SVG для Krita: фигуры и текст вектором, без эмуляции мыши.

Krita умеет принимать SVG прямо в векторный слой
(`VectorLayer.addShapesFromSvg`), поэтому ZERE отдаёт разметку: фигура выходит
точной, с цветом и толщиной, и остаётся редактируемой в Krita. Функции модуля
чистые — проверяются без Krita и без Windows.

Координаты фигур нормализованы (0..1) и приходят из `drawing_geometry` — тех же
функций, что рисуют курсором, поэтому фигуры везде одинаковые.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from zere.tools.drawing.drawing_geometry import Stroke

#: Цвет и толщина по умолчанию: тёмная линия средней толщины на любом фоне.
DEFAULT_COLOR = "#101010"
DEFAULT_STROKE_WIDTH = 2.0

#: Высота текста — доля высоты холста; шрифт системный (в Krita есть Segoe UI).
FONT_FAMILY = "Segoe UI"
TEXT_HEIGHT_FRACTION = 0.25
TEXT_LINE_SPACING = 1.25
MIN_FONT_SIZE = 8.0

#: Замена в XML: амперсанд обязан идти первым, иначе «&lt;» станет «&amp;lt;».
_ESCAPES = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
    ("'", "&apos;"),
)


def escape_text(value: str) -> str:
    """Текст, безопасный для XML/SVG."""
    escaped = str(value or "")

    for source, replacement in _ESCAPES:
        escaped = escaped.replace(source, replacement)

    return escaped


def _point(x: float, y: float, width: int, height: int) -> Tuple[float, float]:
    """Нормализованная точка холста (0..1) → пиксели документа Krita."""
    return (
        round(min(max(x, 0.0), 1.0) * (width - 1), 1),
        round(min(max(y, 0.0), 1.0) * (height - 1), 1),
    )


def _points_attribute(stroke: Sequence[Tuple[float, float]], width: int,
                      height: int) -> str:
    return " ".join(
        f"{x},{y}" for x, y in (_point(px, py, width, height) for px, py in stroke)
    )


def stroke_element(stroke: Stroke, width: int, height: int,
                   color: str = DEFAULT_COLOR,
                   stroke_width: float = DEFAULT_STROKE_WIDTH) -> Optional[str]:
    """Один штрих: замкнутый — полигон, открытый — ломаная, точка — кружок."""
    if not stroke:
        return None

    if len(stroke) == 1:
        x, y = _point(stroke[0][0], stroke[0][1], width, height)
        radius = max(0.5, float(stroke_width) / 2.0)
        return f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}"/>'

    style = (
        f'fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round"'
    )

    if len(stroke) > 2 and stroke[0] == stroke[-1]:
        # Полигон замыкается сам: повторять первую точку в атрибуте не нужно.
        points = _points_attribute(stroke[:-1], width, height)
        return f'<polygon points="{points}" {style}/>'

    points = _points_attribute(stroke, width, height)
    return f'<polyline points="{points}" {style}/>'


def canvas_svg(width: int, height: int, body: str) -> str:
    """SVG нужного размера вокруг готового содержимого."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
        f"{body}</svg>"
    )


def strokes_svg(strokes: Sequence[Stroke], width: int, height: int,
                color: str = DEFAULT_COLOR,
                stroke_width: float = DEFAULT_STROKE_WIDTH) -> str:
    """Фигура целиком: все штрихи одной разметкой.

    Пустой список даёт пустой SVG: вызывающий сам решает, что делать
    (например, повторить рисунок мазками кистью).
    """
    if width <= 0 or height <= 0:
        return ""

    elements: List[str] = []

    for stroke in strokes:
        element = stroke_element(stroke, width, height, color, stroke_width)

        if element:
            elements.append(element)

    if not elements:
        return ""

    return canvas_svg(width, height, "".join(elements))


def text_svg(text: str, width: int, height: int, color: str = DEFAULT_COLOR,
             font_size: Optional[float] = None,
             font_family: str = FONT_FAMILY) -> str:
    """Текст вектором: строки по центру холста.

    Размер подбирается по холсту и длине самой длинной строки: иначе длинная
    надпись уезжает за края документа.
    """
    lines = [line for line in str(text or "").splitlines() if line.strip()]

    if not lines or width <= 0 or height <= 0:
        return ""

    size = float(font_size or height * TEXT_HEIGHT_FRACTION)
    longest = max(len(line) for line in lines)
    # Ширина символа ≈ 0.55 высоты шрифта: держим текст в 90 % холста.
    fits = width * 0.9 / (longest * 0.55)
    size = max(MIN_FONT_SIZE, min(size, fits))

    line_height = size * TEXT_LINE_SPACING
    block = line_height * len(lines)
    first_baseline = (height - block) / 2.0 + size

    elements = []

    for index, line in enumerate(lines):
        baseline = first_baseline + index * line_height
        elements.append(
            f'<text x="{round(width / 2.0, 1)}" y="{round(baseline, 1)}" '
            f'font-family="{escape_text(font_family)}" font-size="{round(size, 1)}" '
            f'fill="{color}" text-anchor="middle">{escape_text(line)}</text>'
        )

    return canvas_svg(width, height, "".join(elements))
