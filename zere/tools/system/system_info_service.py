"""Системная информация (порт System/SystemInfoService.cs)."""

from __future__ import annotations

import sys

import psutil


class SystemInfoService:
    def get_cpu(self) -> str:
        return self._query_single("Win32_Processor", "Name")

    def get_gpu(self) -> str:
        return self._query_single("Win32_VideoController", "Name")

    def get_ram(self) -> str:
        # C#: SELECT TotalPhysicalMemory FROM Win32_ComputerSystem (WMI → psutil)
        total_bytes = float(psutil.virtual_memory().total)

        if total_bytes:
            # Math.Round(bytes / 1024 / 1024 / 1024) — банковское округление,
            # как и round() в Python.
            gb = round(total_bytes / 1024 / 1024 / 1024)
            return f"{gb} ГБ"

        return "Не удалось определить RAM."

    def get_windows_version(self) -> str:
        # Environment.OSVersion.VersionString
        version = sys.getwindowsversion()
        return f"Microsoft Windows NT {version.major}.{version.minor}.{version.build}.0"

    def get_running_processes(self, limit: int = 15) -> list[str]:
        names: list[str] = []

        for process in psutil.process_iter():
            try:
                name = process.name()
                # C# Process.ProcessName — без расширения ".exe"
                names.append(name[:-4] if name.lower().endswith(".exe") else name)
            except Exception:
                # Некоторые процессы недоступны.
                pass

        # OrderBy(p => p.ProcessName).Take(limit)
        names.sort(key=str.lower)
        return names[:limit]

    def _query_single(self, class_name: str, property_name: str) -> str:
        # System.Management (WMI) → пакет wmi; ленимый импорт в теле функции.
        import wmi

        searcher = wmi.WMI()

        for obj in searcher.query(f"SELECT {property_name} FROM {class_name}"):
            value = getattr(obj, property_name, None)
            # obj[property]?.ToString() ?? "Не найдено."
            if value is None:
                return "Не найдено."
            return str(value)

        return "Не найдено."
