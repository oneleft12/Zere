"""Порт JARVIS.Memory/Database/MemoryDatabase.cs — sqlite3 вместо Microsoft.Data.Sqlite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jarvis import paths


class MemoryDatabase:
    """Аналог MemoryDatabase : IDisposable — вместо Dispose() метод close()."""

    def __init__(self) -> None:
        # C#: %LOCALAPPDATA%\JARVIS\jarvis.db — по спецификации путь только jarvis.paths.db_path()
        self._database_path: Path = paths.db_path()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)  # C#: Directory.CreateDirectory(folder)

        self._initialize()

    def create_connection(self) -> sqlite3.Connection:
        # C#: new SqliteConnection($"Data Source={_databasePath}").
        # isolation_level=None — автокоммит: в C# явных транзакций нет, каждый запрос фиксируется сам.
        return sqlite3.connect(self._database_path, isolation_level=None)

    def _initialize(self) -> None:
        # C#: using var connection; command.ExecuteNonQuery() со всеми CREATE TABLE сразу.
        connection = self.create_connection()
        try:
            connection.executescript(
                """
        CREATE TABLE IF NOT EXISTS Conversations
        (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            UserMessage TEXT NOT NULL,
            JarvisResponse TEXT NOT NULL,
            Timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS Memories
        (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            Key TEXT NOT NULL UNIQUE,
            Value TEXT NOT NULL,
            Category TEXT NOT NULL DEFAULT 'User',
            CreatedAt TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS Meta
        (
            Key TEXT PRIMARY KEY,
            Value TEXT NOT NULL
        );
        """
            )
        finally:
            connection.close()

    def close(self) -> None:
        # IDisposable implemented for interface consistency; no unmanaged resources to release.
        # Connections are opened/closed per operation via create_connection().
        pass
