"""Порт JARVIS.Memory/Database/ConversationRepository.cs."""

from __future__ import annotations

import datetime

from jarvis.memory.database.memory_database import MemoryDatabase
from jarvis.memory.models.conversation import Conversation


def _now_roundtrip() -> str:
    # Аналог DateTime.Now.ToString("O"): локальное время, 7 долей секунды.
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f") + "0"


def _parse_datetime(value: str) -> datetime.datetime:
    # Аналог DateTime.Parse(value, CultureInfo.InvariantCulture).
    return datetime.datetime.fromisoformat(value)


class ConversationRepository:
    def __init__(self, database: MemoryDatabase) -> None:
        self._database = database

    def save(self, user_message: str, jarvis_response: str) -> None:
        connection = self._database.create_connection()
        try:
            connection.execute(
                """
        INSERT INTO Conversations
        (UserMessage, JarvisResponse, Timestamp)
        VALUES ($user, $jarvis, $time)
        """,
                {
                    "user": user_message,
                    "jarvis": jarvis_response,
                    "time": _now_roundtrip(),
                },
            )
        finally:
            connection.close()

    def clear_history(self) -> None:
        connection = self._database.create_connection()
        try:
            connection.execute("DELETE FROM Conversations")
        finally:
            connection.close()

    def get_last(self, count: int) -> list[Conversation]:
        connection = self._database.create_connection()
        try:
            cursor = connection.execute(
                """
        SELECT Id, UserMessage, JarvisResponse, Timestamp
        FROM Conversations
        ORDER BY Id DESC
        LIMIT $count
        """,
                {"count": count},
            )
            return [
                Conversation(
                    id=row[0],
                    user_message=row[1],
                    jarvis_response=row[2],
                    timestamp=_parse_datetime(row[3]),
                )
                for row in cursor
            ]
        finally:
            connection.close()

    def count(self) -> int:
        """Всего записей истории (для пагинации /api/history)."""
        connection = self._database.create_connection()
        try:
            cursor = connection.execute("SELECT COUNT(*) FROM Conversations")
            row = cursor.fetchone()
            return int(row[0]) if row is not None else 0
        finally:
            connection.close()

    def get_page(self, limit: int, offset: int) -> list[Conversation]:
        """Страница истории: новые сверху (Id DESC), с учётом смещения."""
        connection = self._database.create_connection()
        try:
            cursor = connection.execute(
                """
        SELECT Id, UserMessage, JarvisResponse, Timestamp
        FROM Conversations
        ORDER BY Id DESC
        LIMIT $limit OFFSET $offset
        """,
                {"limit": limit, "offset": offset},
            )
            return [
                Conversation(
                    id=row[0],
                    user_message=row[1],
                    jarvis_response=row[2],
                    timestamp=_parse_datetime(row[3]),
                )
                for row in cursor
            ]
        finally:
            connection.close()
