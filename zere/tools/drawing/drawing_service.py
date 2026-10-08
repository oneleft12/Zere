"""Рисование в Krita и Paint эмуляцией мыши Win32.

Почему эмуляция ввода, а не API приложения: у Paint API нет вовсе, а Krita
требует установки плагина PyKrita и его включения в настройках. Эмуляция
работает в обоих приложениях (и в любом другом редакторе) без настройки.

Плата за универсальность — курсор на время рисования занят. Поэтому перед
началом выдерживается пауза (пользователь успевает отпустить мышь), а после
рисования возвращается прежнее активное окно.

Модуль импортируется и на не-Windows: Win32-вызовы создаются лениво, внутри
функций, а `execute` возвращает понятный отказ вместо исключения.
"""

from __future__ import annotations

import ctypes
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from zere.core.logging.log_service import log_error
from zere.tools.drawing.drawing_command_router import ParsedDrawingCommand
from zere.tools.drawing.drawing_command_type import DrawingCommandType
from zere.tools.drawing.drawing_font import text_strokes
from zere.tools.drawing.drawing_geometry import (
    DrawingCanvas,
    Stroke,
    circle,
    document_canvas,
    ellipse,
    fit_strokes,
    line,
    rectangle,
    square,
    star,
    triangle,
)
from zere.tools.drawing.drawing_target import (
    DEFAULT_TARGET,
    DrawingTarget,
    display_name,
    expand_template,
    spec_for,
)

# ── Настройки таймингов (сек, пиксели) ────────────────────────────

# Ожидание окна после запуска приложения: Krita стартует небыстро.
WINDOW_WAIT_SECONDS = 25.0
WINDOW_POLL_SECONDS = 0.5

FOCUS_ATTEMPTS = 30
FOCUS_DELAY = 0.1

# Пауза перед рисованием: пользователь должен успеть отпустить мышь.
PREPARE_DELAY = 0.6

# Шаг интерполяции штриха: чаще — плавнее, но дольше.
STEP_PIXELS = 5.0
# Пауза между движениями курсора. Меньше ~5 мс Windows склеивает
# WM_MOUSEMOVE, и приложение видит только точку вместо штриха.
MOVE_DELAY = 0.010
# Пауза между штрихами: у текста их сотни, поэтому пауза небольшая.
STROKE_DELAY = 0.010
# Потолок точек на штрих: длинную окружность разбиваем крупнее,
# иначе рисование растягивается на секунды без выигрыша в качестве.
MAX_POINTS_PER_STROKE = 120
# Минимальный холст, при котором рисование вообще имеет смысл.
MIN_CANVAS_SIZE = 80

# Срез снимка экрана не доходит до краёв области рисования: у самого края
# рамка окна, а справа и снизу могут стоять полосы прокрутки.
SAMPLE_MARGIN = 2
SCROLLBAR_MARGIN = 18

# ── Константы Win32 ───────────────────────────────────────────────

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0

SW_RESTORE = 9
GW_OWNER = 4

# GetSystemMetrics: границы виртуального рабочего стола (мультимонитор).
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
DPI_AWARENESS_PER_MONITOR_V2 = -4

VK_CONTROL = 0x11
VK_A = 0x41
VK_DELETE = 0x2E

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class _MOUSEINPUT(ctypes.Structure):
    """MOUSEINPUT. Ширины заданы явно: layout структур не должен зависеть от ОС."""

    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


class _BITMAPINFOHEADER(ctypes.Structure):
    """BITMAPINFOHEADER. Ширины заданы явно — layout не должен зависеть от ОС."""

    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


_user32 = None
_gdi32 = None


def _as_hwnd(value: object) -> int:
    """HWND из ctypes: c_void_p приходит как int или None — приводим к int."""
    return int(value) if value else 0


