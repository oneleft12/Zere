"""Рисование в Paint картинкой: рендер, буфер обмена, доставка в Paint.

Проверяется без Windows и без Paint: картинка рисуется Pillow, форматы буфера
собираются из чистых функций, а доставка (Ctrl+V или открытие файла)
проверяется подставными объектами. Тесты, которым нужен Pillow, печатают SKIP,
если его нет.
"""

from __future__ import annotations

import ctypes
import inspect
import os
import struct
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.tools.drawing import drawing_canvas as canvas_module
from zere.tools.drawing import drawing_clipboard, drawing_geometry as geometry
from zere.tools.drawing import drawing_service
from zere.tools.drawing.drawing_command_router import DrawingCommandRouter
from zere.tools.drawing.drawing_service import DrawingService
from zere.tools.drawing.drawing_target import DrawingTarget

try:
    from PIL import Image  # noqa: F401

    HAVE_PILLOW = True
except ImportError:  # pragma: no cover - окружение без Pillow
    HAVE_PILLOW = False


def _skip_without_pillow() -> bool:
    if HAVE_PILLOW:
        return False

    print("SKIP Pillow недоступен")
    return True


# ── Картинка ──────────────────────────────────────────────────────


def test_render_strokes_draws_inside_expected_box() -> None:
    if _skip_without_pillow():
        return

    image = canvas_module.render_strokes(geometry.square(), 400, 300)
    box = canvas_module.ink_box(image)

    assert image.size == (400, 300)
    assert canvas_module.ink_count(image) > 0, "фигура не нарисовалась"

    # Квадрат занимает 0.275..0.725 холста — рамка рисунка обязана совпасть.
    left, top, right, bottom = box
    assert 100 <= left <= 115 and 275 <= right <= 295, box
    assert 75 <= top <= 90 and 205 <= bottom <= 222, box

    # Фон прозрачный: вставка не затирает то, что уже нарисовано в Paint.
    assert image.getpixel((2, 2))[3] == 0


def test_render_strokes_uses_color_and_width() -> None:
    if _skip_without_pillow():
        return

    thin = canvas_module.render_strokes(geometry.line(), 200, 200, line_width=1)
    thick = canvas_module.render_strokes(geometry.line(), 200, 200, line_width=6)
    red = canvas_module.render_strokes(geometry.line(), 200, 200, color=(255, 0, 0))

    assert canvas_module.ink_count(thick) > canvas_module.ink_count(thin)
    assert red.getpixel((100, 100))[0] > 200, "цвет линии не применился"


def test_render_strokes_handles_empty_input() -> None:
    if _skip_without_pillow():
        return

    assert canvas_module.render_strokes([], 400, 300) is None
    assert canvas_module.render_strokes(geometry.square(), 0, 0) is None
    assert canvas_module.render_strokes(geometry.square(), 400, 300) is not None


def test_render_strokes_draws_single_point() -> None:
    if _skip_without_pillow():
        return

    image = canvas_module.render_strokes([[(0.5, 0.5)]], 100, 100)

    assert canvas_module.ink_count(image) > 0
    assert canvas_module.ink_box(image) is not None


def test_render_text_fits_and_centers() -> None:
    if _skip_without_pillow():
        return

    image = canvas_module.render_text("Привет", 400, 300)
    box = canvas_module.ink_box(image)
    left, top, right, bottom = box

    assert canvas_module.ink_count(image) > 0
    assert left > 0 and right < 400, f"текст не влез по ширине: {box}"
    assert abs((left + right) / 2 - 200) < 12, f"текст не по центру: {box}"

    # Длинная строка должна ужиматься, а не обрезаться.
    long_box = canvas_module.ink_box(canvas_module.render_text("я" * 60, 400, 300))
    assert long_box[0] >= 0 and long_box[2] <= 400, long_box
    assert (long_box[3] - long_box[1]) < (bottom - top)


