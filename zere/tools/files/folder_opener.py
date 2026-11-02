"""Открытие папки на экране: проводник Windows, Finder, файловый менеджер.

Отдельный маленький класс, а не `os.startfile` по месту вызова, потому что:

- на Linux (CI) `os.startfile` не существует, а тесты должны проверять
  именно вызов открытия, не запуская окно;
- ошибку открытия нужно вернуть текстом, а не исключением — панель и чат
  показывают её пользователю;
- путь не должен попадать в shell: только argv, без `shell=True`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable


class FolderOpener:
    """Открывает существующую папку системным файловым менеджером."""

    def __init__(
        self,
        *,
        system: str | None = None,
        startfile: Callable[[str], None] | None = None,
        spawn: Callable[..., object] | None = None,
    ) -> None:
        self._system = system or os.name
        self._startfile = startfile
        self._spawn = spawn or subprocess.Popen

    def open(self, path: str | Path) -> tuple[bool, str]:
        target = Path(path)

        try:
            if not target.is_dir():
                return False, f"Папка «{target}» не найдена."
        except (OSError, ValueError):
            return False, f"Папка «{target}» недоступна."

        try:
            if self._system == "nt":
                opener = self._startfile or getattr(os, "startfile", None)
                if opener is None:
                    return False, "Открытие папок не поддерживается на этой системе."
                opener(str(target))
            elif self._system == "darwin":
                self._spawn(["open", str(target)])
            else:
                self._spawn(["xdg-open", str(target)])
        except (OSError, ValueError) as ex:
            return False, f"Не удалось открыть папку «{target}»: {ex}"

        return True, f"Открываю папку «{target.name or target}»: {target}"