def _get_user32():
    """Дескриптор user32; создаётся при первом обращении и только в Windows.

    Прототипы обязательны: без них ctypes считает результат `int` (32 бита) и
    обрезает 64-битные HWND — тогда ни фокус, ни поиск окна не подтверждаются.
    """
    global _user32

    if _user32 is not None:
        return _user32

    if sys.platform != "win32":
        raise RuntimeError("Рисование поддерживается только в Windows.")

    from ctypes import wintypes

    handle = ctypes.WinDLL("user32", use_last_error=True)

    handle.SendInput.argtypes = (
        ctypes.c_uint,
        ctypes.POINTER(_INPUT),
        ctypes.c_int,
    )
    handle.SendInput.restype = ctypes.c_uint

    handle.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    handle.SetCursorPos.restype = ctypes.c_bool

    handle.GetForegroundWindow.argtypes = ()
    handle.GetForegroundWindow.restype = wintypes.HWND

    handle.SetForegroundWindow.argtypes = (wintypes.HWND,)
    handle.SetForegroundWindow.restype = wintypes.BOOL

    handle.BringWindowToTop.argtypes = (wintypes.HWND,)
    handle.BringWindowToTop.restype = wintypes.BOOL

    handle.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    handle.ShowWindow.restype = wintypes.BOOL

    handle.GetWindow.argtypes = (wintypes.HWND, ctypes.c_uint)
    handle.GetWindow.restype = wintypes.HWND

    handle.IsWindowVisible.argtypes = (wintypes.HWND,)
    handle.IsWindowVisible.restype = wintypes.BOOL

    handle.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    handle.GetWindowTextLengthW.restype = ctypes.c_int

    handle.GetWindowTextW.argtypes = (
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    )
    handle.GetWindowTextW.restype = ctypes.c_int

    handle.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    handle.GetWindowThreadProcessId.restype = wintypes.DWORD

    handle.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    handle.GetClientRect.restype = wintypes.BOOL

    handle.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    handle.ClientToScreen.restype = wintypes.BOOL

    handle.GetSystemMetrics.argtypes = (ctypes.c_int,)
    handle.GetSystemMetrics.restype = ctypes.c_int

    handle.GetDC.argtypes = (wintypes.HWND,)
    handle.GetDC.restype = wintypes.HDC

    handle.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    handle.ReleaseDC.restype = ctypes.c_int

    # Эти две есть не во всех Windows: без них координаты на масштабированных
    # дисплеях виртуализируются и уезжают.
    for name in ("SetThreadDpiAwarenessContext", "SetProcessDPIAware"):
        try:
            function = getattr(handle, name)
        except AttributeError:
            continue

        function.restype = wintypes.BOOL

    # Прототип EnumWindows задаётся в _find_window: там известен тип колбэка.

    _user32 = handle
    return handle


def _get_gdi32():
    """Дескриптор gdi32 для снимка экрана; создаётся лениво и только в Windows."""
    global _gdi32

    if _gdi32 is not None:
        return _gdi32

    if sys.platform != "win32":
        raise RuntimeError("Снимок экрана поддерживается только в Windows.")

    from ctypes import wintypes

    handle = ctypes.WinDLL("gdi32", use_last_error=True)

    handle.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    handle.CreateCompatibleDC.restype = wintypes.HDC

    handle.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
    handle.CreateCompatibleBitmap.restype = wintypes.HBITMAP

    handle.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
    handle.SelectObject.restype = wintypes.HGDIOBJ

    handle.BitBlt.argtypes = (
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint32,
    )
    handle.BitBlt.restype = wintypes.BOOL

    handle.GetDIBits.argtypes = (
        wintypes.HDC,
        wintypes.HBITMAP,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(_BITMAPINFO),
        ctypes.c_uint,
    )
    handle.GetDIBits.restype = ctypes.c_int

    handle.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    handle.DeleteObject.restype = wintypes.BOOL

    handle.DeleteDC.argtypes = (wintypes.HDC,)
    handle.DeleteDC.restype = wintypes.BOOL

    _gdi32 = handle
    return handle


