"""Порт ZERE.Core/Logging/LogService.cs."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from zere import paths

# Общий замок для записи в постоянный errors.log (межпоточный, межмодульный)
_ERRORS_LOCK = threading.Lock()


def _errors_path() -> Path:
    """Постоянный файл ошибок logs/errors.log (ROADMAP 1.1)."""
    folder = paths.logs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "errors.log"


def log_error(source: str, message: str) -> None:
    """Дозапись ошибки в logs/errors.log из любого модуля (best-effort).

    Логирование не должно ронять рабочий процесс: любые сбои записи
    проглатываются.
    """
    try:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [ERROR] [{source}] {message}\n"
        with _ERRORS_LOCK:
            with open(_errors_path(), "a", encoding="utf-8") as errors_file:
                errors_file.write(line)
    except OSError:
        pass


class LogService:
    def __init__(self) -> None:
        folder: Path = paths.logs_dir()
        folder.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._log_path: Path = folder / f"zere_{timestamp}.log"
        self._lock = threading.Lock()

    @property
    def log_path(self) -> Path:
        return self._log_path

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def warning(self, message: str) -> None:
        self._write("WARN", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)
        # ERROR дублируется в постоянный errors.log между сессиями (ROADMAP 1.1)
        log_error("LogService", message)

    def _write(self, level: str, message: str) -> None:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {message}"

        with self._lock:
            with open(self._log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
