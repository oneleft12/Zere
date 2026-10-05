"""Каталог игр (порт GameCatalog.cs — static class)."""

from __future__ import annotations

from typing import ClassVar


class GameCatalog:
    # C#: public static readonly Dictionary<string, string> Games
    GAMES: ClassVar[dict[str, str]] = {
        "steam": "Steam",
        "epicgameslauncher": "Epic Games Launcher",
        "valorant": "VALORANT",
        "cs2": "Counter-Strike 2",
        "dota2": "Dota 2",
        "leagueclient": "League of Legends",
        "ppsspp": "PPSSPP",
        "minecraft": "Minecraft",
    }