def _screen_colors(x: int, y: int, width: int, height: int) -> List[Tuple[int, int, int]]:
    """Цвета пикселей прямоугольника экрана: строка за строкой, сверху вниз.

    Нужны, чтобы отличить документ от подложки вокруг него: Paint игнорирует
    штрих, начатый вне изображения. Контексты освобождаются всегда — снимок
    не должен течь даже при ошибке.
    """
    from ctypes import wintypes

    if width <= 0 or height <= 0:
        return []

    user = _get_user32()
    gdi = _get_gdi32()

    screen = user.GetDC(None)
    if not screen:
        raise OSError("не удалось получить контекст экрана")

    memory = gdi.CreateCompatibleDC(screen)
    bitmap = gdi.CreateCompatibleBitmap(screen, width, height) if memory else None

    try:
        if not memory or not bitmap:
            raise OSError("не удалось создать совместимый контекст снимка")

        previous = gdi.SelectObject(memory, bitmap)

        try:
            if not gdi.BitBlt(memory, 0, 0, width, height, screen, x, y, SRCCOPY):
                raise OSError("не удалось скопировать область экрана")

            info = _BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            # Отрицательная высота: строки идут сверху вниз, как на экране.
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB

            buffer = ctypes.create_string_buffer(width * height * 4)
            copied = gdi.GetDIBits(
                memory, bitmap, 0, height, buffer, ctypes.byref(info), DIB_RGB_COLORS
            )

            if not copied:
                raise OSError("не удалось получить пиксели снимка")

            raw = buffer.raw
            # В DIB порядок байтов BGR(A) — приводим к привычному RGB.
            return [
                (raw[index + 2], raw[index + 1], raw[index])
                for index in range(0, len(raw), 4)
            ]
        finally:
            gdi.SelectObject(memory, previous)
    finally:
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        user.ReleaseDC(None, screen)


def _sample_row(x: int, y: int, width: int) -> Tuple[int, List[Tuple[int, int, int]]]:
    """Срез снимка вдоль строки: (координата первого пикселя, цвета)."""
    return x, _screen_colors(x, y, width, 1)


def _sample_column(x: int, y: int, height: int) -> Tuple[int, List[Tuple[int, int, int]]]:
    """Срез снимка вдоль столбца: (координата первого пикселя, цвета)."""
    return y, _screen_colors(x, y, 1, height)


def _enable_dpi_awareness() -> None:
    """Согласованность координат на масштабированных дисплеях (125 %, 150 %).

    Процесс ZERE может быть DPI-unaware, тогда GetClientRect/ClientToScreen
    возвращают виртуализированные координаты, а курсор живёт в физических —
    холст схлопывается и вместо фигуры получается точка. Переключаем
    awareness для текущего потока: остальной процесс не затрагивается.

    Если не получилось — не беда: на 100 % масштабе координаты совпадают,
    и рисование работает как раньше.
    """
    handle = _get_user32()

    set_thread = getattr(handle, "SetThreadDpiAwarenessContext", None)
    if set_thread is not None:
        try:
            if set_thread(ctypes.c_void_p(DPI_AWARENESS_PER_MONITOR_V2)):
                return
        except OSError:
            pass

    set_process = getattr(handle, "SetProcessDPIAware", None)
    if set_process is not None:
        try:
            set_process()
        except OSError:
            pass


def _send_inputs(items: Sequence[_INPUT]) -> bool:
    """Отправляет пачку событий SendInput; False — если ОС их отклонила."""
    if not items:
        return True

    handle = _get_user32()
    array = (_INPUT * len(items))(*items)
    sent = handle.SendInput(len(items), array, ctypes.sizeof(_INPUT))

    return int(sent) == len(items)


def _mouse_event(flags: int, dx: int = 0, dy: int = 0) -> bool:
    """Событие мыши через SendInput.

    Для перемещения обязателен MOUSEEVENTF_MOVE|MOUSEEVENTF_ABSOLUTE: одного
    SetCursorPos недостаточно — движение курсора не попадает в очередь ввода
    окна как сообщение о перетаскивании, и вместо штриха выходит точка.
    """
    item = _INPUT(
        type=INPUT_MOUSE,
        u=_INPUTUNION(mi=_MOUSEINPUT(int(dx), int(dy), 0, flags, 0, None)),
    )
    return _send_inputs([item])


def _absolute_coords(dx: int, dy: int) -> Tuple[int, int]:
    """Экранные пиксели → абсолютные координаты SendInput (0..65535).

    Нормируется на виртуальный рабочий стол: иначе на нескольких мониторах
    курсор уезжает на основной.
    """
    handle = _get_user32()

    left = handle.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = handle.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = handle.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = handle.GetSystemMetrics(SM_CYVIRTUALSCREEN)

    if width <= 1 or height <= 1:
        return (0, 0)

    normalized_x = round((dx - left) * 65535 / (width - 1))
    normalized_y = round((dy - top) * 65535 / (height - 1))

    return (
        max(0, min(65535, int(normalized_x))),
        max(0, min(65535, int(normalized_y))),
    )


