"""Порт ZERE.Memory/Database/ConversationRepository.cs."""

from __future__ import annotations

import datetime

from zere.memory.database.memory_database import MemoryDatabase
from zere.memory.models.conversation import Conversation


def _now_roundtrip() -> str:
    # Аналог DateTime.Now.ToString("O"): локальное время, 7 долей секунды.
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f") + "0"


def _parse_datetime(value: str) -> datetime.datetime:
    # Аналог DateTime.Parse(value, CultureInfo.InvariantCulture).
    return datetime.datetime.fromisoformat(value)


class ConversationRepository:
    def __init__(self, database: MemoryDatabase) -> None:
        self._database = database

    def save(self, user_message: str, zere_response: str) -> None:
        connection = self._database.create_connection()
        try:
            connection.execute(
                f"""
        INSERT INTO Conversations
        (UserMessage, {self._response_column}, Timestamp)
        VALUES ($user, $zere, $time)
        """,
                {
                    "user": user_message,
                    "zere": zere_response,
                    "time": _now_roundtrip(),
                },
            )
        finally:
            connection.close()

    @property
    def _response_column(self) -> str:
        """Колонка ответа: ZereResponse, либо JarvisResponse в старой базе."""
        return self._database.response_column

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
                f"""
        SELECT Id, UserMessage, {self._response_column}, Timestamp
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
                    zere_response=row[2],
                    timestamp=_parse_datetime(row[3]),
                )
                for row in cursor
            ]
        finally:
            connection.close()

    def count(self, search: str = "") -> int:
        """Всего записей истории (для пагинации /api/history).

        `search` — подстрока для поиска по вопросу и ответу (регистронезависимо).
        """
        connection = self._database.create_connection()
        try:
            if search:
                cursor = connection.execute(
                    f"""
        SELECT COUNT(*) FROM Conversations
        WHERE lower(UserMessage) LIKE $q OR lower({self._response_column}) LIKE $q
        """,
                    {"q": f"%{search.lower()}%"},
                )
            else:
                cursor = connection.execute("SELECT COUNT(*) FROM Conversations")
            row = cursor.fetchone()
            return int(row[0]) if row is not None else 0
        finally:
            connection.close()

    def get_page(self, limit: int, offset: int, search: str = "") -> list[Conversation]:
        """Страница истории: новые сверху (Id DESC), с учётом смещения.

        `search` — регистронезависимая подстрока по вопросу и ответу.
        """
        connection = self._database.create_connection()
        try:
            if search:
                cursor = connection.execute(
                    f"""
        SELECT Id, UserMessage, {self._response_column}, Timestamp
        FROM Conversations
        WHERE lower(UserMessage) LIKE $q OR lower({self._response_column}) LIKE $q
        ORDER BY Id DESC
        LIMIT $limit OFFSET $offset
        """,
                    {
                        "q": f"%{search.lower()}%",
                        "limit": limit,
                        "offset": offset,
                    },
                )
            else:
                cursor = connection.execute(
                    f"""
        SELECT Id, UserMessage, {self._response_column}, Timestamp
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
                    zere_response=row[2],
                    timestamp=_parse_datetime(row[3]),
                )
                for row in cursor
            ]
        finally:
            connection.close()
