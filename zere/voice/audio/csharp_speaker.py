"""Мост к C#-хелперу озвучки ZERE.Speaker (DSP + вывод через NAudio/WASAPI).

Зачем: озвучка — обработка звука (DSP) и вывод на устройство — выполняется
C#-кодом, а ядро, панель и распознавание остаются на Python. Хелпер
поднимается один раз в режиме `host` и общается строками JSON, поэтому старт
процесса и JIT не попадают в задержку каждой фразы (в отличие от запуска
процесса на каждое предложение).

Отказоустойчивость: если хелпер не собран, упал или не ответил, `speak()`
возвращает False — вызывающий код (VoiceManager) озвучивает сам через
sounddevice. Голос не должен пропадать из-за отсутствия C#-сборки.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Any, Optional

from zere import paths
from zere.core.logging.log_service import log_error

# Версия протокола хелпера (см. ZERE.Speaker/Program.cs)
PROTOCOL_VERSION = "1"

# Старт хелпера (JIT + инициализация NAudio) и запас к ожиданию ответа сверх
# длительности файла: DSP и вывод не должны обрываться по таймауту.
_START_TIMEOUT = 20.0
_REPLY_EXTRA_TIMEOUT = 30.0

# CreateNoWindow в C# (Windows-only; на других платформах — 0)
_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _wav_duration_seconds(wav_file: str) -> float:
    """Длительность WAV (для таймаута ожидания); 0 — если прочитать не удалось."""
    try:
        with wave.open(str(wav_file), "rb") as reader:
            rate = reader.getframerate() or 1
            return reader.getnframes() / float(rate)
    except Exception:  # noqa: BLE001 — битый/чужой файл: считаем нулевой
        return 0.0


def speaker_disabled() -> bool:
    """Отключён ли C#-хелпер (ZERE_SPEAKER=python — озвучка на Python)."""
    return os.environ.get("ZERE_SPEAKER", "").strip().lower() in ("python", "off", "0")


