"""Менеджер процессов (порт System/ProcessManager.cs, System.Diagnostics → psutil)."""

from __future__ import annotations

import psutil


def _process_name(process: "psutil.Process") -> str:
    """Имя процесса без расширения — как C# Process.ProcessName."""
    name = process.name()
    return name[:-4] if name.lower().endswith(".exe") else name


class ProcessManager:
    def get_processes(self) -> list["psutil.Process"]:
        items: list[tuple[str, "psutil.Process"]] = []

        for process in psutil.process_iter():
            try:
                items.append((_process_name(process), process))
            except Exception:
                # Некоторые процессы недоступны.
                pass

        # OrderBy(p => p.ProcessName)
        items.sort(key=lambda item: item[0].lower())

        return [process for _name, process in items]

    def find(self, name: str) -> list["psutil.Process"]:
        name_lower = name.lower()

        items: list[tuple[str, "psutil.Process"]] = []

        for process in psutil.process_iter():
            try:
                process_name = _process_name(process)
            except Exception:
                continue

            # Contains(name, StringComparison.OrdinalIgnoreCase)
            if name_lower in process_name.lower():
                items.append((process_name, process))

        items.sort(key=lambda item: item[0].lower())

        return [process for _name, process in items]

    def kill(self, name: str) -> bool:
        name_lower = name.lower()

        process: "psutil.Process | None" = None

        for candidate in psutil.process_iter():
            try:
                # FirstOrDefault(p.ProcessName.Equals(name, OrdinalIgnoreCase))
                if _process_name(candidate).lower() == name_lower:
                    process = candidate
                    break
            except Exception:
                continue

        if process is None:
            return False

        try:
            # process.Kill(true) — завершить вместе с дочерними процессами
            for child in process.children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass

            process.kill()
        except psutil.NoSuchProcess:
            # C#: InvalidOperationException → false
            return False

        return True
