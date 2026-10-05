"""Настройка консольного вывода (Windows cp866/cp1251 не умеет эмодзи).

Python печатает в **интерактивную** консоль Windows через wide-API (UTF-8),
поэтому эмодзи в принтах там работают. Но стоит перенаправить вывод
(`ZERE.bat > zere.log`, запуск из CI/другого процесса) — и Python берёт
кодовую страницу системы (cp866/cp1251). Любой принт с эмодзи тогда падает
`UnicodeEncodeError`, а он в аудио-пути выглядел как сбой микрофона:

    [Recorder] Ошибка записи: 'charmap' codec can't encode character '\\U0001f3a4'

Поэтому на входе в приложение непредставимые символы заменяются на «?»:
печать не падает и не маскирует настоящие ошибки.
"""

from __future__ import annotations

import sys
from typing import Any


def configure_console_encoding() -> None:
    """Разрешает замену непредставимых символов в stdout/stderr.

    Ничего не делает, если поток не поддерживает `reconfigure` (тестовые
    заглушки, перенаправление в объект без текстового слоя).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure: Any = getattr(stream, "reconfigure", None)

        if reconfigure is None:
            continue

        try:
            reconfigure(errors="replace")
        except Exception:  # noqa: BLE001 — поток без кодировки: печать и так работает
            pass
