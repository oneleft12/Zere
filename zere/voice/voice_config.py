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

    # Движок синтеза речи: "chattts" (китайский/английский, «человечный»
    # тембр) или "silero" (русский, с ударениями и омографами). Значение
    # приходит из config.json (ttsEngine) в main.py, паритет с VoiceConfig.cs
    # (в C# есть ещё "pocket" — клонирование голоса).
    tts_engine: str = "chattts"

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

    # ── Движок слова-триггера (анализ S2: VAD+STT → keyword spotting) ──
    # "auto" — KWS-модель (ZERE.Voice/WakeWord/models/wake_<слово>.onnx),
    # если она есть и установлен onnxruntime; иначе прежний детектор на STT;
    # "kws" — только KWS (нет модели → предупреждение и откат на STT);
    # "whisper" — прежний детектор: VAD + полный STT + нечёткое сравнение.
    wake_engine: str = "auto"

    # Явный путь к ONNX-модели (пусто — папка моделей по слову-триггеру).
    wake_model_path: str = ""

    # Порог вероятности, число кадров подряд и cooldown. 0 — значения из
    # манифеста модели: их подбирает tools/wake_word/evaluate.py по метрике
    # «FA/час при recall ≥ 97 %».
    wake_threshold: float = 0.0
    wake_min_consecutive: int = 0
    wake_cooldown_ms: int = 0

    # Энергетическая отсечка тишины: пока RMS последних 300 мс ниже порога,
    # модель не запускается вовсе (в тихой комнате — ноль работы).
    wake_energy_gate: bool = True
    wake_gate_rms: float = 0.0015