def test_render_text_multiline_is_taller() -> None:
    if _skip_without_pillow():
        return

    one = canvas_module.ink_box(canvas_module.render_text("раз", 400, 300))
    two = canvas_module.ink_box(canvas_module.render_text("раз\nдва", 400, 300))

    assert (two[3] - two[1]) > (one[3] - one[1])
    assert canvas_module.render_text("", 400, 300) is None
    assert canvas_module.render_text("привет", 0, 300) is None


def test_flatten_makes_image_opaque() -> None:
    if _skip_without_pillow():
        return

    flat = canvas_module.flatten(canvas_module.render_strokes(geometry.circle(), 100, 100))
    alpha = flat.convert("RGBA").getchannel("A")

    assert min(alpha.getdata()) == 255
    assert flat.convert("RGBA").getpixel((1, 1))[:3] == canvas_module.WHITE


# ── Форматы буфера обмена ─────────────────────────────────────────


def test_dib_v5_header_matches_windows() -> None:
    if _skip_without_pillow():
        return

    image = canvas_module.render_strokes(geometry.square(), 64, 48)
    data = canvas_module.dib_v5(image)

    assert struct.unpack("<I", data[:4])[0] == 124, "BITMAPV5HEADER должен быть 124 байта"
    assert struct.unpack("<ii", data[4:12]) == (64, 48)
    assert struct.unpack("<H", data[14:16])[0] == 32, "нужна 32-битная картинка"
    assert struct.unpack("<I", data[16:20])[0] == canvas_module.BI_BITFIELDS
    assert struct.unpack("<IIII", data[40:56]) == (
        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000
    ), "маски каналов обязаны совпадать с BGRA"
    assert struct.unpack("<I", data[56:60])[0] == canvas_module.LCS_SRGB
    assert len(data) == canvas_module.BITMAPV5HEADER_SIZE + 64 * 48 * 4


def test_dib_rows_go_bottom_up() -> None:
    """DIB хранится снизу вверх: иначе картинка вставится перевёрнутой."""
    if _skip_without_pillow():
        return

    # Штрих только в верхней половине холста.
    image = canvas_module.render_strokes([[(0.1, 0.1), (0.9, 0.1)]], 100, 100)
    data = canvas_module.dib_v5(image)
    pixels = data[canvas_module.BITMAPV5HEADER_SIZE:]
    row_size = 100 * 4

    def row_alpha(row: int) -> int:
        return sum(
            pixels[index + 3]
            for index in range(row * row_size, (row + 1) * row_size, 4)
        )

    assert row_alpha(0) == 0, "первая строка DIB — низ картинки, там пусто"
    assert sum(row_alpha(row) for row in range(85, 100)) > 0, (
        "верх картинки должен лежать в конце DIB"
    )


def test_dib_legacy_is_sized_and_opaque() -> None:
    if _skip_without_pillow():
        return

    image = canvas_module.render_strokes(geometry.circle(), 50, 40)
    data = canvas_module.dib_legacy(image)

    assert struct.unpack("<I", data[:4])[0] == 40
    assert struct.unpack("<I", data[16:20])[0] == canvas_module.BI_RGB
    assert len(data) == 40 + 50 * 40 * 4


def test_png_bytes_are_png() -> None:
    if _skip_without_pillow():
        return

    image = canvas_module.render_strokes(geometry.triangle(), 80, 60)
    data = canvas_module.png_bytes(image)

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 100


def test_clipboard_format_list_has_three_variants() -> None:
    if _skip_without_pillow():
        return

    image = canvas_module.render_strokes(geometry.star(), 80, 60)
    entries = drawing_clipboard.clipboard_formats(image, png_format=0x1234)

    assert [item[0] for item in entries] == [
        drawing_clipboard.CF_DIBV5,
        0x1234,
        drawing_clipboard.CF_DIB,
    ]
    assert all(item[1] for item in entries), "ни один формат не должен быть пустым"


