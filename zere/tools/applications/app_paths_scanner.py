"""Сканер App Paths реестра (порт AppPathsScanner.cs)."""

from __future__ import annotations

import winreg
from pathlib import Path

from zere.tools.applications.app_alias_provider import AppAliasProvider
from zere.tools.applications.indexing.app_info import AppInfo
from zere.tools.applications.indexing.i_app_scanner import IAppScanner

_APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"


class AppPathsScanner(IAppScanner):
    """HKLM/HKCU -> SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths."""

    def scan(self) -> list[AppInfo]:
        apps: list[AppInfo] = []

        self._scan_hive(winreg.HKEY_LOCAL_MACHINE, apps)
        self._scan_hive(winreg.HKEY_CURRENT_USER, apps)

        return apps

    def _scan_hive(self, hive: int, apps: list[AppInfo]) -> None:
        try:
            key = winreg.OpenKey(hive, _APP_PATHS_KEY)
        except OSError:
            return  # ключ отсутствует

        with key:
            sub_key_count = winreg.QueryInfoKey(key)[0]

            for index in range(sub_key_count):
                try:
                    sub_key_name = winreg.EnumKey(key, index)

                    exe: str | None = None

                    try:
                        with winreg.OpenKey(key, sub_key_name) as sub_key:
                            value, _registry_type = winreg.QueryValueEx(sub_key, "")
                            if isinstance(value, str):
                                exe = value
                    except OSError:
                        exe = None  # subKey?.GetValue("") as string

                    if exe is None or exe.isspace():
                        continue

                    name = Path(sub_key_name).stem

                    apps.append(
                        AppInfo(
                            name=name,
                            executable_path=exe.strip('"'),
                            source="App Paths",
                            priority=95,
                            category="Application",
                            aliases=AppAliasProvider.get_aliases(name),
                        )
                    )
                except Exception:
                    pass
