"""Порт JARVIS.Core/Logging/LogService.cs."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from jarvis import paths


class LogService:
    def __init__(self) -> None:
        folder: Path = paths.logs_dir()
        folder.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._log_path: Path = folder / f"jarvis_{timestamp}.log"
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

    def _write(self, level: str, message: str) -> None:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {message}"

        with self._lock:
            with open(self._log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
