"""Порт ZERE.Core/Configuration/ZereConfig.cs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from zere import paths


def _norm(key: str) -> str:
    """Нормализация ключа: case-insensitive + underscore-insensitive.

    Эквивалент PropertyNameCaseInsensitive в System.Text.Json:
    'assistantName' (JSON) == 'AssistantName' (C#) == 'assistant_name' (Python).
    """
    return key.replace("_", "").lower()


def _camel(key: str) -> str:
    """snake_case → camelCase.

    Обе реализации пишут config.json в camelCase (как в существующем
    файле): C# читает case-insensitive, Python — с нормализацией,
    поэтому формат записи обязателен для взаимной читаемости.
    """
    parts = key.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


@dataclass
class ZereConfig:
    version: str = "1.8.0"
    assistant_name: str = "ZERE"
    language: str = "ru"
    # Русский — обязательное требование: по умолчанию берём русско-ориентированную
    # модель (T-lite 2.1), а не самую маленькую (см. docs/LOCAL_MODELS_RESEARCH.md).
    model: str = "t-tech/T-lite-it-2.1:q4_K_M"

    voice_enabled: bool = False
    # Громкость голосового вывода 0.0–1.0 (паритет с C# ZereConfig.VoiceVolume;
    # применяется к VoiceConfig.Volume в main.py).
    voice_volume: float = 0.5
    auto_memory: bool = True
    ollama_timeout_minutes: int = 10

    # --- LLM (Ollama) — параметры скорости/стабильности (паритет с C#) ---
    # keep_alive в секундах: -1 — модель остаётся в памяти Ollama
    # бессрочно (иначе после 5 мин простоя следующий запрос платит
    # загрузку +2…5 с, анализ S5).
    llm_keep_alive: int = -1
    # Лимит ответа в токенах в ГОЛОСОВОМ режиме (96 ≈ 1–2 предложения;
    # текстовый режим лимит не применяется).
    llm_max_tokens: int = 96
    # Таймаут запроса к Ollama в секундах: для голоса прежние 10 минут
    # недопустимы (пользователь молча ждёт, анализ S5).
    llm_timeout_seconds: int = 60

    # --- TTS (паритет с C# ZereConfig) -------------------
    # Движок озвучки: "pocket" — xVibePocketTTS (клонирование голоса),
    # "chattts" — ChatTTS (нейросетевой синтез, замена Piper). У Python-порта
    # PocketTTS нет, поэтому при любом значении фактически работает ChatTTS
    # (эквивалент отката pocket→chattts из C#-версии).
    tts_engine: str = "pocket"

    # --- STT (паритет с C# ZereConfig, отчёт docs/STT_ENGINE_RESEARCH.md) ---
    # Движок распознавания речи: "gigaam" — GigaAM-v3 punct (sherpa-onnx,
    # основной; модель качается установщиком или при первой предзагрузке),
    # "whisper" — откат на Whisper. При сбое gigaam всегда откат на whisper
    # (зеркало отката TTS-движков).
    stt_engine: str = "gigaam"

    # Путь к WAV-референсу голоса пользователя (пусто = встроенный голос).
    voice_reference_path: str = ""

    # --- Wake word (паритет с C# ZereConfig) -------------
    # Движок слова-триггера: "auto" — стриминговый KWS на своей ONNX-модели
    # (ZERE.Voice/WakeWord/models/wake_<слово>.onnx), если она есть, иначе
    # прежний детектор на VAD + STT; "kws" — только KWS; "whisper" — прежний
    # детектор (смена слова без обучения модели). Подробности: docs/WAKE_WORD.md.
    wake_engine: str = "auto"
    wake_model_path: str = ""
    # 0 — значения из манифеста модели (их подобрал tools/wake_word/evaluate.py).
    wake_threshold: float = 0.0
    wake_min_consecutive: int = 0
    wake_cooldown_ms: int = 0
    wake_energy_gate: bool = True

    # DSP-обработка озвучки ChatTTS (EQ + мягкий компрессор + нормализация),
    # паритет с C# ZereConfig.AudioProcessing. Ключ config.json:
    # audioProcessing. Читается на каждое предложение (VoiceManager), поэтому
    # переключается из панели на лету; false — «сырой» выход TTS.
    audio_processing: bool = True

    # --- Совместимость с C#-стилем обращений (Version, AssistantName, ...) ---
    _PASCAL_ALIASES = {
        "Version": "version",
        "AssistantName": "assistant_name",
        "Language": "language",
        "Model": "model",
        "VoiceEnabled": "voice_enabled",
        "VoiceVolume": "voice_volume",
        "AutoMemory": "auto_memory",
        "OllamaTimeoutMinutes": "ollama_timeout_minutes",
        "TtsEngine": "tts_engine",
        "SttEngine": "stt_engine",
        "WakeEngine": "wake_engine",
        "WakeModelPath": "wake_model_path",
        "WakeThreshold": "wake_threshold",
        "WakeMinConsecutive": "wake_min_consecutive",
        "WakeCooldownMs": "wake_cooldown_ms",
        "WakeEnergyGate": "wake_energy_gate",
        "VoiceReferencePath": "voice_reference_path",
        "AudioProcessing": "audio_processing",
        "LlmKeepAlive": "llm_keep_alive",
        "LlmMaxTokens": "llm_max_tokens",
        "LlmTimeoutSeconds": "llm_timeout_seconds",
    }

    def __getattr__(self, name: str) -> Any:
        target = self._PASCAL_ALIASES.get(name)
        if target is not None:
            return getattr(self, target)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    @classmethod
    def config_path(cls) -> Path:
        return paths.config_path()

    def to_camel_dict(self) -> dict[str, Any]:
        """Словарь конфигурации с ключами формата config.json (camelCase)."""
        return {_camel(k): v for k, v in asdict(self).items()}

    def save(self) -> None:
        """Атомарное сохранение: запись во временный файл + rename."""
        config_path = paths.config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = config_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self.to_camel_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(config_path)

    @classmethod
    def load(cls) -> "ZereConfig":
        config_path = paths.config_path()

        config_dir = config_path.parent
        if config_dir is not None:
            config_dir.mkdir(parents=True, exist_ok=True)

        if not config_path.exists():
            config = cls()
            config.save()
            return config

        text = config_path.read_text(encoding="utf-8")

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return cls()

        if not isinstance(data, dict):
            return cls()

        # PropertyNameCaseInsensitive — как в System.Text.Json
        norm_map = {_norm(f.name): f.name for f in fields(cls)}

        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            target = norm_map.get(_norm(str(key)))
            if target is None:
                continue
            kwargs[target] = value

        try:
            return cls(**kwargs)
        except TypeError:
            return cls()
