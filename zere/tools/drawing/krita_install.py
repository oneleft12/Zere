"""Установка плагина ZERE в Krita: копирование в pykrita и включение в kritarc.

Плагины PyKrita живут в пользовательской папке `pykrita`, а их включённость
хранится в `kritarc` (группа `[python]`, ключ `enable_<модуль>`) — ровно так
это делает менеджер Python-плагинов самой Krita. Поэтому установку можно
сделать без интерфейса:

    python -m zere.tools.drawing.krita_install          # установить и включить
    python -m zere.tools.drawing.krita_install --check   # что установлено и отвечает ли плагин

После установки Krita нужно перезапустить: плагины читаются при старте.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from zere import paths

#: Имя модуля плагина: `pykrita/zere/` и ключ `enable_zere` в kritarc.
PLUGIN_MODULE = "zere"
DESKTOP_FILE = "kritapykrita_zere.desktop"
#: Группа настроек Krita, куда плагин пишет рабочий порт.
SETTINGS_GROUP = "zere"
PORT_KEY = "port"
#: Группа kritarc, которой управляет менеджер Python-плагинов Krita.
PYTHON_GROUP = "python"


def plugin_source_dir() -> Path:
    """Исходники плагина в репозитории ZERE."""
    return paths.KRITA_PLUGIN_DIR


def plugin_files(source: Optional[Path] = None) -> List[Path]:
    """Файлы плагина, которые нужно скопировать (desktop + пакет модуля)."""
    root = Path(source or plugin_source_dir())
    return [root / DESKTOP_FILE, root / PLUGIN_MODULE]


def user_pykrita_dir() -> Path:
    """Пользовательская папка Python-плагинов Krita."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "krita" / "pykrita"

    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "krita" / "pykrita"


def kritarc_path() -> Path:
    """Файл настроек Krita (kritarc) для текущей системы."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "kritarc"

    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "kritarc"


# ── kritarc: разбор и правка без KConfig ──────────────────────────


def _group_bounds(lines: List[str], header: str) -> Tuple[Optional[int], Optional[int]]:
    """Границы группы в списке строк конфигурации KDE."""
    start = None

    for index, line in enumerate(lines):
        stripped = line.strip()

        if not (stripped.startswith("[") and stripped.endswith("]")):
            continue

        if start is None:
            if stripped == header:
                start = index
            continue

        return start, index

    return (start, len(lines)) if start is not None else (None, None)


def read_setting(text: str, group: str, key: str) -> Optional[str]:
    """Значение ключа в группе или None (аргументы и регистр — как в KConfig)."""
    lines = (text or "").splitlines()
    start, end = _group_bounds(lines, f"[{group}]")

    if start is None or end is None:
        return None

    for line in lines[start + 1:end]:
        name, separator, value = line.partition("=")

        if separator and name.strip() == key:
            return value.strip()

    return None


def write_setting(text: str, group: str, key: str, value: str) -> str:
    """Новый текст конфигурации с записанным ключом (группа создаётся при нужде)."""
    lines = (text or "").splitlines()
    header = f"[{group}]"
    start, end = _group_bounds(lines, header)

    if start is None or end is None:
        if lines and lines[-1].strip():
            lines.append("")

        lines.append(header)
        lines.append(f"{key}={value}")

        return "\n".join(lines) + "\n"

    for index in range(start + 1, end):
        name, separator, _value = lines[index].partition("=")

        if separator and name.strip() == key:
            lines[index] = f"{key}={value}"
            return "\n".join(lines) + "\n"

    lines.insert(end, f"{key}={value}")

    return "\n".join(lines) + "\n"


def enable_plugin(text: str) -> str:
    """Включает плагин ZERE так, как это делает менеджер плагинов Krita."""
    return write_setting(text, PYTHON_GROUP, f"enable_{PLUGIN_MODULE}", "true")


def is_plugin_enabled(text: str) -> bool:
    value = read_setting(text, PYTHON_GROUP, f"enable_{PLUGIN_MODULE}")
    return str(value).strip().lower() in ("true", "1", "yes", "on")


# ── Установка ─────────────────────────────────────────────────────


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as error:
        raise RuntimeError(f"Не удалось прочитать {path}: {error}") from error


def install(source: Optional[Path] = None, pykrita: Optional[Path] = None,
            kritarc: Optional[Path] = None, port: Optional[int] = None) -> str:
    """Копирует плагин и включает его в kritarc; возвращает отчёт для человека."""
    root = Path(source or plugin_source_dir())
    desktop = root / DESKTOP_FILE
    package = root / PLUGIN_MODULE

    if not desktop.is_file() or not (package / "__init__.py").is_file():
        raise RuntimeError(f"В {root} нет плагина ZERE для Krita")

    target = Path(pykrita or user_pykrita_dir())
    target.mkdir(parents=True, exist_ok=True)

    destination = target / PLUGIN_MODULE

    if destination.exists():
        shutil.rmtree(destination)

    shutil.copy2(desktop, target / DESKTOP_FILE)
    shutil.copytree(
        package,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    config_file = Path(kritarc or kritarc_path())
    config_file.parent.mkdir(parents=True, exist_ok=True)

    text = enable_plugin(_read_text(config_file))

    if port:
        text = write_setting(text, SETTINGS_GROUP, PORT_KEY, str(int(port)))

    config_file.write_text(text, encoding="utf-8")

    return (
        f"Плагин ZERE установлен в {target} и включён в {config_file.name}. "
        f"Перезапустите Krita — после запуска ZERE будет рисовать без курсора."
    )


def status() -> str:
    """Что установлено, включено и отвечает ли плагин прямо сейчас."""
    target = user_pykrita_dir()
    config_file = kritarc_path()

    installed = (target / DESKTOP_FILE).is_file() and (
        target / PLUGIN_MODULE / "__init__.py"
    ).is_file()
    enabled = is_plugin_enabled(_read_text(config_file))
    lines = [
        f"Плагин в pykrita: {'да' if installed else 'нет'} ({target})",
        f"Включён в {config_file.name}: {'да' if enabled else 'нет'}",
    ]

    from zere.tools.drawing.krita_api import KritaApiClient, KritaPluginError, plugin_port

    port = plugin_port()
    try:
        KritaApiClient(port=port).ping()
        lines.append(f"Krita отвечает на 127.0.0.1:{port}: да")
    except KritaPluginError as error:
        lines.append(f"Krita на 127.0.0.1:{port} не ответила: {error}")

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m zere.tools.drawing.krita_install",
        description="Установка плагина ZERE для Krita (рисование без курсора)",
    )
    parser.add_argument("--check", action="store_true",
                        help="показать состояние плагина, ничего не меняя")
    parser.add_argument("--source", type=Path, default=None,
                        help="папка с плагином (по умолчанию tools/krita_plugin)")
    parser.add_argument("--pykrita", type=Path, default=None,
                        help="куда копировать плагин (по умолчанию папка Krita)")
    parser.add_argument("--kritarc", type=Path, default=None,
                        help="файл настроек Krita")
    parser.add_argument("--port", type=int, default=None,
                        help="порт плагина (по умолчанию Krita выберет сама)")

    arguments = parser.parse_args(argv)

    try:
        if arguments.check:
            print(status())
            return 0

        print(install(arguments.source, arguments.pykrita, arguments.kritarc, arguments.port))
    except RuntimeError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
