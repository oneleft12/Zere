"""Детекторы слова-триггера ZERE.

Два движка за одним интерфейсом (`recorder`, `wait_for_wake_word(event)`,
`close()`):

- `KwsWakeWordDetector` — стриминговый keyword spotting на крошечной
  ONNX-модели под одно слово (основной путь, см. `kws_detector.py`);
- `WakeWordDetector` — прежняя логика: энергетический VAD + полный STT и
  нечёткое сравнение строк (остаётся откатом и способом сменить слово
  без обучения модели).

Выбор — в `create_wake_detector()` по `config.wake_engine`.
"""

from __future__ import annotations

from typing import Optional, Union

from zere.voice.voice_config import VoiceConfig
from zere.voice.wakeword.kws_detector import (
    KwsWakeWordDetector,
    onnx_available,
    resolve_model_path,
)
from zere.voice.wakeword.wake_word_detector import WakeWordDetector

WakeDetector = Union[KwsWakeWordDetector, WakeWordDetector]


def detect_wake_engine(config: VoiceConfig) -> str:
    """Имя движка, который выберет фабрика — без создания детектора.

    Нужно статусу панели (`wakeEngine`), чтобы показать «kws» или «whisper»
    ещё до первого ожидания слова.
    """
    engine = str(getattr(config, "wake_engine", "auto") or "auto").strip().lower()

    if engine == "whisper":
        return "whisper"

    if resolve_model_path(config) is not None and onnx_available():
        return KwsWakeWordDetector.ENGINE_NAME

    return "whisper"


def create_wake_detector(
    config: VoiceConfig,
    whisper: Optional[object] = None,
) -> WakeDetector:
    """Создаёт детектор слова-триггера по `config.wake_engine`.

    - `auto` (дефолт): KWS, если есть модель и onnxruntime; иначе прежний
      детектор на STT;
    - `kws`: только KWS. Если модели/onnxruntime нет — предупреждение и
      откат на STT: голосовой режим не должен ломаться из-за отсутствия
      файла модели (установка без обученной модели — нормальный случай);
    - `whisper`: всегда прежний детектор (смена слова без обучения).
    """
    engine = str(getattr(config, "wake_engine", "auto") or "auto").strip().lower()

    if engine == "whisper":
        return WakeWordDetector(config, whisper=whisper)  # type: ignore[arg-type]

    model_path = resolve_model_path(config)

    if model_path is None:
        print(
            "⚠️ Модель wake word не найдена "
            f"({config.wake_word!r}) — работаю на прежнем детекторе (STT). "
            "Обучить модель: python -m tools.wake_word.train"
        )
        return WakeWordDetector(config, whisper=whisper)  # type: ignore[arg-type]

    if not onnx_available():
        print(
            "⚠️ onnxruntime не установлен (pip install onnxruntime) — "
            "работаю на прежнем детекторе (STT)."
        )
        return WakeWordDetector(config, whisper=whisper)  # type: ignore[arg-type]

    try:
        detector = KwsWakeWordDetector(config, model_path=model_path)

        # Прогрев создаёт ONNX-сессию: битая или несовместимая модель не должна
        # оставить голосовой режим без слова-триггера вообще (warmup() не бросает).
        detector.warmup()

        if not detector.is_ready:
            detector.close()
            print("⚠️ KWS-модель не загрузилась — откат на STT-детектор.")
            return WakeWordDetector(config, whisper=whisper)  # type: ignore[arg-type]

        if engine == "kws":
            print(f"[Voice] Wake word: KWS-модель {model_path.name}")

        return detector
    except Exception as ex:  # noqa: BLE001 — битая модель не должна ломать голос
        print(f"⚠️ KWS-детектор не запустился ({ex}) — откат на STT-детектор.")
        return WakeWordDetector(config, whisper=whisper)  # type: ignore[arg-type]


__all__ = [
    "KwsWakeWordDetector",
    "WakeDetector",
    "WakeWordDetector",
    "create_wake_detector",
    "detect_wake_engine",
    "onnx_available",
    "resolve_model_path",
]
