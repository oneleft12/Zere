"""Сервис процессов: список, поиск, завершение (порт Windows/ProcessService.cs, → psutil)."""

from __future__ import annotations

import psutil

from jarvis.tools.windows.process_info import ProcessInfo


def _process_name(process: "psutil.Process") -> str:
    """Имя процесса без расширения — как C# Process.ProcessName."""
    name = process.name()
    return name[:-4] if name.lower().endswith(".exe") else name


def _normalize(name: str) -> str:
    trimmed = (name or "").strip()
    return trimmed[:-4] if trimmed.lower().endswith(".exe") else trimmed


class ProcessService:
    # Системные процессы, которых нельзя касаться командами ассистента.
    _PROTECTED_NAMES = frozenset(
        {
            "system",
            "idle",
            "registry",
            "smss",
            "csrss",
            "wininit",
            "winlogon",
            "services",
            "lsass",
            "svchost",
            "memcompression",
            "memory compression",
        }
    )

    @classmethod
    def is_protected(cls, name: str) -> bool:
        """Запрещено ли завершение процесса с таким именем (без .exe и регистра)."""
        normalized = _normalize(name)
        return bool(normalized) and normalized.lower() in cls._PROTECTED_NAMES

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

    def search_exact(self, name: str) -> list[ProcessInfo]:
        """Точное совпадение имени (без учёта регистра и .exe) — тот же предикат, что и у kill()."""
        normalized = _normalize(name).lower()

        return [
            info
            for info in self.get_processes()
            if info.name.lower() == normalized
        ]

    def kill(self, name: str) -> bool:
        """Завершает все процессы с точным именем (вместе с дочерними).

        Возвращает True, только если завершён хотя бы один процесс.
        """
        if self.is_protected(name):
            return False

        name_lower = _normalize(name).lower()

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

        killed = 0

        for process in processes:
            try:
                # process.Kill(true) — вместе с дочерними процессами
                for child in process.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass

                process.kill()
                killed += 1
            except Exception:
                # Процесс мог завершиться сам или нет прав — не считаем успехом.
                pass

        return killed > 0
