"""Конфигуция голоса (порт JARVIS.Voice/VoiceConfig.cs)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VoiceConfig:
    """Настройки голосового ввода/вывода (1:1 со свойствами VoiceConfig.cs)."""

    enabled: bool = False

    language: str = "ru"

    # Модель Whisper для распознавания: "base" (142 MB) или "medium" (1.5 GB).
    # medium значительно точнее для русского языка.
    whisper_model: str = "medium"

    piper_voice: str = "ru_RU-ruslan-medium"

    microphone_index: int = 0

    volume: float = 1.0

    wake_word_enabled: bool = True

    wake_word: str = "джарвис"

    # Включить DSP-обработку голоса (EQ, компрессия, нормализация).
    # Делает звук более «кинематографичным».
    audio_processing: bool = True

    # Множитель скорости речи (1.0 = норма, меньше = быстрее, больше = медленнее).
    # 1.15 — медленная, уверенная подача для кинематографичного стиля.
    speech_speed: float = 1.15
