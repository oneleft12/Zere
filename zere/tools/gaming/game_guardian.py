"""Обнаружение запущенных игр (порт GameGuardian.cs)."""

from __future__ import annotations

import psutil

from zere.tools.gaming.game_catalog import GameCatalog


def _process_name(process: "psutil.Process") -> str:
    """Имя процесса без расширения — как C# Process.ProcessName."""
    name = process.name()
    return name[:-4] if name.lower().endswith(".exe") else name


class GameGuardian:
    def get_running_games(self) -> list[str]:
        running: list[str] = []

        for process in psutil.process_iter():
            try:
                process_name = _process_name(process).lower()

                for game_key, game_value in GameCatalog.GAMES.items():
                    if game_key in process_name:
                        running.append(game_value)
            except Exception:
                pass

        # Distinct() — с сохранением порядка первого вхождения.
        result: list[str] = []
        for game in running:
            if game not in result:
                result.append(game)

        return result

    def is_gaming(self) -> bool:
        return len(self.get_running_games()) > 0
