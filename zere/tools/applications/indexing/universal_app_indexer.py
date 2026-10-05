"""Универсальный индексер приложений (порт UniversalAppIndexer.cs)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from zere.tools.applications.app_paths_scanner import AppPathsScanner
from zere.tools.applications.local_app_data_scanner import LocalAppDataScanner
from zere.tools.applications.registry_scanner import RegistryScanner
from zere.tools.applications.start_menu_scanner import StartMenuScanner
from zere.tools.applications.indexing.app_info import AppInfo
from zere.tools.applications.indexing.i_app_scanner import IAppScanner


class UniversalAppIndexer:
    """Собирает индекс приложений из всех сканеров и ищет по нему."""

    def __init__(self) -> None:
        # %LOCALAPPDATA%\ZERE (как Environment.SpecialFolder.LocalApplicationData)
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA")
            or (Path.home() / "AppData" / "Local")
        )

        folder = local_app_data / "ZERE"
        folder.mkdir(parents=True, exist_ok=True)

        self._index_path: Path = folder / "app_index.json"

        self._scanners: list[IAppScanner] = []
        self._apps: dict[str, AppInfo] = {}

        self.register_scanner(StartMenuScanner())
        self.register_scanner(RegistryScanner())
        self.register_scanner(AppPathsScanner())
        self.register_scanner(LocalAppDataScanner())

        self.build()

    def register_scanner(self, scanner: IAppScanner) -> None:
        self._scanners.append(scanner)

    def get_apps(self) -> dict[str, AppInfo]:
        """Все приложения индекса (ключ — имя в нижнем регистре)."""
        return self._apps

    @property
    def count(self) -> int:
        return len(self._apps)

    def build(self) -> None:
        self._apps.clear()

        for scanner in self._scanners:
            for app in scanner.scan():
                self._apps[app.name.lower()] = app

        self.save()

    def save(self) -> None:
        apps = sorted(self._apps.values(), key=lambda a: a.name)
        payload = [asdict(app) for app in apps]

        with open(self._index_path, "w", encoding="utf-8") as file:
            json.dump(
                payload,
                file,
                indent=2,
                ensure_ascii=False,
                default=_json_default,
            )

    def find(self, query: str) -> AppInfo | None:
        query = query.lower().strip()

        candidates: list[tuple[AppInfo, int]] = []

        for app in self._apps.values():
            score = 0

            if app.name.lower() == query:
                score = 100
            elif any(alias.lower() == query for alias in app.aliases):
                score = 95
            elif app.name.lower().startswith(query):
                score = 90
            elif query in app.name.lower():
                score = 80

            if score > 0:
                candidates.append((app, score))

        if not candidates:
            return None

        # OrderByDescending(score).ThenByDescending(priority)
        candidates.sort(key=lambda candidate: (-candidate[1], -candidate[0].priority))

        return candidates[0][0]


def _json_default(value: object) -> str:
    """Сериализация дат как ISO (DateTime в C#-JSON тоже ISO)."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
