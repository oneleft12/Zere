"""Порт ZERE.Memory/Database/MemoryDatabase.cs — sqlite3 вместо Microsoft.Data.Sqlite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from zere import paths


class MemoryDatabase:
    """Аналог MemoryDatabase : IDisposable — вместо Dispose() метод close()."""

    def __init__(self) -> None:
        # C#: %LOCALAPPDATA%\ZERE\zere.db — по спецификации путь только zere.paths.db_path()
        self._database_path: Path = paths.db_path()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)  # C#: Directory.CreateDirectory(folder)

        # Колонка ответа раньше называлась JarvisResponse, после ребрендинга —
        # ZereResponse. Старая база не мигрируется: работаем с той схемой,
        # которая уже есть, чтобы история прошлых версий не терялась.
        self._response_column: str = "ZereResponse"

        self._initialize()

    @property
    def response_column(self) -> str:
        """Имя колонки ответа ассистента в таблице Conversations."""
        return self._response_column

    def create_connection(self) -> sqlite3.Connection:
        # C#: new SqliteConnection($"Data Source={_databasePath}").
        # isolation_level=None — автокоммит: в C# явных транзакций нет, каждый запрос фиксируется сам.
        return sqlite3.connect(self._database_path, isolation_level=None)

    def _initialize(self) -> None:
        # C#: using var connection; command.ExecuteNonQuery() со всеми CREATE TABLE сразу.
        connection = self.create_connection()
        try:
            self._detect_response_column(connection)
            connection.executescript(
                """
        CREATE TABLE IF NOT EXISTS Conversations
        (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            UserMessage TEXT NOT NULL,
            ZereResponse TEXT NOT NULL,
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

    def _detect_response_column(self, connection: sqlite3.Connection) -> None:
        """Определяет имя колонки ответа в существующей базе.

        Старые версии (до ребрендинга) писали историю в JarvisResponse.
        PRAGMA table_info возвращает пустой список, если таблицы ещё нет —
        тогда остаётся новое имя, и CREATE TABLE ниже создаёт схему с нуля.
        """
        try:
            cursor = connection.execute("PRAGMA table_info(Conversations)")
            columns = {str(row[1]) for row in cursor.fetchall()}
        except sqlite3.Error:
            return

        if "ZereResponse" in columns:
            self._response_column = "ZereResponse"
        elif "JarvisResponse" in columns:
            self._response_column = "JarvisResponse"

    def close(self) -> None:
        # IDisposable implemented for interface consistency; no unmanaged resources to release.
        # Connections are opened/closed per operation via create_connection().
        pass
