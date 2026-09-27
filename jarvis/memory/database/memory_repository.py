"""Порт JARVIS.Memory/Database/MemoryRepository.cs."""

from __future__ import annotations

import datetime
from typing import Optional

from jarvis.memory.database.memory_database import MemoryDatabase
from jarvis.memory.models.memory_item import MemoryItem


def _now_roundtrip() -> str:
    # Аналог DateTime.Now.ToString("O"): локальное время, 7 долей секунды.
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f") + "0"


def _parse_datetime(value: str) -> datetime.datetime:
    # Аналог DateTime.Parse(value, CultureInfo.InvariantCulture).
    return datetime.datetime.fromisoformat(value)


class MemoryRepository:
    def __init__(self, database: MemoryDatabase) -> None:
        self._database = database

    def remember(self, key: str, value: str, category: str = "User") -> None:
        connection = self._database.create_connection()
        try:
            connection.execute(
                """
        INSERT INTO Memories(Key, Value, Category, CreatedAt)
        VALUES($key,$value,$category,$time)
        ON CONFLICT(Key)
        DO UPDATE SET
            Value = excluded.Value,
            Category = excluded.Category;
        """,
                {
                    "key": key.lower(),
                    "value": value,
                    "category": category,
                    "time": _now_roundtrip(),
                },
            )
        finally:
            connection.close()

    def forget(self, key: str) -> bool:
        connection = self._database.create_connection()
        try:
            cursor = connection.execute(
                """
        DELETE FROM Memories
        WHERE lower(Key)=lower($key)
        """,
                {"key": key},
            )
            return cursor.rowcount > 0  # C#: command.ExecuteNonQuery() > 0
        finally:
            connection.close()

    def forget_by_id(self, memory_id: int) -> bool:
        """Удаление по первичному ключу (для DELETE /api/memory/{id})."""
        connection = self._database.create_connection()
        try:
            cursor = connection.execute(
                "DELETE FROM Memories WHERE Id=$id",
                {"id": memory_id},
            )
            return cursor.rowcount > 0
        finally:
            connection.close()

    def get(self, key: str) -> Optional[MemoryItem]:
        return self.find(key)

    def find(self, key: str) -> Optional[MemoryItem]:
        connection = self._database.create_connection()
        try:
            cursor = connection.execute(
                """
        SELECT Id, Key, Value, Category, CreatedAt
        FROM Memories
        WHERE lower(Key)=lower($key)
        """,
                {"key": key},
            )
            row = cursor.fetchone()
            if row is None:  # C#: if (!reader.Read()) return null;
                return None
            return MemoryItem(
                id=row[0],
                key=row[1],
                value=row[2],
                category=row[3],
                created_at=_parse_datetime(row[4]),
            )
        finally:
            connection.close()

    def get_all(self) -> list[MemoryItem]:
        connection = self._database.create_connection()
        try:
            cursor = connection.execute(
                """
        SELECT Id, Key, Value, Category, CreatedAt
        FROM Memories
        ORDER BY Category, Key
        """,
            )
            return [
                MemoryItem(
                    id=row[0],
                    key=row[1],
                    value=row[2],
                    category=row[3],
                    created_at=_parse_datetime(row[4]),
                )
                for row in cursor
            ]
        finally:
            connection.close()

    def search(self, query: str) -> list[MemoryItem]:
        connection = self._database.create_connection()
        try:
            cursor = connection.execute(
                """
        SELECT Id, Key, Value, Category, CreatedAt
        FROM Memories
        WHERE lower(Key) LIKE $query OR lower(Value) LIKE $query
        ORDER BY Category, Key
        """,
                {"query": f"%{query.lower()}%"},
            )
            return [
                MemoryItem(
                    id=row[0],
                    key=row[1],
                    value=row[2],
                    category=row[3],
                    created_at=_parse_datetime(row[4]),
                )
                for row in cursor
            ]
        finally:
            connection.close()

    def clear(self) -> None:
        connection = self._database.create_connection()
        try:
            connection.execute("DELETE FROM Memories")
        finally:
            connection.close()
