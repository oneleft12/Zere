"""Сканер ярлыков «Пуск» (порт StartMenuScanner.cs)."""

from __future__ import annotations

import os
from pathlib import Path

from zere.tools.applications.app_alias_provider import AppAliasProvider
from zere.tools.applications.indexing.app_info import AppInfo
from zere.tools.applications.indexing.i_app_scanner import IAppScanner


def _common_start_menu() -> Path:
    # Environment.SpecialFolder.CommonStartMenu
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    return Path(program_data) / "Microsoft" / "Windows" / "Start Menu"


def _user_start_menu() -> Path:
    # Environment.SpecialFolder.StartMenu
    appdata = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu"


class StartMenuScanner(IAppScanner):
    """Рекурсивно собирает *.lnk из меню «Пуск» (общего и пользовательского)."""

    def scan(self) -> list[AppInfo]:
        apps: list[AppInfo] = []

        folders = [
            _common_start_menu(),
            _user_start_menu(),
        ]

        for folder in folders:
            self._scan_folder(folder, apps)

        return apps

    def _scan_folder(self, folder: Path, apps: list[AppInfo]) -> None:
        if not folder.is_dir():
            return

        try:
            shortcuts = [
                entry
                for entry in folder.iterdir()
                if entry.is_file() and entry.suffix.lower() == ".lnk"
            ]

            for shortcut in shortcuts:
                name = shortcut.stem

                apps.append(
                    AppInfo(
                        name=name,
                        executable_path=str(shortcut),
                        source="Start Menu",
                        priority=80,
                        category="Application",
                        aliases=AppAliasProvider.get_aliases(name),
                    )
                )

            sub_folders = [entry for entry in folder.iterdir() if entry.is_dir()]

            for sub_folder in sub_folders:
                self._scan_folder(sub_folder, apps)
        except Exception:
            pass
