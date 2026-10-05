"""Сканер приложений из реестра (порт RegistryScanner.cs)."""

from __future__ import annotations

import os
import winreg
from pathlib import Path

from zere.tools.applications.app_alias_provider import AppAliasProvider
from zere.tools.applications.indexing.app_info import AppInfo
from zere.tools.applications.indexing.i_app_scanner import IAppScanner

# Служебные exe, которые не являются главным приложением.
_BAD_EXECUTABLES = (
    "uninstall.exe",
    "unins000.exe",
    "gameoverlayui.exe",
    "gameoverlayui64.exe",
    "crashhandler.exe",
    "updater.exe",
    "helper.exe",
)


class RegistryScanner(IAppScanner):
    """Читает ключи Uninstall в HKLM/HKCU (Microsoft.Win32 → winreg)."""

    def scan(self) -> list[AppInfo]:
        apps: dict[str, AppInfo] = {}

        self._scan_hive(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            apps,
        )

        self._scan_hive(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            apps,
        )

        self._scan_hive(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            apps,
        )

        return list(apps.values())

    def _scan_hive(self, hive: int, path: str, apps: dict[str, AppInfo]) -> None:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            return  # ключ отсутствует

        with key:
            sub_key_count = winreg.QueryInfoKey(key)[0]

            for index in range(sub_key_count):
                try:
                    sub_key_name = winreg.EnumKey(key, index)

                    try:
                        with winreg.OpenKey(key, sub_key_name) as sub_key:
                            name = _query_string(sub_key, "DisplayName")
                            icon = _query_string(sub_key, "DisplayIcon")
                            install_location = _query_string(sub_key, "InstallLocation")
                    except OSError:
                        continue  # subKey is null

                    if name is None or name.isspace():
                        continue

                    exe = self._resolve_executable(icon, install_location)

                    if exe is None or exe.isspace():
                        continue

                    apps[name.lower()] = AppInfo(
                        name=name,
                        executable_path=exe,
                        source="Registry",
                        priority=90,
                        category=self._guess_category(name),
                        aliases=AppAliasProvider.get_aliases(name),
                    )
                except Exception:
                    # Пропускаем повреждённые записи реестра.
                    pass

    # ----------------------------
    # Умный поиск главного EXE
    # ----------------------------
    def _resolve_executable(
        self,
        display_icon: str | None,
        install_location: str | None,
    ) -> str | None:
        exe: str | None = None

        # 1. Берём DisplayIcon
        if display_icon is not None and not display_icon.isspace():
            exe = display_icon.split(",")[0].strip('"')

        # 2. Если путь существует и это НЕ служебный exe — используем сразу
        if exe is not None and not exe.isspace() and os.path.isfile(exe):
            file_name = os.path.basename(exe).lower()

            if file_name not in _BAD_EXECUTABLES:
                return exe

            if install_location is None:
                install_location = str(Path(exe).parent)

        # 3. Если есть папка установки — выбираем лучший exe
        if (
            install_location is not None
            and not install_location.isspace()
            and os.path.isdir(install_location)
        ):
            executables = [
                entry.path
                for entry in os.scandir(install_location)
                if entry.is_file() and entry.name.lower().endswith(".exe")
            ]

            if executables:
                # OrderByDescending(GetExecutableScore).First()
                best = executables[0]
                best_score = self._get_executable_score(best)

                for candidate in executables[1:]:
                    score = self._get_executable_score(candidate)
                    if score > best_score:
                        best, best_score = candidate, score

                return best

        return exe

    # ----------------------------
    # Рейтинг EXE файлов
    # ----------------------------
    def _get_executable_score(self, exe_path: str) -> int:
        name = os.path.basename(exe_path).lower()

        # Никогда не выбираем служебные процессы
        if (
            name.startswith("uninstall")
            or name.startswith("unins")
            or "overlay" in name
            or "crash" in name
            or "helper" in name
            or "updater" in name
        ):
            return 0

        scores = {
            "steam.exe": 100,
            "discord.exe": 100,
            "telegram.exe": 100,
            "code.exe": 100,
            "cursor.exe": 100,
            "spotify.exe": 100,
            "epicgameslauncher.exe": 100,
            "riotclientservices.exe": 100,
            "obs64.exe": 100,
        }

        return scores.get(name, 50)

    # ----------------------------
    # Категории приложений
    # ----------------------------
    def _guess_category(self, name: str) -> str:
        n = name.lower()

        if "steam" in n or "epic" in n or "riot" in n:
            return "Game Launcher"

        if "discord" in n or "telegram" in n:
            return "Messenger"

        if "chrome" in n or "edge" in n or "firefox" in n:
            return "Browser"

        if "visual studio" in n or "code" in n or "cursor" in n:
            return "IDE"

        if "spotify" in n:
            return "Media"

        return "Application"


def _query_string(key: int, name: str) -> str | None:
    """RegistryKey.GetValue(...) as string: не-строковые типы → None."""
    try:
        value, _registry_type = winreg.QueryValueEx(key, name)
    except OSError:
        return None

    return value if isinstance(value, str) else None