def _move_to(x: int, y: int) -> bool:
    """Ставит курсор в точку двумя способами: SetCursorPos + абсолютный MOVE.

    Дублирование намеренное: SetCursorPos двигает курсор, а событие MOVE
    попадает в очередь ввода окна — то, что нужно приложению при перетаскивании.
    False возвращается, если ОС отклонила событие: по нему видно, дошло ли
    рисование до окна (иначе ZERE рапортует об успехе при пустом холсте).
    """
    handle = _get_user32()
    handle.SetCursorPos(int(x), int(y))

    normalized_x, normalized_y = _absolute_coords(int(x), int(y))
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    return _mouse_event(flags, normalized_x, normalized_y)


def _key_event(vk: int, key_up: bool = False) -> bool:
    """Нажатие/отпускание клавиши по виртуальному коду."""
    flags = KEYEVENTF_KEYUP if key_up else 0
    item = _INPUT(
        type=INPUT_KEYBOARD,
        u=_INPUTUNION(ki=_KEYBDINPUT(vk, 0, flags, 0, None)),
    )
    return _send_inputs([item])


def _normalize_process_name(name: str) -> str:
    lowered = (name or "").strip().lower()
    return lowered[:-4] if lowered.endswith(".exe") else lowered


def _process_name(pid: int) -> str:
    """Имя процесса по pid; psutil импортируется лениво (нет в Linux-тестах)."""
    try:
        import psutil
    except ImportError:
        return ""

    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


def _enum_windows() -> List[Tuple[int, str, str]]:
    """Видимые окна верхнего уровня: (hwnd, имя процесса, заголовок)."""
    from ctypes import wintypes

    handle = _get_user32()
    windows: List[Tuple[int, str, str]] = []

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    handle.EnumWindows.argtypes = (enum_proc, wintypes.LPARAM)
    handle.EnumWindows.restype = wintypes.BOOL

    def callback(hwnd, _lparam):
        if not handle.IsWindowVisible(hwnd):
            return True

        # Окна с владельцем — диалоги и всплывающие панели, не главное окно.
        if handle.GetWindow(hwnd, GW_OWNER):
            return True

        title_length = handle.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True

        buffer = ctypes.create_unicode_buffer(title_length + 1)
        handle.GetWindowTextW(hwnd, buffer, title_length + 1)

        pid = wintypes.DWORD()
        handle.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        windows.append(
            (_as_hwnd(hwnd), _process_name(pid.value), buffer.value)
        )
        return True

    handle.EnumWindows(enum_proc(callback), 0)

    return windows


#: Разделители в заголовках окон: «Безымянный — Paint», «Untitled - Krita».
_TITLE_SEPARATORS = (" - ", " — ", " – ", " | ", " · ")


def _title_matches(title: str, hints: Sequence[str]) -> bool:
    """Заголовок окна указывает именно на это приложение.

    Сравнение по сегментам, а не подстрокой: иначе вкладка браузера
    «Paint tutorial — Firefox» сошла бы за Paint и ZERE рисовал бы в браузере.
    """
    if not title:
        return False

    segments = [title]

    for separator in _TITLE_SEPARATORS:
        expanded: List[str] = []

        for segment in segments:
            expanded.extend(segment.split(separator))

        segments = expanded

    for segment in segments:
        cleaned = segment.strip().lower()

        for hint in hints:
            # Только точное совпадение сегмента: «Paint tutorial» — не Paint.
            if cleaned == hint.lower():
                return True

    return False


def _find_window(spec) -> Optional[int]:
    """Окно приложения: сначала по имени процесса, затем по заголовку.

    Заголовок — запасной признак: Store-версии и переименования процессов
    (Paint в Windows 11 — `PaintApp.exe`) иначе не находятся, и ZERE
    запускал бы приложение заново на каждую команду.
    """
    windows = _enum_windows()
    wanted = {_normalize_process_name(name) for name in spec.process_names}

    for hwnd, process_name, _title in windows:
        if _normalize_process_name(process_name) in wanted:
            return hwnd

    for hwnd, _process_value, title in windows:
        if _title_matches(title, spec.title_hints):
            return hwnd

    return None


