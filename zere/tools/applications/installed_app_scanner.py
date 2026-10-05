"""Кэш-индекс установленных приложений (порт InstalledAppScanner.cs)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from zere.tools.applications.registry_scanner import RegistryScanner


def _common_start_menu() -> Path:
    # Environment.SpecialFolder.CommonStartMenu
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    return Path(program_data) / "Microsoft" / "Windows" / "Start Menu"


def _user_start_menu() -> Path:
    # Environment.SpecialFolder.StartMenu
    appdata = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu"


class InstalledAppScanner:
    """Хранит индекс «имя → путь» в %LOCALAPPDATA%\\ZERE\\app_index.json."""

    def __init__(self) -> None:
        self._apps: dict[str, str] = {}
        self._registry_scanner = RegistryScanner()

        # Environment.SpecialFolder.LocalApplicationData + "ZERE"
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        )

        folder = local_app_data / "ZERE"
        folder.mkdir(parents=True, exist_ok=True)

        self._index_path: Path = folder / "app_index.json"

        if self._index_path.is_file():
            self._load_index()
        else:
            print("[Scanner] Создаю индекс приложений...")

            self._scan_start_menu()

            for app in self._registry_scanner.scan():
                self._apps[app.name.lower()] = app.executable_path

            self._save_index()

    def _scan_start_menu(self) -> None:
        folders = [
            _common_start_menu(),
            _user_start_menu(),
        ]

        for folder in folders:
            self._scan_folder(folder)

    def _scan_folder(self, folder: Path) -> None:
        if not folder.is_dir():
            return

        try:
            shortcuts = [
                entry
                for entry in folder.iterdir()
                if entry.is_file() and entry.suffix.lower() == ".lnk"
            ]

            for shortcut in shortcuts:
                name = shortcut.stem.lower()

                if name not in self._apps:
                    self._apps[name] = str(shortcut)

            sub_folders = [entry for entry in folder.iterdir() if entry.is_dir()]

            for sub_folder in sub_folders:
                self._scan_folder(sub_folder)
        except PermissionError:
            # Пропускаем папки без доступа.
            pass

    def find_application(self, name: str) -> str | None:
        name = name.lower().strip()

        exact = self._apps.get(name)
        if exact is not None:
            return exact

        for app_name, path in self._apps.items():
            if name in app_name:
                return path

        return None

    def get_all_apps(self) -> dict[str, str]:
        return self._apps

    def _save_index(self) -> None:
        with open(self._index_path, "w", encoding="utf-8") as file:
            json.dump(self._apps, file, indent=2, ensure_ascii=False)

        print(f"[Scanner] Индекс сохранён ({len(self._apps)} приложений).")

    def _load_index(self) -> None:
        with open(self._index_path, "r", encoding="utf-8") as file:
            apps = json.load(file)

        if not isinstance(apps, dict):
            return

        for app_name, path in apps.items():
            self._apps[app_name] = path

        print(f"[Scanner] Загружено {len(self._apps)} приложений.")

    def rebuild_index(self) -> None:
        self._apps.clear()

        self._scan_start_menu()

        for app in self._registry_scanner.scan():
            self._apps[app.name.lower()] = app.executable_path

        self._save_index()
