"""Единые пути к ресурсам проекта ZERE (корень репозитория)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Корень репозитория: <Zere>/zere/paths.py -> parents[1]
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

CONFIG_DIR: Path = PROJECT_ROOT / "config"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
PLUGINS_DIR: Path = PROJECT_ROOT / "plugins"
TOOLS_DIR: Path = PROJECT_ROOT / "tools"
VOICE_DIR: Path = PROJECT_ROOT / "ZERE.Voice"
PUBLISH_DIR: Path = PROJECT_ROOT / "publish"

#: Исходники плагина ZERE для Krita (PyKrita): кладутся в пользовательскую
#: папку pykrita установщиком (`zere.tools.drawing.krita_install`).
KRITA_PLUGIN_DIR: Path = TOOLS_DIR / "krita_plugin"


def config_path() -> Path:
    return CONFIG_DIR / "config.json"


def plugins_config_path() -> Path:
    return CONFIG_DIR / "plugins.json"


def ai_config_path() -> Path:
    """Настройки ИИ и ключ облачной модели: config/ai.json (gitignored).

    Путь вычисляется от config_path(), а не от CONFIG_DIR: тесты и E2E
    подменяют config_path() на временный каталог, и ключ не должен
    утечь из песочницы в реальный config/.

    Файл содержит секрет — наружу (в API) он не отдаётся: клиент видит
    только маску вида «sk-...abcd».
    """
    return config_path().parent / "ai.json"


def router_config_path() -> Path:
    """Настройки роутера интентов Jev: config/router.json (gitignored).

    Путь вычисляется от config_path().parent — как у ai_config_path(): тесты
    подменяют config_path() на временный каталог, и ключ Jev не должен
    утечь из песочницы в реальный config/. Файл может содержать секрет
    (ключ OpenRouter) — наружу отдаётся только маска.
    """
    return config_path().parent / "router.json"


def mcp_config_path() -> Path:
    """Настройки MCP-серверов: config/mcp.json (gitignored).

    Путь вычисляется от config_path().parent — как у ai_config_path():
    тесты подменяют config_path() на временный каталог. Файл локальный:
    в нём путь к хранилищу заметок Obsidian и другие машинные значения.
    Образец для копирования — config/mcp.example.json.
    """
    return config_path().parent / "mcp.json"


def conspect_config_path() -> Path:
    """Настройки конспектора: config/conspect.json (gitignored).

    Путь вычисляется от config_path().parent — как у ai_config_path(): тесты
    подменяют config_path() на временный каталог, поэтому конспектор в тестах
    не пишет в настоящее хранилище Obsidian. Файл локальный (путь к хранилищу
    и потолки объёма), поэтому в git его нет; образец —
    config/conspect.example.json.
    """
    return config_path().parent / "conspect.json"


def db_path() -> Path:
    """Путь к базе истории и памяти.

    До ребрендинга база называлась jarvis.db. Файл не удаляем и не копируем:
    при первом обращении просто переименовываем, чтобы память и история
    прошлых версий остались доступны (обратной операции не требуется).
    """
    db_file = PROJECT_ROOT / "zere.db"
    legacy_file = PROJECT_ROOT / "jarvis.db"

    if not db_file.exists() and legacy_file.exists():
        try:
            legacy_file.replace(db_file)
        except OSError:
            # Файл занят (например, параллельно работает старая версия):
            # отдаём новый путь, база создастся заново — данные не трогаем.
            return db_file

    return db_file


def logs_dir() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def plugins_dir() -> Path:
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return PLUGINS_DIR


def voice_dir() -> Path:
    return VOICE_DIR


def chattts_dir() -> Path:
    """Папка ChatTTS: вывод синтеза (output_*.wav) и профили голоса (voices/)."""
    return VOICE_DIR / "ChatTts"


def silero_dir() -> Path:
    """Папка Silero TTS: модель (v5_5_ru.pt) и вывод синтеза (output_*.wav)."""
    return VOICE_DIR / "Silero"


def whisper_models_dir() -> Path:
    return VOICE_DIR / "Models"


# ─── C#-хелпер озвучки (ZERE.Speaker) ─────────────────────


def speaker_executable() -> Optional[str]:
    """Путь к собранному C#-хелперу озвучки или None, если он не собран.

    Порядок поиска: переменная окружения `ZERE_SPEAKER_EXE` (отладка и
    тесты) → `publish/speaker` (так публикует установщик) → `publish/app`
    (рядом с C#-редакцией) → `bin/Release|Debug` (локальная сборка
    разработчика). Если ничего нет, Python-редакция озвучивает сама
    (sounddevice) — голос не пропадает.
    """
    override = os.environ.get("ZERE_SPEAKER_EXE")

    if override:
        return override if Path(override).is_file() else None

    for candidate in (
        PUBLISH_DIR / "speaker" / "ZERE.Speaker.exe",
        PUBLISH_DIR / "app" / "ZERE.Speaker.exe",
        PROJECT_ROOT / "ZERE.Speaker" / "bin" / "Release" / "net10.0" / "ZERE.Speaker.exe",
        PROJECT_ROOT / "ZERE.Speaker" / "bin" / "Debug" / "net10.0" / "ZERE.Speaker.exe",
    ):
        if candidate.is_file():
            return str(candidate)

    return None
