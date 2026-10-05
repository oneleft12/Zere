"""Запуск приложений по имени (порт ApplicationLauncher.cs)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from zere.tools.applications.app_alias_provider import AppAliasProvider
from zere.tools.applications.indexing.app_info import AppInfo
from zere.tools.applications.indexing.universal_app_indexer import UniversalAppIndexer


class ApplicationLauncher:
    """Запуск приложений: алиасы → системные exe → индекс UniversalAppIndexer."""

    def __init__(self) -> None:
        self._indexer = UniversalAppIndexer()

        self._system_apps: dict[str, str] = {
            "калькулятор": "calc.exe",
            "блокнот": "notepad.exe",
            "проводник": "explorer.exe",
            "paint": "mspaint.exe",
        }

        print(f"\n[Indexer] Загружено {self._indexer.count} приложений.\n")

    def launch(self, app_name: str) -> bool:
        app_name = app_name.lower().strip()

        # Алиасы
        alias = AppAliasProvider.ALIASES.get(app_name)
        if alias is not None:
            app_name = alias

        print(f"[TOOLS] Поиск: {app_name}")

        # Системные приложения
        system_exe = self._system_apps.get(app_name)
        if system_exe is not None:
            self._start(system_exe)
            return True

        # Ищем в новом индексаторе
        app = self._indexer.find(app_name)

        if app is None:
            print("[TOOLS] Не найдено.")
            return False

        print(f"[TOOLS] {app.name}")
        print(f"[TOOLS] Источник: {app.source}")
        print(f"[TOOLS] Путь: {app.executable_path}")

        self._start(app.executable_path)

        return True

    def rebuild_index(self) -> None:
        self._indexer.build()

    def get_installed_applications(self) -> dict[str, AppInfo]:
        return self._indexer.get_apps()

    @staticmethod
    def _start(executable: str) -> None:
        # Discord
        if (
            Path(executable).name.lower() == "update.exe"
            and "discord" in executable.lower()
        ):
            # UseShellExecute = true + Arguments = "--processStart Discord.exe"
            subprocess.Popen([executable, "--processStart", "Discord.exe"])
            return

        # UseShellExecute = true (запуск через оболочку: exe, ярлыки, документы)
        os.startfile(executable)