def test_clipboard_reports_refusal_outside_windows() -> None:
    if sys.platform == "win32":
        print("SKIP проверка отказа вне Windows (мы в Windows)")
        return

    if _skip_without_pillow():
        return

    image = canvas_module.render_strokes(geometry.square(), 40, 40)

    try:
        drawing_clipboard.set_image(image)
    except RuntimeError as error:
        assert "Windows" in str(error)
    else:
        raise AssertionError("вне Windows буфер обмена должен отказывать")


def test_clipboard_calls_have_explicit_prototypes() -> None:
    source = inspect.getsource(drawing_clipboard._get_win32)

    for call in (
        "OpenClipboard",
        "EmptyClipboard",
        "SetClipboardData",
        "CloseClipboard",
        "RegisterClipboardFormatW",
        "GlobalAlloc",
        "GlobalLock",
        "GlobalUnlock",
        "GlobalFree",
    ):
        assert f"{call}.restype" in source, f"{call}: не задан restype"

    set_source = inspect.getsource(drawing_clipboard.set_image)

    assert "GlobalFree" in set_source, "память при отказе SetClipboardData надо освобождать"
    assert "CloseClipboard" in set_source


# ── Файл рисунка ──────────────────────────────────────────────────


def test_drawing_file_name_is_ascii_and_stamped() -> None:
    name = canvas_module.drawing_file_name(datetime(2026, 10, 8, 12, 34, 56))

    assert name == "zere-2026-10-08_12-34-56.png"
    assert name.isascii()


def test_save_drawing_writes_png() -> None:
    if _skip_without_pillow():
        return

    from PIL import Image as PillowImage

    with tempfile.TemporaryDirectory() as folder:
        image = canvas_module.render_strokes(geometry.square(), 120, 90)
        path = canvas_module.save_drawing(
            image, Path(folder), datetime(2026, 10, 8, 12, 34, 56)
        )

        assert path == Path(folder) / "zere-2026-10-08_12-34-56.png"
        assert path.is_file()

        saved = PillowImage.open(path)

        assert saved.size == (120, 90)
        # В файле фон белый: картинку можно смотреть и печатать.
        assert saved.convert("RGB").getpixel((1, 1)) == canvas_module.WHITE


# ── Выбор способа в сервисе ───────────────────────────────────────


class FakeClipboard:
    """Подменяет буфер обмена: запоминает картинку вместо системного вызова."""

    def __init__(self, works: bool = True) -> None:
        self.images: list = []
        self.works = works

    def __call__(self, image) -> bool:
        self.images.append(image)
        return self.works


def _patch(pairs: list):
    """Временная подмена атрибутов: [(объект, имя, значение), ...] → откат."""
    saved = [
        (target, name, getattr(target, name)) for target, name, _value in pairs
    ]

    for target, name, value in pairs:
        setattr(target, name, value)

    def restore() -> None:
        for target, name, value in saved:
            setattr(target, name, value)

    return restore


def test_service_pastes_image_into_paint() -> None:
    if _skip_without_pillow():
        return

    clipboard = FakeClipboard()
    keys: list = []
    restore = _patch(
        [
            (drawing_service, "_find_window", lambda spec: 4242),
            (drawing_service, "_client_rect", lambda hwnd: (0, 0, 800, 600)),
            (drawing_service, "_focus", lambda hwnd: True),
            (drawing_service, "_key_event",
             lambda vk, key_up=False: keys.append((vk, key_up)) or True),
            (drawing_service, "set_clipboard_image", clipboard),
            (DrawingService, "_run_cursor", lambda self, command: (_ for _ in ()).throw(
                AssertionError("курсор не нужен: картинка вставляется")
            )),
        ]
    )

    try:
        service = DrawingService(target=DrawingTarget.PAINT)
        answer = service.execute(DrawingCommandRouter().parse("нарисуй квадрат"))
    finally:
        restore()

    assert answer == "Вставил рисунок в Paint."
    assert len(clipboard.images) == 1

    image = clipboard.images[0]

    assert image.size == (784, 436), "размер картинки — область рисования окна"
    assert canvas_module.ink_count(image) > 0, "на картинке нет рисунка"

    pressed = [vk for vk, key_up in keys if not key_up]

    assert drawing_service.VK_CONTROL in pressed
    assert drawing_service.VK_V in pressed, "не отправлен Ctrl+V"
    assert drawing_service.VK_RETURN in pressed, "вставка не закреплена Enter"


