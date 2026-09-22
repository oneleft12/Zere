"""Порт JARVIS.Core/Configuration/JarvisConfig.cs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from jarvis import paths


def _norm(key: str) -> str:
    """Нормализация ключа: case-insensitive + underscore-insensitive.

    Эквивалент PropertyNameCaseInsensitive в System.Text.Json:
    'assistantName' (JSON) == 'AssistantName' (C#) == 'assistant_name' (Python).
    """
    return key.replace("_", "").lower()


@dataclass
class JarvisConfig:
    version: str = "1.7.0"
    assistant_name: str = "JARVIS"
    language: str = "ru"
    model: str = "qwen3.5:2b"

    voice_enabled: bool = False
    # Громкость голосового вывода 0.0–1.0 (расширение Python-версии;
    # C# имел жёсткий дефолт 1.0, DSP нормализует пик до −1.5 dBFS).
    voice_volume: float = 0.5
    auto_memory: bool = False
    debug_mode: bool = False
    ollama_timeout_minutes: int = 10

    log_level: str = "Info"

    # --- Совместимость с C#-стилем обращений (Version, AssistantName, ...) ---
    _PASCAL_ALIASES = {
        "Version": "version",
        "AssistantName": "assistant_name",
        "Language": "language",
        "Model": "model",
        "VoiceEnabled": "voice_enabled",
        "VoiceVolume": "voice_volume",
        "AutoMemory": "auto_memory",
        "DebugMode": "debug_mode",
        "OllamaTimeoutMinutes": "ollama_timeout_minutes",
        "LogLevel": "log_level",
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

    @classmethod
    def load(cls) -> "JarvisConfig":
        config_path = paths.config_path()

        config_dir = config_path.parent
        if config_dir is not None:
            config_dir.mkdir(parents=True, exist_ok=True)

        if not config_path.exists():
            config = cls()
            json_text = json.dumps(
                asdict(config),
                indent=2,
                ensure_ascii=False,
            )
            config_path.write_text(json_text, encoding="utf-8")
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
