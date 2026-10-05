"""Цели рисования — Krita и Paint: как найти окно, запустить и где холст.

Отступы (`insets`) обрезают клиентскую область окна до области рисования:
лента Paint и доки Krita (кисти, слои) не должны попадать под курсор.
Значения в пикселях — они предсказуемее процентов при разном размере окна.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class DrawingTarget(Enum):
    """Приложение, в котором рисуем."""

    PAINT = "paint"
    KRITA = "krita"


@dataclass(frozen=True)
class TargetSpec:
    """Как найти, запустить и обрезать окно приложения."""

    # Имена процессов без .exe (сравнение без регистра).
    process_names: tuple[str, ...]
    # Подстроки заголовка окна — запасной поиск, если имя процесса не совпало
    # (Store-версии и переименования процессов).
    title_hints: tuple[str, ...]
    # Пути к исполняемому файлу; переменные окружения раскрываются.
    exe_candidates: tuple[str, ...]
    # Команда запуска, если путь не найден (ищется в PATH).
    launch_command: str
    # Отступы клиентской области до холста: слева, сверху, справа, снизу.
    insets: tuple[int, int, int, int]


# Paint: в Windows 11 это Store-приложение (процесс PaintApp.exe), которое
# запускается алиасом mspaint.exe; в Windows 10 — обычный mspaint.exe.
_SPECS: dict[DrawingTarget, TargetSpec] = {
    DrawingTarget.PAINT: TargetSpec(
        process_names=("mspaint", "paintapp", "paint"),
        title_hints=("paint",),
        exe_candidates=(
            r"%LOCALAPPDATA%\Microsoft\WindowsApps\mspaint.exe",
            r"%SystemRoot%\System32\mspaint.exe",
            r"%ProgramFiles%\Windows NT\Accessories\mspaint.exe",
        ),
        launch_command="mspaint",
        # Лента ~120 px сверху, строка состояния снизу, поля по краям.
        insets=(8, 132, 8, 32),
    ),
    DrawingTarget.KRITA: TargetSpec(
        process_names=("krita",),
        title_hints=("krita",),
        exe_candidates=(
            r"%ProgramFiles%\Krita (x64)\bin\krita.exe",
            r"%ProgramFiles%\Krita\bin\krita.exe",
            r"%ProgramFiles(x86)%\Krita (x64)\bin\krita.exe",
        ),
        launch_command="krita",
        # Слева панель инструментов, справа доки (кисти, слои, настройки).
        insets=(56, 12, 288, 12),
    ),
}

_DISPLAY_NAMES: dict[DrawingTarget, str] = {
    DrawingTarget.PAINT: "Paint",
    DrawingTarget.KRITA: "Krita",
}

# Paint есть на любой Windows — безопасная цель по умолчанию.
DEFAULT_TARGET = DrawingTarget.PAINT


def spec_for(target: DrawingTarget) -> TargetSpec:
    """Описание цели; неизвестная цель невозможна (Enum)."""
    return _SPECS[target]


def display_name(target: DrawingTarget) -> str:
    """Человекочитаемое имя приложения для ответа пользователю."""
    return _DISPLAY_NAMES.get(target, target.value)


def expand_template(path: str) -> str:
    """Раскрывает переменные окружения в шаблоне пути (%ProgramFiles% и т.п.)."""
    return os.path.expandvars(path)