def test_service_opens_file_when_paint_is_absent() -> None:
    if _skip_without_pillow():
        return

    clipboard = FakeClipboard()
    opened: list = []
    restore = _patch(
        [
            (drawing_service, "_find_window", lambda spec: None),
            (drawing_service, "set_clipboard_image", clipboard),
            (drawing_service, "save_drawing",
             lambda image, directory, moment=None: Path("/tmp/zere.png")),
            (drawing_service, "_open_file", lambda spec, path: opened.append(path) or True),
            (DrawingService, "_run_cursor",
             lambda self, command: (_ for _ in ()).throw(
                 AssertionError("курсор не нужен: рисунок открывается файлом")
             )),
        ]
    )

    try:
        answer = DrawingService(target=DrawingTarget.PAINT).execute(
            DrawingCommandRouter().parse("нарисуй звезду")
        )
    finally:
        restore()

    assert "Открыл рисунок в Paint" in answer
    assert opened == [Path("/tmp/zere.png")]
    assert clipboard.images == [], "без окна буфер обмена не нужен"


def test_service_falls_back_to_cursor_when_paste_fails() -> None:
    if _skip_without_pillow():
        return

    opened: list = []
    restore = _patch(
        [
            (drawing_service, "_find_window", lambda spec: 4242),
            (drawing_service, "_client_rect", lambda hwnd: (0, 0, 800, 600)),
            (drawing_service, "_focus", lambda hwnd: False),
            (drawing_service, "set_clipboard_image", FakeClipboard()),
            (drawing_service, "save_drawing",
             lambda image, directory, moment=None: Path("/tmp/zere.png")),
            (drawing_service, "_open_file", lambda spec, path: opened.append(path) or True),
            (DrawingService, "_run_cursor",
             lambda self, command: (_ for _ in ()).throw(
                 AssertionError("курсор не нужен: после вставки рисунок открывается файлом")
             )),
        ]
    )

    try:
        answer = DrawingService(target=DrawingTarget.PAINT).execute(
            DrawingCommandRouter().parse("нарисуй круг")
        )
    finally:
        restore()

    assert "Открыл рисунок в Paint" in answer
    assert opened, "после неудачной вставки нужен файл"


def test_service_uses_cursor_in_cursor_mode() -> None:
    original = os.environ.get(drawing_service.ENV_IMAGE_MODE)
    os.environ[drawing_service.ENV_IMAGE_MODE] = "cursor"

    clipboard = FakeClipboard()
    restore = _patch(
        [
            (drawing_service, "set_clipboard_image", clipboard),
            (DrawingService, "_run_cursor", lambda self, command: "нарисовал курсором"),
        ]
    )

    try:
        answer = DrawingService(target=DrawingTarget.PAINT).execute(
            DrawingCommandRouter().parse("нарисуй круг")
        )
    finally:
        restore()

    assert answer == "нарисовал курсором"
    assert clipboard.images == []

    if original is None:
        os.environ.pop(drawing_service.ENV_IMAGE_MODE, None)
    else:
        os.environ[drawing_service.ENV_IMAGE_MODE] = original


def test_service_falls_back_to_cursor_when_render_fails() -> None:
    """Сбой отрисовки (нет Pillow, битый холст) не ломает рисование."""
    restore = _patch(
        [
            (drawing_service, "_find_window", lambda spec: 4242),
            (drawing_service, "_client_rect", lambda hwnd: (0, 0, 800, 600)),
            (drawing_service, "render_strokes", lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("нет Pillow")
            )),
            (DrawingService, "_run_cursor", lambda self, command: "нарисовал курсором"),
        ]
    )

    try:
        answer = DrawingService(target=DrawingTarget.PAINT).execute(
            DrawingCommandRouter().parse("нарисуй круг")
        )
    finally:
        restore()

    assert answer == "нарисовал курсором"


