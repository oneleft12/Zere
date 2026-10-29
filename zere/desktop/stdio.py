"""Стандартный вывод приложения без консоли.

`zere.exe` запускает Python через `pythonw.exe`: у такого процесса
`sys.stdout` и `sys.stderr` — `None` (проверено: `print()` молча ничего не
делает, а `sys.stdout.flush()` падает с `AttributeError`). Весь код ZERE
печатает в консоль (старт, панель, голос), поэтому без подмены потоков
диагностика запуска просто исчезает, а любой `flush()` роняет старт.

Поэтому в desktop-режиме потоки, которых нет, уводятся в
`logs/desktop.log`. Если консоль есть (запуск из терминала, `--console`),
ничего не меняется — вывод остаётся на экране.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, TextIO

__all__ = ["ensure_std_streams"]


def _works(stream: Optional[TextIO]) -> bool:
    """Можно ли писать в поток (None и мёртвые handle — нет)."""
    if stream is None:
        return False

    try:
        stream.write("")
        stream.flush()
        return True
    except Exception:  # noqa: BLE001 — закрытый/невалидный handle не считается рабочим
        return False


def ensure_std_streams(log_path: Path) -> Optional[Path]:
    """Уводит stdout/stderr в `log_path`, если их нет у процесса.

    Возвращает путь журнала, если подмена включилась, иначе `None` (консоль
    на месте). Оба потока получают один файл: порядок строк в журнале тогда
    совпадает с порядком вывода, а не теряется между двумя буферами.
    """
    if _works(sys.stdout) and _works(sys.stderr):
        return None

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    stream = open(path, "a", encoding="utf-8", errors="replace", buffering=1)

    # None → файл; мёртвый handle → тоже файл (иначе print падает на нём).
    if not _works(sys.stdout):
        sys.stdout = stream
    if not _works(sys.stderr):
        sys.stderr = stream

    return path
