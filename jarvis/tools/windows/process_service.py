"""Сервис процессов: список, поиск, завершение (порт Windows/ProcessService.cs, → psutil)."""

from __future__ import annotations

import psutil

from jarvis.tools.windows.process_info import ProcessInfo


def _process_name(process: "psutil.Process") -> str:
    """Имя процесса без расширения — как C# Process.ProcessName."""
    name = process.name()
    return name[:-4] if name.lower().endswith(".exe") else name


class ProcessService:
    def get_processes(self) -> list[ProcessInfo]:
        list_info: list[ProcessInfo] = []

        for process in psutil.process_iter():
            try:
                list_info.append(
                    ProcessInfo(
                        id=process.pid,
                        name=_process_name(process),
                        # Math.Round(process.WorkingSet64 / 1024d / 1024d, 1)
                        memory_mb=round(process.memory_info().rss / 1024 / 1024, 1),
                        # C# process.Responding: у psutil нет аналога проверки
                        # UI-очереди; по умолчанию True (как C# для процессов
                        # без главного окна).
                        responding=True,
                    )
                )
            except Exception:
                # Некоторые процессы недоступны.
                pass

        # OrderByDescending(p => p.MemoryMb)
        return sorted(list_info, key=lambda info: info.memory_mb, reverse=True)

    def search(self, name: str) -> list[ProcessInfo]:
        name_lower = name.lower()

        # Contains(name, StringComparison.OrdinalIgnoreCase)
        return [
            info
            for info in self.get_processes()
            if name_lower in info.name.lower()
        ]

    def kill(self, name: str) -> bool:
        name_lower = name.lower()

        # Process.GetProcessesByName(name) — точное совпадение имени
        processes: list["psutil.Process"] = []

        for process in psutil.process_iter():
            try:
                if _process_name(process).lower() == name_lower:
                    processes.append(process)
            except Exception:
                continue

        if not processes:
            return False

        for process in processes:
            try:
                # process.Kill(true) — вместе с дочерними процессами
                for child in process.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass

                process.kill()
            except Exception:
                pass

        return True