def _launch(spec) -> bool:
    """Запускает приложение: сначала известные пути, потом PATH."""
    for template in spec.exe_candidates:
        path = Path(expand_template(template))

        if path.is_file():
            try:
                subprocess.Popen([str(path)], creationflags=_CREATE_NO_WINDOW)
                return True
            except OSError:
                continue

    for command in (shutil.which(spec.launch_command), spec.launch_command):
        if not command:
            continue

        try:
            subprocess.Popen([command], creationflags=_CREATE_NO_WINDOW)
            return True
        except OSError:
            continue

    return False


def _client_rect(hwnd: int) -> Tuple[int, int, int, int]:
    """Клиентская область окна в экранных координатах: x, y, ширина, высота."""
    from ctypes import wintypes

    handle = _get_user32()

    rect = wintypes.RECT()
    if not handle.GetClientRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Не удалось определить размер окна приложения.")

    origin = wintypes.POINT(0, 0)
    if not handle.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise RuntimeError("Не удалось определить положение окна приложения.")

    return (
        int(origin.x),
        int(origin.y),
        int(rect.right - rect.left),
        int(rect.bottom - rect.top),
    )


def _focus(hwnd: int) -> bool:
    """Разворачивает и делает окно активным, дожидаясь результата."""
    handle = _get_user32()

    handle.ShowWindow(hwnd, SW_RESTORE)

    for _ in range(FOCUS_ATTEMPTS):
        handle.SetForegroundWindow(hwnd)
        handle.BringWindowToTop(hwnd)

        if _as_hwnd(handle.GetForegroundWindow()) == _as_hwnd(hwnd):
            return True

        time.sleep(FOCUS_DELAY)

    return False


def is_canvas_usable(canvas: DrawingCanvas) -> bool:
    """Годится ли холст для рисования.

    Вырожденный холст (окно не измерилось, свёрнуто, отступы съели область)
    даёт не фигуру, а одну точку — при этом команда отрапортует об успехе.
    Лучше проверить заранее и сказать пользователю правду.
    """
    return canvas.width >= MIN_CANVAS_SIZE and canvas.height >= MIN_CANVAS_SIZE


