"""Непрерывный голосовой режим для панели (POST /api/voice/mode).

Порт консольной ветки voiceMode (main.run_voice_mode) в ФОНОВЫЙ поток:
панель включает/выключает режим через API, поэтому цикл
«wake word → команда → engine → озвучка» не блокирует ни HTTP-потоки
сервера, ни консоль.

Семантика (зеркалит консоль):
- wake word включён → спящий режим, ждём ключевое слово, потом команду;
- wake word выключен → слушаем команду сразу (старый вариант);
- «выход»/«стоп» голосом — выключение режима;
- ошибка LLM/TTS не убивает цикл: пишем lastError и слушаем дальше;
- ошибка записи (микрофон занят/отключён, сбой PortAudio) тоже не убивает
  цикл: lastError + пауза, состояние возвращается к sleeping;
- выход из цикла always освобождает wake-детектор (disable_wake_word).

Отмена: threading.Event (аналог CancellationToken в C#); stop() дополнительно
гасит текущую озвучку, чтобы выключение не ждало конца ответа.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from zere.core.logging.log_service import log_error

# Фазы цикла — значение поле state в контракте VoiceModeState (openapi).
STATE_IDLE = "idle"
STATE_SLEEPING = "sleeping"
STATE_LISTENING = "listening"
STATE_PROCESSING = "processing"
STATE_SPEAKING = "speaking"
STATE_ERROR = "error"

_EXIT_WORDS = ("выход", "стоп", "exit")

# Пауза после пустого распознавания: микрофон молчит/ошибка — не крутим
# горячий цикл (иначе 100% CPU на повторных попытках записи).
_EMPTY_TRANSCRIPT_PAUSE = 0.3

# Пауза после сбоя захвата (микрофон занят/отключён, PortAudio -9997 и т.п.):
# режим остаётся включённым, но не долбит сломанное устройство в цикле.
_CAPTURE_ERROR_PAUSE = 0.5

# Сколько ждём остановки потока в stop(): запись с микрофона может быть
# длинной (VAD), поэтому джойн с таймаутом, а не навсегда.
_STOP_TIMEOUT = 2.0


class VoiceModeRunner:
    """Фоновый цикл голосового режима панели.

    process — вызываемая обработка команды (engine.process): панельная и
    консольная реплики идут в одну историю разговоров. runtime —
    RuntimeContext (или None): voice_mode=True, пока цикл жив, чтобы
    AIHandler отвечал коротко (этап 1, анализ S5).
    """

    def __init__(
        self,
        voice: Any,
        process: Callable[[str], str],
        runtime: Optional[Any] = None,
    ) -> None:
        self._voice = voice
        self._process = process
        self._runtime = runtime
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._state = STATE_IDLE
        self._last_utterance = ""
        self._last_answer = ""
        self._last_error: Optional[str] = None

    # ── Состояние (контракт VoiceModeState) ─────────────────────

    @property
    def available(self) -> bool:
        """STT готов — режим вообще можно включить."""
        return bool(getattr(self._voice, "is_voice_available", False))

    @property
    def enabled(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def status(self) -> dict[str, Any]:
        config = self._voice.config
        return {
            "enabled": self.enabled,
            "state": self._state,
            "available": self.available,
            "wakeWordEnabled": bool(getattr(config, "wake_word_enabled", False)),
            "wakeWord": str(getattr(config, "wake_word", "")),
            # Движок триггера: "onnx-kws" (своя модель) или "whisper" (VAD+STT).
            "wakeEngine": str(getattr(self._voice, "wake_engine_label", "") or ""),
            "lastUtterance": self._last_utterance,
            "lastAnswer": self._last_answer,
            "lastError": self._last_error,
        }

    # ── Управление ──────────────────────────────────────────────

    def start(self) -> bool:
        """Поднимает фоновый цикл. False — включить нельзя (STT недоступен).

        Повторный вызов при живом цикле идемпотентен (True).
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True

            if not self.available:
                return False

            self._cancel = threading.Event()
            self._last_error = None
            self._state = STATE_SLEEPING
            self._thread = threading.Thread(
                target=self._run,
                name="zere-voice-mode",
                daemon=True,
            )
            self._thread.start()

        return True

    def stop(self, timeout: float = _STOP_TIMEOUT) -> None:
        """Останавливает цикл и ждёт выхода (с таймаутом). Идемпотентен."""
        with self._lock:
            thread = self._thread
            cancel = self._cancel

        cancel.set()

        # Текущая озвучка не должна тянуть остановку (порт StopSpeaking).
        try:
            self._voice.stop_speaking()
        except Exception:  # noqa: BLE001 — остановка не должна падать
            pass

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

        if thread is None or not thread.is_alive():
            # Поток уже вышел (или его не было) — финализируем сами:
            # детектор мог остаться, если цикл не запускался.
            self._disable_wake_word()
            if self._state != STATE_ERROR:
                self._state = STATE_IDLE

    # ── Цикл ────────────────────────────────────────────────────

    def _run(self) -> None:
        cancel = self._cancel

        try:
            while not cancel.is_set():
                try:
                    text = self._capture(cancel)
                except Exception as ex:  # noqa: BLE001 — сбой микрофона/PortAudio
                    # Раньше здесь режим умирал в состоянии «error» навсегда
                    # (например «Invalid sample rate [PaErrorCode -9997]»).
                    # Теперь ошибка видна в lastError, а цикл продолжает
                    # слушать: устройство могли занять или переткнуть.
                    log_error("VoiceModeRunner", f"capture: {ex}")
                    self._last_error = str(ex)
                    self._set_state(STATE_SLEEPING)
                    cancel.wait(_CAPTURE_ERROR_PAUSE)
                    continue

                if cancel.is_set():
                    break

                if not text or not text.strip():
                    cancel.wait(_EMPTY_TRANSCRIPT_PAUSE)
                    continue

                command = text.strip()

                if command.lower() in _EXIT_WORDS:
                    # Пользователь выключил режим голосом — чистый выход.
                    break

                self._last_utterance = command
                self._set_state(STATE_PROCESSING)

                try:
                    # Флаг только на время голосовой реплики: AIHandler
                    # отвечает коротко (этап 1, S5), текстовый чат панели
                    # при этом не «подрезается».
                    if self._runtime is not None:
                        self._runtime.voice_mode = True
                    answer = str(self._process(command))
                except Exception as ex:  # noqa: BLE001 — цикл не должен падать
                    log_error("VoiceModeRunner", f"process: {ex}")
                    self._last_error = str(ex)
                    self._set_state(STATE_SLEEPING)
                    continue
                finally:
                    if self._runtime is not None:
                        self._runtime.voice_mode = False

                self._last_answer = answer
                self._set_state(STATE_SPEAKING)

                try:
                    self._voice.speak(answer)
                except Exception as ex:  # noqa: BLE001
                    log_error("VoiceModeRunner", f"speak: {ex}")
                    self._last_error = str(ex)

                self._set_state(STATE_SLEEPING)
        except Exception as ex:  # noqa: BLE001 — неожиданный сбой цикла
            log_error("VoiceModeRunner", str(ex))
            self._last_error = str(ex)
            self._set_state(STATE_ERROR)
        finally:
            self._disable_wake_word()

            # Остановили пользователем/«выходом» → idle; сбой уже помечен error.
            if self._state != STATE_ERROR:
                self._state = STATE_IDLE

    def _capture(self, cancel: threading.Event) -> str:
        """Одна попытка получить голосовую команду: wake word → команда
        или прямое прослушивание (без триггера)."""
        voice = self._voice
        config = voice.config

        if not bool(getattr(config, "wake_word_enabled", False)):
            self._set_state(STATE_LISTENING)
            return str(voice.listen() or "")

        self._set_state(STATE_SLEEPING)
        voice.enable_wake_word()

        while not cancel.is_set():
            detected = bool(voice.wait_for_wake_word(cancel))

            if cancel.is_set():
                return ""

            if not detected:
                # Ложный возврат/перезапуск детектора — ждём дальше.
                # Пауза нужна, чтобы не крутить горячий цикл.
                cancel.wait(0.2)
                continue

            self._set_state(STATE_LISTENING)
            return str(voice.listen_command() or "")

        return ""

    # ── Помощники ───────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        self._state = state

    def _disable_wake_word(self) -> None:
        try:
            self._voice.disable_wake_word()
        except Exception:  # noqa: BLE001 — детектор мог быть уже закрыт
            pass
