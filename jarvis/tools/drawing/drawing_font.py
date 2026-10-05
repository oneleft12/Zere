"""Текст для рисования: растр шрифта → горизонтальные штрихи.

Ручной набор глифов не нужен: текст рисуется «плоттером» — шрифт растеризуется
через Pillow, уменьшается до сетки и превращается в отрезки
(`drawing_geometry.polyline_from_bitmap`). Поэтому работает любой текст, включая
кириллицу, и не нужен ни один шрифтовой файл в репозитории.

Pillow импортируется внутри функций: модуль остаётся импортируемым там, где
Pillow не установлен (тесты разбора команд и геометрии идут без него).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

from jarvis.tools.drawing.drawing_geometry import Stroke, polyline_from_bitmap

# Ширина растра: хватает на читаемый текст, но не превращает рисование в часы.
MIN_COLUMNS = 48
MAX_COLUMNS = 160
COLUMNS_PER_CHAR = 12

# Порог «тёмный пиксель»: после уменьшения края серые, 160 сохраняет тонкие штрихи.
DARK_THRESHOLD = 160

FONT_SIZE = 64

_FONT_CANDIDATES = (
    r"%WINDIR%\Fonts\segoeui.ttf",
    r"%WINDIR%\Fonts\arial.ttf",
    r"%WINDIR%\Fonts\tahoma.ttf",
    r"%WINDIR%\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def find_font_path() -> Optional[str]:
    """Первый доступный TrueType-шрифт с кириллицей; None — если не нашли."""
    for template in _FONT_CANDIDATES:
        path = Path(os.path.expandvars(template))

        if path.is_file():
            return str(path)

    return None


def columns_for(text: str) -> int:
    """Ширина растра под длину текста."""
    wanted = len((text or "").strip()) * COLUMNS_PER_CHAR
    return max(MIN_COLUMNS, min(MAX_COLUMNS, wanted))


def render_text_bitmap(
    text: str,
    columns: Optional[int] = None,
    font_size: int = FONT_SIZE,
    font_path: Optional[str] = None,
) -> List[List[bool]]:
    """Растеризует текст и уменьшает его до сетки columns × rows."""
    from PIL import Image, ImageDraw  # локально: без Pillow модуль импортируется

    cleaned = (text or "").strip()

    if not cleaned:
        return []

    width = max(8, int(columns) if columns else columns_for(cleaned))
    font = _load_font(font_size, font_path)

    probe = Image.new("L", (8, 8), 255)
    bounds = ImageDraw.Draw(probe).textbbox((0, 0), cleaned, font=font)

    text_width = max(1, bounds[2] - bounds[0])
    text_height = max(1, bounds[3] - bounds[1])

    # Пропорции сохраняем: строк столько, сколько нужно под ширину растра.
    rows = max(1, round(width * text_height / text_width))

    canvas = Image.new("L", (text_width + 4, text_height + 4), 255)
    ImageDraw.Draw(canvas).text(
        (2 - bounds[0], 2 - bounds[1]), cleaned, font=font, fill=0
    )

    small = canvas.resize((width, rows), Image.LANCZOS)
    pixels = small.load()

    return [
        [pixels[x, y] < DARK_THRESHOLD for x in range(width)]
        for y in range(rows)
    ]


def text_strokes(
    text: str,
    columns: Optional[int] = None,
    font_size: int = FONT_SIZE,
    font_path: Optional[str] = None,
) -> Tuple[List[Stroke], int, int]:
    """Текст → штрихи и размеры исходного растра (для fit_strokes)."""
    rows = render_text_bitmap(text, columns=columns, font_size=font_size,
                              font_path=font_path)

    if not rows:
        return [], 0, 0

    return polyline_from_bitmap(rows), len(rows[0]), len(rows)


def _load_font(font_size: int, font_path: Optional[str]):
    """TrueType-шрифт из явного пути, из кандидатов или встроенный запасной."""
    from PIL import ImageFont

    candidates: List[str] = []

    if font_path:
        candidates.append(font_path)

    found = find_font_path()
    if found:
        candidates.append(found)

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, font_size)
        except OSError:
            continue

    # Pillow < 10.1 не принимает size — запасной растровый шрифт без кириллицы.
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()
