"""Порт ZERE.Core/Logging/LogService.cs."""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from zere import paths

# Общий замок для записи в постоянный errors.log (межпоточный, межмодульный)
_ERRORS_LOCK = threading.Lock()

# ── Защита секретов (задача «ключ облачной модели») ──────────────────
# Ключ API не должен попасть в логи ни при каких обстоятельствах, даже
# если он случайно окажется внутри текста исключения (requests кладёт URL
# и заголовки в сообщение об ошибке). Маскирование — на выходе лога,
# поэтому вызывающему коду не нужно об этом помнить.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Провайдерские форматы ключей: OpenAI, OpenRouter, Groq, Google, xAI
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"), "***"),
    # Шлюз OpenCode Go: `oc_sk_...` (провайдер `opencode-go`). Отдельный
    # шаблон обязателен: `\bsk-` его не ловит — в `oc_sk_` подчёркивание,
    # а не дефис, поэтому ключ уходил в logs/errors.log открытым текстом.
    # Класс символов с дефисом: реальные ключи его содержат, иначе
    # замаскировалась бы только голова, а хвост остался бы в логе.
    (re.compile(r"\boc_sk_[A-Za-z0-9_\-]{6,}"), "***"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{6,}"), "***"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{10,}"), "***"),
    (re.compile(r"\bxai-[A-Za-z0-9]{6,}"), "***"),
    # Authorization: Bearer <token>
    (re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{8,})"), r"\1***"),
    # JSON/JSON-подобное поле ключа: "apiKey": "секрет"
    (
        re.compile(r"(?i)([\"']?(?:api[_-]?key|apikey|authorization)[\"']?\s*[:=]\s*[\"'])([^\"']{8,})([\"'])"),
        r"\1***\3",
    ),
)


def redact_secrets(text: str) -> str:
    """Убирает секреты из строки перед записью в лог (best-effort)."""
    if not text:
        return text

    result = text
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


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
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [ERROR] [{source}] {redact_secrets(message)}\n"
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
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {redact_secrets(message)}"

        with self._lock:
            with open(self._log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
