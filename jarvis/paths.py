"""Единые пути к ресурсам проекта JARVIS (корень репозитория)."""

from __future__ import annotations

from pathlib import Path

# Корень репозитория: <Jarvis>/jarvis/paths.py -> parents[1]
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

CONFIG_DIR: Path = PROJECT_ROOT / "config"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
PLUGINS_DIR: Path = PROJECT_ROOT / "plugins"
VOICE_DIR: Path = PROJECT_ROOT / "JARVIS.Voice"


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
