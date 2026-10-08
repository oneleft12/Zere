"""Картинка вместо курсора: ZERE рисует сам и отдаёт результат в Paint.

У Paint нет ни API, ни плагина, поэтому надёжный способ «нарисовать в Paint»
один: нарисовать картинку самому (Pillow) и отдать её одним действием —
вставкой из буфера (Ctrl+V) или открытием файла. Вместо сотен координат
мыши — один достоверный акт, зато доступны цвет, толщина, сглаживание и
настоящий шрифт (курсорный способ рисует тем, что выбрано в редакторе).

Модуль чистый: ни Windows, ни Paint для проверки не нужны — на входе те же
штрихи в нормализованных координатах, что и у `drawing_geometry`.
"""

from __future__ import annotations

import struct
from datetime import datetime
from io import BytesIO
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from zere.tools.drawing.drawing_font import find_font_path
from zere.tools.drawing.drawing_geometry import DrawingCanvas, Stroke

Color = Tuple[int, int, int]

#: Рисуем крупнее и уменьшаем: так линии получаются сглаженными.
SUPERSAMPLE = 2

DEFAULT_COLOR: Color = (16, 16, 16)
DEFAULT_LINE_WIDTH = 2
#: Размер картинки, когда окно редактора не измерить.
CANVAS_DEFAULT_SIZE = (1280, 960)

TEXT_HEIGHT_FRACTION = 0.25
TEXT_LINE_SPACING = 1.25
MIN_FONT_SIZE = 8

WHITE: Color = (255, 255, 255)
#: Куда складывать готовые картинки (открываются в Paint как файл).
DRAWINGS_DIR_NAME = "drawings"

# ── Форматы буфера обмена ─────────────────────────────────────────

#: BITMAPV5HEADER: 40 байт BITMAPINFOHEADER + маски, цветовое пространство,
#: конечные точки, гаммы, назначение и профиль.
BITMAPV5HEADER_SIZE = 124
BI_RGB = 0
BI_BITFIELDS = 3
LCS_SRGB = 0x73524742  # 'sRGB'
PIXELS_PER_METER = 2835  # 72 dpi


def new_image(width: int, height: int,
              background: Optional[Color] = None) -> Image.Image:
    """Пустая картинка: прозрачная (для вставки) или залитая цветом (для файла)."""
    mode = "RGBA" if background is None else "RGB"
    image = Image.new(mode, (max(1, int(width)), max(1, int(height))),
                      background if background is not None else (0, 0, 0, 0))

    return image.convert("RGBA")


def _stroke_points(stroke: Stroke, width: int, height: int,
                   scale: int) -> list:
    """Штрих в пикселях картинки (с учётом надвыборки)."""
    canvas = DrawingCanvas(0, 0, width, height)

    return [
        (x * scale, y * scale)
        for x, y in (canvas.to_screen(px, py) for px, py in stroke)
    ]


def render_strokes(strokes: Sequence[Stroke], width: int, height: int,
                   color: Color = DEFAULT_COLOR,
                   line_width: int = DEFAULT_LINE_WIDTH,
                   background: Optional[Color] = None,
                   supersample: int = SUPERSAMPLE) -> Optional[Image.Image]:
    """Фигуры в картинку. None — если рисовать нечего или холст пустой."""
    if width <= 0 or height <= 0 or not strokes:
        return None

    scale = max(1, int(supersample))
    image = new_image(width * scale, height * scale)
    draw = ImageDraw.Draw(image)
    stroke_width = max(1, int(round(line_width * scale)))

    for stroke in strokes:
        points = _stroke_points(stroke, width, height, scale)

        if len(points) < 2:
            # Точка: круглая метка размером с толщину линии.
            if points:
                x, y = points[0]
                radius = stroke_width / 2.0
                draw.ellipse(
                    (x - radius, y - radius, x + radius, y + radius), fill=color
                )
            continue

        draw.line(points, fill=color, width=stroke_width, joint="curve")

    image = image.resize((width, height), Image.LANCZOS)

    if background is not None:
        image = flatten(image, background)

    return image


def _load_font(size: int) -> ImageFont.ImageFont:
    """Системный шрифт нужного размера; без файла — встроенный."""
    path = find_font_path()

    if path:
        try:
            return ImageFont.truetype(path, max(1, int(size)))
        except OSError:
            pass

    return ImageFont.load_default()