class DrawingService:
    """Рисует фигуры и текст в текущем приложении-цели."""

    #: Русские названия фигур для ответа пользователю.
    _SHAPE_NAMES = {
        DrawingCommandType.DRAW_CIRCLE: "круг",
        DrawingCommandType.DRAW_ELLIPSE: "овал",
        DrawingCommandType.DRAW_RECTANGLE: "прямоугольник",
        DrawingCommandType.DRAW_SQUARE: "квадрат",
        DrawingCommandType.DRAW_TRIANGLE: "треугольник",
        DrawingCommandType.DRAW_LINE: "линию",
        DrawingCommandType.DRAW_STAR: "звезду",
    }

    def __init__(self, target: DrawingTarget = DEFAULT_TARGET) -> None:
        self._target = target

    @property
    def target(self) -> DrawingTarget:
        return self._target

    def set_target(self, target: DrawingTarget) -> None:
        self._target = target

    def execute(self, command: ParsedDrawingCommand) -> str:
        """Выполняет разобранную команду и возвращает ответ пользователю."""
        if command.type is DrawingCommandType.NONE:
            return "Команда рисования не распознана."

        if command.target is not None:
            self._target = command.target

        if command.type is DrawingCommandType.SET_TARGET:
            return f"Рисую в {display_name(self._target)}."

        try:
            return self._run(command)
        except RuntimeError as ex:
            return str(ex)
        except Exception as ex:  # noqa: BLE001 — рисование не должно ронять ассистента
            log_error("DrawingService", str(ex))
            return f"Не удалось нарисовать: {ex}"

    # ── Внутренняя работа ─────────────────────────────────────────

    def _run(self, command: ParsedDrawingCommand) -> str:
        spec = spec_for(self._target)

        # До любых измерений окна: иначе на масштабированных дисплеях
        # координаты виртуализируются и холст схлопывается в точку.
        _enable_dpi_awareness()

        hwnd = self._find_or_launch(spec)
        if hwnd is None:
            return (
                f"Не удалось найти или запустить {display_name(self._target)}. "
                f"Проверьте, что приложение установлено."
            )

        previous = _as_hwnd(_get_user32().GetForegroundWindow())

        if not _focus(hwnd):
            return f"Не удалось переключиться на окно {display_name(self._target)}."

        target_name = display_name(self._target)

        try:
            # Пауза: пользователь отпускает мышь, окно дорисовывается.
            time.sleep(PREPARE_DELAY)

            window_rect = _client_rect(hwnd)
            viewport = DrawingCanvas.from_client(*window_rect, insets=spec.insets)

            if command.type is DrawingCommandType.CLEAR_CANVAS:
                self._clear_canvas()
                return f"Очистил холст в {target_name}."

            # Холст — документ внутри окна, а не вся область рисования:
            # Paint игнорирует штрих, начатый вне изображения, поэтому фигура,
            # начатая на подложке, не появлялась вовсе (круг, квадрат).
            canvas = self._document_canvas(viewport) or viewport

            # Вырожденный холст — молчаливая точка вместо фигуры. Лучше отказать
            # и показать числа: по ним сразу видно, врёт ли определение окна.
            if not is_canvas_usable(canvas):
                log_error(
                    "DrawingService",
                    f"вырожденный холст {canvas.width}x{canvas.height} "
                    f"(окно {window_rect}, область {viewport.width}x{viewport.height})",
                )
                return (
                    f"Холст {target_name} оказался слишком мал "
                    f"({canvas.width}×{canvas.height} px). Разверните окно "
                    f"и увеличьте документ, затем повторите."
                )

            strokes = self._strokes_for(command, canvas)
            if not strokes:
                return "Не удалось построить рисунок."

            started = time.monotonic()
            moves = self._draw_strokes(canvas, strokes)
            elapsed = time.monotonic() - started

            # Диагностика в стиле [Perf]: по этой строке видно, дошло ли
            # рисование до окна, если фигура снова окажется точкой.
            print(
                f"[Drawing] {target_name}: окно={window_rect}, "
                f"холст={canvas.width}x{canvas.height}"
                f"{' (документ)' if canvas != viewport else ' (окно)'}, "
                f"штрихов={len(strokes)}, перемещений={moves}, "
                f"время={elapsed:.1f} с"
            )

            if moves == 0:
                log_error("DrawingService", "ни одного перемещения курсора")
                return (
                    f"Не удалось провести штрихи в {target_name}: "
                    f"курсор не переместился. Подробности — в консоли."
                )
        finally:
            if previous and previous != hwnd:
                _get_user32().SetForegroundWindow(previous)

        return self._describe(command)

    def _find_or_launch(self, spec) -> Optional[int]:
        hwnd = _find_window(spec)

        if hwnd is not None:
            return hwnd

        if not _launch(spec):
            return None

        deadline = time.monotonic() + WINDOW_WAIT_SECONDS

        while time.monotonic() < deadline:
            time.sleep(WINDOW_POLL_SECONDS)
            hwnd = _find_window(spec)

            if hwnd is not None:
                return hwnd

        return None

    def _document_canvas(self, viewport: DrawingCanvas) -> Optional[DrawingCanvas]:
        """Документ приложения внутри области рисования или None.

        Снимаем два среза экрана — центральную строку и центральный столбец
        области рисования: документ отличается от подложки вокруг него.
        Без этой проверки фигура начинается у края окна, а Paint игнорирует
        штрих, начатый вне изображения, — не рисуется ничего.
        """
        try:
            row = _sample_row(
                viewport.left + SAMPLE_MARGIN,
                viewport.top + viewport.height // 2,
                viewport.width - SAMPLE_MARGIN - SCROLLBAR_MARGIN,
            )
            column = _sample_column(
                viewport.left + viewport.width // 2,
                viewport.top + SAMPLE_MARGIN,
                viewport.height - SAMPLE_MARGIN - SCROLLBAR_MARGIN,
            )
        except (OSError, RuntimeError) as ex:
            log_error("DrawingService", f"снимок области рисования: {ex}")
            return None

        return document_canvas(viewport, row, column)

    def _strokes_for(
        self, command: ParsedDrawingCommand, canvas: DrawingCanvas
    ) -> List[Stroke]:
        command_type = command.type

        if command_type is DrawingCommandType.DRAW_CIRCLE:
            return circle()
        if command_type is DrawingCommandType.DRAW_ELLIPSE:
            return ellipse()
        if command_type is DrawingCommandType.DRAW_RECTANGLE:
            return rectangle()
        if command_type is DrawingCommandType.DRAW_SQUARE:
            return square()
        if command_type is DrawingCommandType.DRAW_TRIANGLE:
            return triangle()
        if command_type is DrawingCommandType.DRAW_LINE:
            return line()
        if command_type is DrawingCommandType.DRAW_STAR:
            return star()

        if command_type is DrawingCommandType.WRITE_TEXT:
            strokes, columns, rows = text_strokes(command.value)

            if not strokes:
                return []

            # Текст вписывается пропорционально: растр шрифта не совпадает
            # по аспекту с холстом окна.
            return fit_strokes(strokes, columns, rows, canvas.width, canvas.height)

        return []

    def _draw_strokes(self, canvas: DrawingCanvas, strokes: Sequence[Stroke]) -> int:
        """Проводит все штрихи; возвращает число доставленных перемещений.

        Считаем именно доставленные: SendInput возвращает 0, когда ОС отклонила
        событие (например, ввод заблокирован). Раньше число перемещений росло
        независимо от результата, и ZERE рапортовал «нарисовал», хотя курсор
        не сдвинулся.
        """
        moves = 0

        for stroke in strokes:
            points = [canvas.to_screen(x, y) for (x, y) in stroke]

            if not points:
                continue

            _move_to(*points[0])

            if not _mouse_event(MOUSEEVENTF_LEFTDOWN):
                log_error("DrawingService", "SendInput отклонил нажатие кнопки мыши")
                break

            for step in self._plan_moves(points):
                if _move_to(*step):
                    moves += 1

                if MOVE_DELAY:
                    time.sleep(MOVE_DELAY)

            _mouse_event(MOUSEEVENTF_LEFTUP)

            if STROKE_DELAY:
                time.sleep(STROKE_DELAY)

        return moves

    @classmethod
    def _plan_moves(cls, points: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """Точки перемещения по ломаной с потолком на количество.

        Шаг подбирается от длины штриха: длинная окружность разбивается
        крупнее, чтобы при паузе 10 мс рисование не длилось минуты.
        """
        if len(points) < 2:
            return []

        length = sum(
            math.hypot(end[0] - start[0], end[1] - start[1])
            for start, end in zip(points, points[1:])
        )
        step_pixels = max(STEP_PIXELS, length / MAX_POINTS_PER_STROKE)

        moves: List[Tuple[int, int]] = []

        for start, end in zip(points, points[1:]):
            moves.extend(cls._interpolate(start, end, step_pixels))

        return moves

    @staticmethod
    def _interpolate(start: Tuple[int, int],
                     end: Tuple[int, int],
                     step_pixels: float = STEP_PIXELS) -> List[Tuple[int, int]]:
        """Промежуточные точки отрезка: без них приложение «срежет» угол."""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        steps = max(1, int(math.hypot(dx, dy) / step_pixels))

        return [
            (round(start[0] + dx * index / steps), round(start[1] + dy * index / steps))
            for index in range(1, steps + 1)
        ]

    @staticmethod
    def _clear_canvas() -> None:
        """Ctrl+A и Delete — выделить всё и стереть.

        Клик по холсту намеренно не делается: в Paint и Krita клик кистью
        оставил бы точку. Если фокус оказался в доке, очистка не сработает —
        тогда достаточно кликнуть по холсту и повторить.
        """
        _key_event(VK_CONTROL)
        _key_event(VK_A)
        _key_event(VK_A, key_up=True)
        _key_event(VK_CONTROL, key_up=True)

        time.sleep(0.15)
        _key_event(VK_DELETE)
        _key_event(VK_DELETE, key_up=True)

    def _describe(self, command: ParsedDrawingCommand) -> str:
        target_name = display_name(self._target)

        if command.type is DrawingCommandType.WRITE_TEXT:
            return f"Написал «{command.value}» в {target_name}."

        shape = self._SHAPE_NAMES.get(command.type, "фигуру")

        return f"Нарисовал {shape} в {target_name}."
