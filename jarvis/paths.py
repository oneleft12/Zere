"""Единые пути к ресурсам проекта JARVIS (корень репозитория)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Корень репозитория: <Jarvis>/jarvis/paths.py -> parents[1]
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

CONFIG_DIR: Path = PROJECT_ROOT / "config"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
PLUGINS_DIR: Path = PROJECT_ROOT / "plugins"
VOICE_DIR: Path = PROJECT_ROOT / "JARVIS.Voice"
PUBLISH_DIR: Path = PROJECT_ROOT / "publish"


def config_path() -> Path:
    return CONFIG_DIR / "config.json"


def plugins_config_path() -> Path:
    return CONFIG_DIR / "plugins.json"


def db_path() -> Path:
    return PROJECT_ROOT / "jarvis.db"


def logs_dir() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def plugins_dir() -> Path:
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return PLUGINS_DIR


def voice_dir() -> Path:
    return VOICE_DIR


def piper_dir() -> Path:
    return VOICE_DIR / "Piper"


def whisper_models_dir() -> Path:
    return VOICE_DIR / "Models"


# ─── C#-хелпер озвучки (JARVIS.Speaker) ─────────────────────


def speaker_executable() -> Optional[str]:
    """Путь к собранному C#-хелперу озвучки или None, если он не собран.

    Порядок поиска: переменная окружения `JARVIS_SPEAKER_EXE` (отладка и
    тесты) → `publish/speaker` (так публикует установщик) → `publish/app`
    (рядом с C#-редакцией) → `bin/Release|Debug` (локальная сборка
    разработчика). Если ничего нет, Python-редакция озвучивает сама
    (sounddevice) — голос не пропадает.
    """
    override = os.environ.get("JARVIS_SPEAKER_EXE")

    if override:
        return override if Path(override).is_file() else None

    for candidate in (
        PUBLISH_DIR / "speaker" / "JARVIS.Speaker.exe",
        PUBLISH_DIR / "app" / "JARVIS.Speaker.exe",
        PROJECT_ROOT / "JARVIS.Speaker" / "bin" / "Release" / "net10.0" / "JARVIS.Speaker.exe",
        PROJECT_ROOT / "JARVIS.Speaker" / "bin" / "Debug" / "net10.0" / "JARVIS.Speaker.exe",
    ):
        if candidate.is_file():
            return str(candidate)

    return None