def render_text(text: str, width: int, height: int,
                color: Color = DEFAULT_COLOR,
                background: Optional[Color] = None) -> Optional[Image.Image]:
    """Текст в картинку: строки по центру, размер подбирается по холсту."""
    lines = [line for line in str(text or "").splitlines() if line.strip()]

    if not lines or width <= 0 or height <= 0:
        return None

    size = max(MIN_FONT_SIZE, int(height * TEXT_HEIGHT_FRACTION))
    font = _load_font(size)

    # Подгоняем размер так, чтобы самая длинная строка уложилась в 90 % ширины.
    longest = max(lines, key=len)
    measured = font.getbbox(longest)[2] or 1

    if measured > width * 0.9:
        size = max(MIN_FONT_SIZE, int(size * width * 0.9 / measured))
        font = _load_font(size)

    image = new_image(width, height)
    draw = ImageDraw.Draw(image)
    line_height = size * TEXT_LINE_SPACING
    offset_y = (height - line_height * len(lines)) / 2.0

    for line in lines:
        left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
        draw.text(
            ((width - (right - left)) / 2.0 - left, offset_y - top),
            line,
            font=font,
            fill=color,
        )
        offset_y += line_height

    if background is not None:
        image = flatten(image, background)

    return image


def flatten(image: Image.Image, background: Color = WHITE) -> Image.Image:
    """Накладывает картинку на непрозрачный фон (для старых программ)."""
    canvas = Image.new("RGBA", image.size, (*background, 255))
    canvas.alpha_composite(image.convert("RGBA"))

    return canvas


def ink_box(image: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    """Рамка непрозрачных пикселей: по ней видно, появился ли рисунок."""
    alpha = image.convert("RGBA").getchannel("A")

    return alpha.getbbox()


def ink_count(image: Image.Image, threshold: int = 8) -> int:
    """Сколько пикселей нарисовано (в рамке и рядом с ней)."""
    alpha = image.convert("RGBA").getchannel("A")

    return sum(1 for value in alpha.getdata() if value > threshold)


# ── Буфер обмена: DIB и PNG ───────────────────────────────────────


def _dib_pixels(image: Image.Image, opaque: bool) -> Tuple[bytes, int]:
    """Пиксели DIB снизу вверх в порядке BGRA."""
    rgba = image.convert("RGBA")

    if opaque:
        rgba = flatten(rgba)

    width, height = rgba.size
    raw = rgba.tobytes()
    row_size = width * 4
    rows = []

    for y in range(height - 1, -1, -1):
        rows.append(raw[y * row_size:(y + 1) * row_size])

    return b"".join(rows), height


def dib_v5(image: Image.Image) -> bytes:
    """BITMAPV5HEADER + пиксели: современный формат с прозрачностью."""
    pixels, height = _dib_pixels(image, opaque=False)
    width = image.size[0]

    header = struct.pack(
        "<IiiHHIIiiII",
        BITMAPV5HEADER_SIZE,
        width,
        height,
        1,
        32,
        BI_BITFIELDS,
        len(pixels),
        PIXELS_PER_METER,
        PIXELS_PER_METER,
        0,
        0,
    )
    masks = struct.pack("<IIII", 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    colour_space = struct.pack("<I", LCS_SRGB)

    return b"".join(
        (
            header,
            masks,
            colour_space,
            bytes(36),                              # конечные точки цвета
            struct.pack("<III", 0, 0, 0),           # гаммы
            struct.pack("<I", 0),                   # назначение (intent)
            struct.pack("<II", 0, 0),               # профиль: смещение и размер
            struct.pack("<I", 0),                   # зарезервировано
            pixels,
        )
    )


def dib_legacy(image: Image.Image) -> bytes:
    """BITMAPINFOHEADER + пиксели без прозрачности: для старых программ."""
    pixels, height = _dib_pixels(image, opaque=True)
    width = image.size[0]

    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height,
        1,
        32,
        BI_RGB,
        len(pixels),
        PIXELS_PER_METER,
        PIXELS_PER_METER,
        0,
        0,
    )

    return header + pixels


def png_bytes(image: Image.Image) -> bytes:
    """PNG-представление: его понимают современные приложения (Paint тоже)."""
    buffer = BytesIO()
    image.convert("RGBA").save(buffer, format="PNG")

    return buffer.getvalue()


# ── Файл и имя ────────────────────────────────────────────────────


def drawing_file_name(moment: Optional[datetime] = None) -> str:
    """Имя файла рисунка: латиницей и без пробелов — так надёжнее в путях."""
    stamp = (moment or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")

    return f"zere-{stamp}.png"


def save_drawing(image: Image.Image, directory, moment: Optional[datetime] = None):
    """Сохраняет картинку в папку рисунков и возвращает путь."""
    from pathlib import Path

    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / drawing_file_name(moment)

    flatten(image).convert("RGB").save(path, format="PNG")

    return path
