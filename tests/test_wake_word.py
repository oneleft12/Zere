"""Тесты слова-триггера «Зере» (WakeWordDetector).

Ребрендинг заменил имя ассистента, и слово-триггер обязан следовать за ним.
Здесь проверяется, что детектор ловит варианты «зере/зера/зерэ/зире/zere»,
игнорирует постороннюю речь и совпадает с C#-редакцией по набору ядер.

Микрофон не нужен: запись и Whisper подменяются заглушками, проверяется
только сопоставление текста.

Запуск: python3 tests/test_wake_word.py
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# audio_recorder тянет sounddevice (PortAudio) — на безголосых машинах
# (CI) достаточно заглушки, как в tests/test_stt_engine.py.
try:
    import sounddevice  # noqa: F401
except Exception:  # noqa: BLE001 — ImportError или OSError от PortAudio
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")


def _detector(**overrides: object):
    """Детектор без микрофона и без модели Whisper."""
    from zere.voice.voice_config import VoiceConfig
    from zere.voice.wakeword import wake_word_detector

    config = VoiceConfig(**overrides)  # type: ignore[arg-type]

    with mock.patch.object(wake_word_detector, "ContinuousAudioRecorder", mock.Mock()):
        return wake_word_detector.WakeWordDetector(config, whisper=mock.Mock())


def test_default_wake_word_is_zere() -> None:
    """Дефолт слова-триггера — «зере» в Python, C# и config.json."""
    from zere.voice.voice_config import VoiceConfig

    assert VoiceConfig().wake_word == "зере"

    cs = (ROOT / "ZERE.Voice" / "VoiceConfig.cs").read_text(encoding="utf-8")
    assert re.search(r'WakeWord\s*\{\s*get;\s*set;\s*\}\s*=\s*"зере"', cs), (
        "C#-дефолт слова-триггера не «зере»"
    )


def test_wake_word_variants_are_detected() -> None:
    """Точные варианты имени ловятся и в начале, и внутри фразы."""
    detector = _detector()

    for text in (
        "зере",
        "Зере, привет",
        "слушай зера",
        "эй зерэ",
        "зире, открой ютуб",
        "zere, включи музыку",
        "ЗЕРЕ",
    ):
        assert detector._is_wake_word(text) is True, f"не распознано: {text!r}"  # noqa: SLF001


def test_unrelated_speech_is_not_a_wake_word() -> None:
    """Посторонняя речь не должна будить ассистента."""
    detector = _detector()

    for text in (
        "",
        "привет",
        "сережа",
        "середина",
        "зрение",
        "озеро",
        "делай что хочешь",
        "jarvis",
    ):
        assert detector._is_wake_word(text) is False, f"ложное срабатывание: {text!r}"  # noqa: SLF001


def test_configured_wake_word_is_honoured() -> None:
    """Явно заданное слово-триггер работает так же, как дефолтное."""
    detector = _detector(wake_word="Зере")

    assert detector._is_wake_word("зере") is True  # noqa: SLF001
    assert detector._is_wake_word("привет") is False  # noqa: SLF001


def test_csharp_uses_same_cores_and_no_old_name() -> None:
    """C# и Python согласованы; старого имени «джарвис» в ядрах нет."""
    from zere.voice.wakeword.wake_word_detector import WakeWordDetector

    py_cores = set(WakeWordDetector.FUZZY_CORES)

    source = (ROOT / "ZERE.Voice" / "WakeWord" / "WakeWordDetector.cs").read_text(
        encoding="utf-8"
    )
    block = re.search(r"FuzzyCores\s*=\s*\{(?P<body>.*?)\}", source, re.S)
    assert block is not None, "в C# не найден список FuzzyCores"
    cs_cores = set(re.findall(r'"([^"]+)"', block.group("body")))

    assert py_cores == cs_cores, f"ядра расходятся: Python {py_cores}, C# {cs_cores}"
    assert "зере" in py_cores, "ядра не содержат нового имени"
    assert not any("джарвис" in core for core in py_cores), "осталось старое имя"


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов слова-триггера")


if __name__ == "__main__":
    sys.exit(main())
