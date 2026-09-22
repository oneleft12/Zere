"""Сканер папок LocalAppData/Roaming (порт LocalAppDataScanner.cs)."""

from __future__ import annotations

import os
from pathlib import Path

from jarvis.tools.applications.app_alias_provider import AppAliasProvider
from jarvis.tools.applications.indexing.app_info import AppInfo
from jarvis.tools.applications.indexing.i_app_scanner import IAppScanner

_CATEGORIES = {
    "Discord": "Messenger",
    "Telegram Desktop": "Messenger",
    "Spotify": "Media",
    "Cursor": "IDE",
    "Code": "IDE",
    "Riot Client": "Game Launcher",
}


class LocalAppDataScanner(IAppScanner):
    """Ищет exe известных приложений в %LOCALAPPDATA% и %APPDATA%."""

    def __init__(self) -> None:
        # Environment.SpecialFolder.LocalApplicationData / ApplicationData
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        )
        roaming = Path(
            os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        )

        self._roots: tuple[Path, ...] = (local_app_data, roaming)

        self._targets: tuple[str, ...] = (
            "Discord",
            "Telegram Desktop",
            "Spotify",
            "Cursor",
            "Code",
            "Riot Client",
        )

    def scan(self) -> list[AppInfo]:
        apps: list[AppInfo] = []

        for root in self._roots:
            for folder in self._targets:
                path = root / folder

                if not path.is_dir():
                    continue

                try:
                    # GetFiles("*.exe", AllDirectories).OrderBy(Length).First()
                    executables = [
                        entry.path
                        for entry in path.rglob("*")
                        if entry.is_file() and entry.suffix.lower() == ".exe"
                    ]

                    if not executables:
                        continue

                    exe = min(executables, key=len)

                    apps.append(
                        AppInfo(
                            name=folder,
                            executable_path=exe,
                            source="LocalAppData",
                            priority=100,
                            category=self._guess_category(folder),
                            aliases=AppAliasProvider.get_aliases(folder),
                        )
                    )
                except Exception:
                    pass

        return apps

    def _guess_category(self, name: str) -> str:
        return _CATEGORIES.get(name, "Application")
