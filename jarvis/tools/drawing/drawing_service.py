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

from jarvis.core.logging.log_service import log_error
from jarvis.tools.drawing.drawing_command_router import ParsedDrawingCommand
from jarvis.tools.drawing.drawing_command_type import DrawingCommandType
from jarvis.tools.drawing.drawing_font import text_strokes
from jarvis.tools.drawing.drawing_geometry import (
    DrawingCanvas,
    Stroke,
    circle,
    ellipse,
    fit_strokes,
    line,
    rectangle,
    square,
    star,
    triangle,
)
from jarvis.tools.drawing.drawing_target import (
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
STEP_DELAY = 0.002
# Пауза между штрихами: у текста их сотни, поэтому пауза небольшая.
STROKE_DELAY = 0.015

# ── Константы Win32 ───────────────────────────────────────────────

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

KEYEVENTF_KEYUP = 0x0002

SW_RESTORE = 9
GW_OWNER = 4

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


_user32 = None


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

    # Прототип EnumWindows задаётся в _find_window: там известен тип колбэка.

    _user32 = handle
    return handle


def _send_inputs(items: Sequence[_INPUT]) -> bool:
    """Отправляет пачку событий SendInput; False — если ОС их отклонила."""
    if not items:
        return True

    handle = _get_user32()
    array = (_INPUT * len(items))(*items)
    sent = handle.SendInput(len(items), array, ctypes.sizeof(_INPUT))

    return int(sent) == len(items)


def _mouse_event(flags: int) -> bool:
    """Событие мыши без смещения (курсор двигаем через SetCursorPos)."""
    item = _INPUT(
        type=INPUT_MOUSE,
        u=_INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, flags, 0, None)),
    )
    return _send_inputs([item])


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
    «Paint tutorial — Firefox» сошла бы за Paint и JARVIS рисовал бы в браузере.
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
    (Paint в Windows 11 — `PaintApp.exe`) иначе не находятся, и JARVIS
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

        hwnd = self._find_or_launch(spec)
        if hwnd is None:
            return (
                f"Не удалось найти или запустить {display_name(self._target)}. "
                f"Проверьте, что приложение установлено."
            )

        previous = _as_hwnd(_get_user32().GetForegroundWindow())

        if not _focus(hwnd):
            return f"Не удалось переключиться на окно {display_name(self._target)}."

        try:
            # Пауза: пользователь отпускает мышь, окно дорисовывается.
            time.sleep(PREPARE_DELAY)

            canvas = DrawingCanvas.from_client(
                *_client_rect(hwnd), insets=spec.insets
            )

            if command.type is DrawingCommandType.CLEAR_CANVAS:
                self._clear_canvas()
                return f"Очистил холст в {display_name(self._target)}."

            strokes = self._strokes_for(command, canvas)
            if not strokes:
                return "Не удалось построить рисунок."

            self._draw_strokes(canvas, strokes)
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

    def _draw_strokes(self, canvas: DrawingCanvas, strokes: Sequence[Stroke]) -> None:
        handle = _get_user32()

        for stroke in strokes:
            points = [canvas.to_screen(x, y) for (x, y) in stroke]

            if not points:
                continue

            handle.SetCursorPos(*points[0])
            _mouse_event(MOUSEEVENTF_LEFTDOWN)

            for start, end in zip(points, points[1:]):
                for step in self._interpolate(start, end):
                    handle.SetCursorPos(*step)

                    if STEP_DELAY:
                        time.sleep(STEP_DELAY)

            _mouse_event(MOUSEEVENTF_LEFTUP)

            if STROKE_DELAY:
                time.sleep(STROKE_DELAY)

    @staticmethod
    def _interpolate(start: Tuple[int, int],
                     end: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Промежуточные точки отрезка: без них приложение «срежет» угол."""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        steps = max(1, int(math.hypot(dx, dy) / STEP_PIXELS))

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