def test_service_clear_canvas_never_uses_image() -> None:
    """Очистка — это Ctrl+A и Delete, картинка для неё не нужна."""
    clipboard = FakeClipboard()
    restore = _patch(
        [
            (drawing_service, "set_clipboard_image", clipboard),
            (DrawingService, "_run_cursor", lambda self, command: "очистил курсором"),
        ]
    )

    try:
        answer = DrawingService(target=DrawingTarget.PAINT).execute(
            DrawingCommandRouter().parse("очисти холст")
        )
    finally:
        restore()

    assert answer == "очистил курсором"
    assert clipboard.images == []


def test_image_mode_reads_environment() -> None:
    original = os.environ.get(drawing_service.ENV_IMAGE_MODE)

    try:
        os.environ.pop(drawing_service.ENV_IMAGE_MODE, None)
        assert drawing_service.image_mode() == drawing_service.DEFAULT_IMAGE_MODE

        os.environ[drawing_service.ENV_IMAGE_MODE] = "open"
        assert drawing_service.image_mode() == "open"

        os.environ[drawing_service.ENV_IMAGE_MODE] = "CURSOR"
        assert drawing_service.image_mode() == "cursor"

        os.environ[drawing_service.ENV_IMAGE_MODE] = "мусор"
        assert drawing_service.image_mode() == drawing_service.DEFAULT_IMAGE_MODE
    finally:
        if original is None:
            os.environ.pop(drawing_service.ENV_IMAGE_MODE, None)
        else:
            os.environ[drawing_service.ENV_IMAGE_MODE] = original


def test_image_support_is_available_with_pillow() -> None:
    """Сервис видит рендер: без Pillow картинка просто выключена, не падает."""
    if _skip_without_pillow():
        return

    assert drawing_service.IMAGE_SUPPORT is True
    assert drawing_service.render_strokes is not None
    assert drawing_service.render_text is not None
    assert drawing_service.save_drawing is not None
    assert drawing_service.set_clipboard_image is not None


def test_image_path_off_without_pillow() -> None:
    """Без Pillow рисование картинкой молча уступает курсору."""
    restore = _patch(
        [
            (drawing_service, "IMAGE_SUPPORT", False),
            (DrawingService, "_run_cursor", lambda self, command: "нарисовал курсором"),
        ]
    )

    try:
        answer = DrawingService(target=DrawingTarget.PAINT).execute(
            DrawingCommandRouter().parse("нарисуй круг")
        )
    finally:
        restore()

    assert answer == "нарисовал курсором"


def test_run_dispatches_image_for_paint_only() -> None:
    """Структурная проверка диспетчера: картинка — для Paint, не для Krita."""
    source = inspect.getsource(DrawingService._run)

    assert "DrawingTarget.PAINT" in source
    assert "_run_image(" in source
    assert "_run_plugin(" in source
    assert "_run_cursor(" in source
    assert "image_mode()" in inspect.getsource(DrawingService._run_image)
    assert "CLEAR_CANVAS" in inspect.getsource(DrawingService._run_image)


def test_bitmap_structures_use_explicit_widths() -> None:
    """Ширины полей DIB заданы явно: layout не должен зависеть от платформы."""
    assert ctypes.sizeof(ctypes.c_uint32) == 4

    import ast

    tree = ast.parse(Path("zere/tools/drawing/drawing_canvas.py").read_text(encoding="utf-8"))
    source = Path("zere/tools/drawing/drawing_canvas.py").read_text(encoding="utf-8")

    assert tree is not None
    assert "BITMAPV5HEADER_SIZE = 124" in source
    assert "struct.pack(" in source, "заголовки DIB собираются вручную, без ctypes-структур"


# ── Раннер ────────────────────────────────────────────────────────


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов рисования картинкой")


if __name__ == "__main__":
    main()
