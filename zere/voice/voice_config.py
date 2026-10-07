"""Конфигуция голоса (порт ZERE.Voice/VoiceConfig.cs)."""

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

    # Движок распознавания речи: "gigaam" — GigaAM-v3 punct (sherpa-onnx,
    # основной, MIT; отчёт docs/STT_ENGINE_RESEARCH.md), "whisper" — откат
    # на Whisper. Значение приходит из config.json (sttEngine) в main.py,
    # паритет с VoiceConfig.SttEngine в C#.
    stt_engine: str = "gigaam"

    # Профиль голоса ChatTTS. У ChatTTS нет именованных голосов: профиль —
    # это детерминированное зерно эмбеддинга говорящего (crc32 имени), поэтому
    # один профиль всегда звучит одинаково. См. zere/voice/chattts/.
    chattts_voice: str = "zere-standard"

    microphone_index: int = 0

    # Дефолт 0.5 (вместо 1.0 в C#): DSP нормализует пик до −1.5 dBFS, при
    # 1.0 звук «орёт» на полную. Значение переопределяется из config.json
    # (ключ voiceVolume) в main.py.
    volume: float = 0.5

    wake_word_enabled: bool = True

    wake_word: str = "зере"

    # Включить DSP-обработку голоса (EQ, компрессия, нормализация).
    # Делает звук более «кинематографичным».
    audio_processing: bool = True

    # Множитель скорости речи (1.0 = норма, меньше = быстрее, больше = медленнее).
    # 1.15 — медленная, уверенная подача для кинематографичного стиля.
    # ChatTTS задаёт темп токеном [speed_N] (дискретная шкала 1…9): 1.15 → 4.
    speech_speed: float = 1.15

    # Пауза (в секундах) после каждого предложения во время синтеза
    # (паритет с C# VoiceConfig.SentenceSilence): у ChatTTS — тишина,
    # дописываемая в WAV после каждого предложения.
    sentence_silence: float = 0.2

    # Пауза тишины (мс), после которой wake-детектор считает речь оконченной.
    # Было жёсткие 1200 мс — каждый цикл платил 1.2 с сверху (анализ S4);
    # 700 мс покрывает обычные межсловесные паузы и не рвёт фразу.
    wake_silence_ms: int = 700

    # Пауза тишины (мс) для окончания голосовой команды (было 1500 мс).
    command_silence_ms: int = 800
