"""Тесты устойчивости фонового голосового режима (VoiceModeRunner).

Регрессия из панели («Режим голоса → Состояние режима: ошибка»):

    Error opening InputStream: Invalid sample rate [PaErrorCode -9997]

Сбой записи (панель. PortAudio, микрофон занят/отключён) выбрасывался из
`_capture`, попадал в общий `except` цикла — и режим умирал в состоянии
`error` навсегда: повторное включение не помогало, пока не перезапустишь
JARVIS. Теперь ошибка видна в `lastError`, а цикл продолжает слушать.

Запуск: python3 tests/test_voice_mode.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.core.console import configure_console_encoding  # noqa: E402
from jarvis.voice.voice_mode import (  # noqa: E402
    STATE_ERROR,
    STATE_IDLE,
    VoiceModeRunner,
)

# Текст ошибки PortAudio/sounddevice, с которой начинался разбор
SAMPLE_RATE_ERROR = (
    "Error opening InputStream: Invalid sample rate [PaErrorCode -9997]"
)


class PortAudioLikeError(Exception):
    """Аналог sounddevice.PortAudioError по тексту."""


class FlakyVoice:
    """Голосовой менеджер с управляемыми сбоями записи.

    fail_times — сколько первых `listen()` падают; wake_fail_times — сколько
    первых `wait_for_wake_word()` падают (путь wake word: именно там падал
    ContinuousAudioRecorder). Дальше отдаются utterances.
    """

    def __init__(
        self,
        utterances: list[str] | None = None,
        *,
        fail_times: int = 0,
        wake_fail_times: int = 0,
        wake_word_enabled: bool = False,
        speak_fail_times: int = 0,
    ) -> None:
        self.config = SimpleNamespace(
            wake_word_enabled=wake_word_enabled,
            wake_word="джарвис",
        )
        self.is_voice_available = True

        self._utterances = list(utterances or [])
        self._fail_times = fail_times
        self._wake_fail_times = wake_fail_times
        self._speak_fail_times = speak_fail_times

        self.listen_calls = 0
        self.wake_calls = 0
        self.spoken: list[str] = []
        self.wake_disabled = 0
        self.wake_armed = False

    def listen(self) -> str:
        self.listen_calls += 1

        if self.listen_calls <= self._fail_times:
            raise PortAudioLikeError(SAMPLE_RATE_ERROR)

        return self._utterances.pop(0) if self._utterances else ""

    def listen_command(self) -> str:
        return self._utterances.pop(0) if self._utterances else ""

    def speak(self, text: str) -> None:
        if self._speak_fail_times > 0:
            self._speak_fail_times -= 1
            raise PortAudioLikeError("Ошибка озвучки")

        self.spoken.append(text)

    def stop_speaking(self) -> None:
        pass

    def enable_wake_word(self) -> "FlakyVoice":
        self.wake_armed = True
        return self

    def disable_wake_word(self) -> None:
        self.wake_disabled += 1
        self.wake_armed = False

    def wait_for_wake_word(self, cancel_event: Any = None) -> bool:
        self.wake_calls += 1

        if self.wake_calls <= self._wake_fail_times:
            raise PortAudioLikeError(SAMPLE_RATE_ERROR)

        return True

    def close(self) -> None:
        pass


def wait_for(predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
    """Ждёт выполнения условия (фоновый поток не джойнится сам)."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)

    return False


def test_listen_failure_keeps_mode_alive() -> None:
    """Сбой записи не убивает режим: lastError + повторные попытки."""
    voice = FlakyVoice(["выход"], fail_times=3)
    runner = VoiceModeRunner(voice, lambda command: "не должно вызываться")

    assert runner.start() is True, "режим должен включаться (STT доступен)"

    try:
        # 3 сбоя подряд, затем успешная запись «выход» → цикл выходит сам.
        assert wait_for(lambda: voice.listen_calls >= 4 and not runner.enabled), (
            "цикл не пережил сбой записи (раньше умирал после первого)"
        )
    finally:
        runner.stop()

    status = runner.status()
    assert "PaErrorCode -9997" in str(status["lastError"]), (
        f"ошибка записи должна попадать в lastError, а не теряться: {status}"
    )
    assert status["state"] != STATE_ERROR, (
        "сбой микрофона — не «ошибка режима»: состояние должно вернуться в idle"
    )
    assert status["state"] == STATE_IDLE
    assert status["enabled"] is False
    assert voice.wake_disabled >= 1, "wake-детектор освобождается на выходе"


def test_wake_word_failure_keeps_mode_alive() -> None:
    """Тот же сбой на пути wake word (непрерывная запись → -9997)."""
    voice = FlakyVoice(
        ["команда", "выход"], wake_fail_times=1, wake_word_enabled=True
    )
    runner = VoiceModeRunner(voice, lambda command: f"ответ: {command}")

    assert runner.start() is True

    try:
        assert wait_for(lambda: voice.wake_calls >= 2 and not runner.enabled), (
            "после сбоя wait_for_wake_word режим должен продолжать слушать"
        )
    finally:
        runner.stop()

    status = runner.status()
    assert "PaErrorCode -9997" in str(status["lastError"])
    assert status["state"] == STATE_IDLE, "режим не должен оставаться в error"
    assert status["lastUtterance"] == "команда", "wake-путь должен дойти до команды"
    assert status["lastAnswer"] == "ответ: команда"
    assert voice.wake_armed is False, "детектор освобождён на выходе"


def test_speak_failure_keeps_mode_alive() -> None:
    """Сбой озвучки тоже не убивает цикл (ошибка видна, режим работает)."""
    voice = FlakyVoice(["привет", "выход"], speak_fail_times=1)
    runner = VoiceModeRunner(voice, lambda command: "ответ джарвиса")

    assert runner.start() is True

    try:
        assert wait_for(lambda: not runner.enabled and voice.listen_calls >= 2)
    finally:
        runner.stop()

    status = runner.status()
    assert status["lastError"] is not None and "озвучки" in status["lastError"]
    assert status["lastAnswer"] == "ответ джарвиса"
    assert status["state"] == STATE_IDLE


def test_stop_is_clean_without_errors() -> None:
    """Обычный сценарий без сбоев остаётся прежним: вывод «выход» → idle."""
    voice = FlakyVoice(["команда", "выход"])
    reached = []

    def process(command: str) -> str:
        reached.append(command)
        return f"ответ: {command}"

    runner = VoiceModeRunner(voice, process)

    assert runner.start() is True

    try:
        assert wait_for(lambda: not runner.enabled)
    finally:
        runner.stop()

    status = runner.status()
    assert reached == ["команда"], f"обработана не та команда: {reached}"
    assert status["lastError"] is None, "на happy-path ошибок быть не должно"
    assert status["lastUtterance"] == "команда"
    assert status["state"] == STATE_IDLE


def main() -> None:
    configure_console_encoding()

    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов голосового режима")


if __name__ == "__main__":
    sys.exit(main())
