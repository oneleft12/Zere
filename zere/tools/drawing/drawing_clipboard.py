"""Буфер обмена Windows: кладём картинку, чтобы вставить её одним Ctrl+V.

Именно так картинка попадает в Paint без единого движения курсора: ZERE
рисует изображение сам, кладёт его в буфер в трёх форматах (современный DIB с
прозрачностью, простой DIB и PNG) и отправляет в окно одно нажатие Ctrl+V.

Windows-вызовы создаются лениво: на других системах модуль импортируется, а
попытка положить картинку честно сообщает об отказе.
"""

from __future__ import annotations

import ctypes
import sys
from typing import List, Tuple

from zere.tools.drawing.drawing_canvas import dib_legacy, dib_v5, png_bytes

#: Форматы буфера обмена Windows.
CF_DIB = 8
CF_DIBV5 = 17
#: Имя формата PNG: регистрируется системой и совпадает у всех программ.
PNG_FORMAT_NAME = "PNG"

GMEM_MOVEABLE = 0x0002

_user32 = None
_kernel32 = None


def _get_win32():
    """Дескрипторы user32/kernel32 с обязательными прототипами."""
    global _user32, _kernel32

    if _user32 is not None and _kernel32 is not None:
        return _user32, _kernel32

    if sys.platform != "win32":
        raise RuntimeError("Буфер обмена с картинкой доступен только в Windows.")

    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.OpenClipboard.restype = wintypes.BOOL

    user32.EmptyClipboard.argtypes = ()
    user32.EmptyClipboard.restype = wintypes.BOOL

    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    user32.SetClipboardData.restype = wintypes.HANDLE

    user32.CloseClipboard.argtypes = ()
    user32.CloseClipboard.restype = wintypes.BOOL

    user32.RegisterClipboardFormatW.argtypes = (wintypes.LPCWSTR,)
    user32.RegisterClipboardFormatW.restype = wintypes.UINT

    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL

    kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalLock.restype = ctypes.c_void_p

    kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    _user32, _kernel32 = user32, kernel32
    return user32, kernel32


def png_clipboard_format() -> int:
    """Номер формата «PNG» в системе (регистрируется при первом обращении)."""
    user32, _kernel32 = _get_win32()

    return int(user32.RegisterClipboardFormatW(PNG_FORMAT_NAME))


def clipboard_formats(image, png_format: int) -> List[Tuple[int, bytes]]:
    """Что именно кладём в буфер: от современного формата к простому.

    Порядок не важен (программа сама выбирает удобный формат), но набор
    важен: Paint (WinUI) берёт PNG или DIB с прозрачностью, а старые
    программы — обычный DIB, наложенный на белый фон. Номер формата PNG
    передаётся снаружи: его выдаёт Windows, а разбор содержимого от системы
    не зависит.
    """
    return [
        (CF_DIBV5, dib_v5(image)),
        (int(png_format), png_bytes(image)),
        (CF_DIB, dib_legacy(image)),
    ]


def set_image(image) -> bool:
    """Кладёт картинку в буфер обмена; False — если Windows не дала буфер.

    Память под данные выделяется через GlobalAlloc: после успешного
    SetClipboardData её владельцем становится система, освобождать нельзя.
    """
    user32, kernel32 = _get_win32()
    entries = clipboard_formats(image, png_clipboard_format())

    if not user32.OpenClipboard(None):
        return False

    try:
        if not user32.EmptyClipboard():
            return False

        for clipboard_format, data in entries:
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))

            if not handle:
                continue

            pointer = kernel32.GlobalLock(handle)

            if not pointer:
                kernel32.GlobalFree(handle)
                continue

            try:
                ctypes.memmove(pointer, data, len(data))
            finally:
                kernel32.GlobalUnlock(handle)

            if not user32.SetClipboardData(clipboard_format, handle):
                kernel32.GlobalFree(handle)
    finally:
        user32.CloseClipboard()

    return True