class CSharpSpeaker:
    """Долгоживущий C#-процесс озвучки: `speak` блокирует до конца звучания."""

    def __init__(self, command: Optional[list[str]] = None) -> None:
        # command — своя команда запуска (тесты вместо exe); None — искать exe.
        self._command = command
        self._process: Optional[subprocess.Popen[str]] = None
        self._reader: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._reply_event = threading.Event()
        self._reply: Optional[dict[str, Any]] = None
        self._ready_event = threading.Event()
        self._unavailable = False
        self._closing = False

    # ── Доступность ──────────────────────────────────────────

    def executable(self) -> Optional[str]:
        """Команда запуска хелпера или None, если он не собран/отключён."""
        if speaker_disabled():
            return None

        if self._command:
            return self._command[0]

        return paths.speaker_executable()

    def available(self) -> bool:
        """Готов ли хелпер (уже запущен, либо есть что запускать)."""
        if self._unavailable:
            return False

        with self._state_lock:
            if self._process is not None and self._process.poll() is None:
                return True

        return self.executable() is not None

    # ── Озвучка ──────────────────────────────────────────────

    def speak(
        self,
        wav_file: str,
        *,
        volume: float = 1.0,
        process: bool = True,
        rate: int = 44100,
    ) -> bool:
        """Просит хелпер обработать и проиграть WAV. True — звук отыгран.

        Блокирует до конца воспроизведения (как AudioPlayer.PlayAsync в C#),
        поэтому вызывающий код сохраняет прежнюю семантику.
        """
        if not wav_file or not Path(wav_file).is_file():
            return False

        if not self._ensure_started():
            return False

        request = {
            "cmd": "speak",
            "wav": str(wav_file),
            "volume": float(volume),
            "process": bool(process),
            "rate": int(rate),
        }

        duration = _wav_duration_seconds(wav_file)
        reply = self._exchange(request, timeout=duration + _REPLY_EXTRA_TIMEOUT)

        if reply is None:
            return False

        if reply.get("event") == "error":
            log_error("CSharpSpeaker", f"speak: {reply.get('message')}")
            return False

        # «stopped» — пользователь оборвал озвучку: это не ошибка.
        return reply.get("event") in ("done", "stopped")

    def stop(self) -> None:
        """Обрывает текущую озвучку (StopSpeaking, бардж-ин)."""
        with self._state_lock:
            process = self._process

        if process is None or process.poll() is not None:
            return

        try:
            self._write({"cmd": "stop"})
        except OSError as ex:  # noqa: PERF203 — канал мог закрыться
            log_error("CSharpSpeaker", f"stop: {ex}")

    def close(self) -> None:
        """Гасит хелпер (quit, затем terminate при необходимости)."""
        with self._state_lock:
            process = self._process
            self._process = None
            self._closing = True

        if process is None:
            return

        try:
            if process.poll() is None:
                self._write({"cmd": "quit"})
                process.wait(timeout=3.0)
        except Exception:  # noqa: BLE001 — гасим любой ценой
            pass

        if process.poll() is None:
            try:
                process.kill()
            except Exception:  # noqa: BLE001 — процесс уже мог выйти
                pass

        try:
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()
        except Exception:  # noqa: BLE001 — потоки закрываются ОС
            pass

        self._reader = None

    def __enter__(self) -> "CSharpSpeaker":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── Процесс и протокол ───────────────────────────────────

    def _ensure_started(self) -> bool:
        """Запускает хелпер (один раз) и дожидается его готовности."""
        with self._state_lock:
            if self._unavailable:
                return False

            if self._process is not None and self._process.poll() is None:
                return True

            executable = self.executable()

            if executable is None:
                return False

            command = self._command or [executable]

            try:
                self._process = subprocess.Popen(
                    [*command, "host"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    cwd=str(paths.PROJECT_ROOT),
                    creationflags=_CREATIONFLAGS,
                )
            except OSError as ex:
                # Хелпер не запускается (нет бинарника/прав) — озвучим сами.
                log_error("CSharpSpeaker", f"запуск хелпера: {ex}")
                self._unavailable = True
                return False

            self._ready_event.clear()
            self._reader = threading.Thread(
                target=self._read_replies,
                args=(self._process,),
                name="zere-csharp-speaker",
                daemon=True,
            )
            self._reader.start()

        if not self._ready_event.wait(_START_TIMEOUT):
            log_error("CSharpSpeaker", "хелпер не сообщил о готовности — озвучка на Python")
            self._unavailable = True
            return False

        return True

    def _read_replies(self, process: subprocess.Popen[str]) -> None:
        """Читает JSON-строки хелпера и отдаёт их ожидающему запросу."""
        assert process.stdout is not None

        for line in process.stdout:
            line = line.strip()

            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # Диагностика хелпера идёт в stderr; сюда попадать не должна.
                log_error("CSharpSpeaker", f"не JSON от хелпера: {line[:200]}")
                continue

            if payload.get("event") == "ready":
                self._ready_event.set()
                continue

            # Неожиданный ответ (например «done» после stop) не теряем молча:
            # если никто не ждёт — просто игнорируем.
            if self._reply_event.is_set():
                continue

            self._reply = payload
            self._reply_event.set()

        # Процесс закрыл stdout — значит, вышел.
        with self._state_lock:
            if self._process is process:
                self._process = None

            # Упал сам (не по close()) — больше не пытаемся: следующие фразы
            # озвучит Python, а не будем поднимать процесс на каждую.
            if not self._closing:
                self._unavailable = True
                log_error("CSharpSpeaker", "хелпер завершился — озвучка на Python")

        self._reply_event.set()

    def _write(self, request: dict[str, Any]) -> None:
        with self._write_lock:
            process = self._process

            if process is None or process.stdin is None:
                raise OSError("хелпер не запущен")

            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()

    def _exchange(self, request: dict[str, Any], timeout: float) -> Optional[dict[str, Any]]:
        """Пишет запрос и ждёт ответ; None — если хелпер не ответил."""
        with self._state_lock:
            self._reply = None
            self._reply_event.clear()

        try:
            self._write(request)
        except OSError as ex:
            log_error("CSharpSpeaker", f"отправка команды: {ex}")
            self._unavailable = True
            return None

        started = time.monotonic()

        if not self._reply_event.wait(timeout):
            log_error(
                "CSharpSpeaker",
                f"нет ответа за {timeout:.1f} с — озвучка на Python",
            )
            return None

        with self._state_lock:
            reply = self._reply
            self._reply = None

        if reply is None:
            # Хелпер завершился, не ответив (краш) — дальше озвучиваем сами.
            log_error("CSharpSpeaker", "хелпер завершился без ответа")
            self._unavailable = True
            return None

        # Готовность приходит отдельным событием; остальное — ответ на запрос.
        if reply.get("event") == "ready":
            return self._exchange(request, max(0.1, timeout - (time.monotonic() - started)))

        return reply
