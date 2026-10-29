#!/usr/bin/env python3
"""Иконка ZERE: тёмный квадрат со скруглением, циановый контур и «Z».

Иконка нужна сразу трём вещам: окну приложения (pywebview/exe), ярлыкам
установщика и самому `zere.exe` (ресурс /win32icon). Рисуется кодом, а не
хранится «магическим» бинарником: цвета — из панели (`panel/src/styles/
tokens.css`), поэтому иконка и интерфейс не расходятся.

Запуск: python scripts/make_icon.py [--out assets/zere.ico]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]

# Цвета из panel/src/styles/tokens.css (тёмная тема — основная).
BG_TOP = (10, 18, 28, 255)  # #0a121c
BG_BOTTOM = (5, 8, 13, 255)  # #05080d
ACCENT = (34, 224, 255, 255)  # #22e0ff
ACCENT_2 = (139, 92, 255, 255)  # #8b5cff
TEXT = (233, 242, 250, 255)  # #e9f2fa

# Размеры, которые Windows реально берёт: панель задач, список, alt-tab, ярлык.
ICON_SIZES = (256, 128, 64, 48, 32, 24, 16)
SUPERSAMPLE = 4

# Segoe UI Bold есть на любой Windows 10/11 — иконка не тянет сторонний шрифт.
FONT_CANDIDATES = (
    Path("/mnt/c/Windows/Fonts/segoeuib.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
    Path(__file__).resolve().parents[1] / "assets" / "segoeuib.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)

    # Без Segoe UI остаётся встроенный шрифт Pillow: буква есть, но тоньше.
    return ImageFont.load_default(size)


def _vertical_gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    top = Image.new("RGBA", (size, 1), BG_TOP)
    bottom = Image.new("RGBA", (size, 1), BG_BOTTOM)
    for y in range(size):
        ratio = y / max(size - 1, 1)
        row = Image.blend(top, bottom, ratio).resize((size, 1))
        image.paste(row, (0, y))
    return image


def _rounded_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * 0.22)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _draw_glow(layer: Image.Image, box: tuple[int, int, int, int], color, width: int) -> None:
    """Мягкое свечение под контуром: рисуем дважды — блюр и резкий контур."""
    glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(box, outline=color, width=width)
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(width * 2)))
    ImageDraw.Draw(layer).ellipse(box, outline=color, width=width)


def render(size: int = 1024) -> Image.Image:
    """Рисует иконку в квадрате `size` (с запасом для сглаживания)."""
    image = _vertical_gradient(size)
    image.putalpha(_rounded_mask(size))

    pad = int(size * 0.17)
    ring_box = (pad, pad, size - pad, size - pad)
    ring_width = max(2, int(size * 0.028))
    _draw_glow(image, ring_box, ACCENT, ring_width)

    # Второй контур — фиолетовая дуга снизу: «данные» панели (accent-2).
    arc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    arc_draw = ImageDraw.Draw(arc)
    arc_draw.arc(ring_box, start=205, end=335, fill=ACCENT_2, width=max(2, int(size * 0.022)))
    image.alpha_composite(arc.filter(ImageFilter.GaussianBlur(max(1, int(size * 0.004)))))
    image.alpha_composite(arc)

    # Буква «Z»: центр, чуть выше оптического центра.
    font = _font(int(size * 0.46))
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.textbbox((0, 0), "Z", font=font)
    x = (size - (right - left)) / 2 - left
    y = (size - (bottom - top)) / 2 - top - int(size * 0.02)
    draw.text((x, y), "Z", font=font, fill=TEXT)

    return image


def build(out: Path) -> Path:
    master = render(1024)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = [master.resize((s, s), Image.LANCZOS) for s in ICON_SIZES]
    # Pillow сам собирает многоразмерный .ico, если передать sizes.
    frames[0].save(
        out,
        format="ICO",
        sizes=[(s, s) for s in ICON_SIZES],
        append_images=frames[1:],
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Нарисовать assets/zere.ico")
    parser.add_argument("--out", default=str(ROOT / "assets" / "zere.ico"))
    args = parser.parse_args()

    path = build(Path(args.out))
    print(f"Иконка: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
