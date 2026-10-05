"""Порт ZERE.Memory/Gaming/GameStatsDatabase.cs — sqlite3 вместо Microsoft.Data.Sqlite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from zere import paths


class GameStatsDatabase:
    def __init__(self) -> None:
        # C#: %LOCALAPPDATA%\ZERE\zere_games.db — по заданию путь только zere.paths.db_path()
        # (таблица GameStats создаётся в той же файловой БД, что и Memories/Conversations).
        self._database_path: Path = paths.db_path()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)  # C#: Directory.CreateDirectory(folder)

    def create_connection(self) -> sqlite3.Connection:
        # C#: new SqliteConnection($"Data Source={_databasePath}"); connection.Open(); CreateTables(connection);
        # isolation_level=None — автокоммит: в C# явных транзакций нет.
        connection = sqlite3.connect(self._database_path, isolation_level=None)
        self._create_tables(connection)
        return connection

    @staticmethod
    def _create_tables(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
        CREATE TABLE IF NOT EXISTS GameStats(
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            Game TEXT NOT NULL,
            Date TEXT NOT NULL,
            Minutes INTEGER NOT NULL,
            UNIQUE(Game, Date)
        );
        """
        )
