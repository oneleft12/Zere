"""Совместимость базы истории со старой схемой (ребрендинг ZERE).

До ребрендинга колонка ответа называлась JarvisResponse, после — ZereResponse.
Старая база не мигрируется: обе реализации обязаны работать с той схемой,
которая уже есть, иначе история прошлых версий перестанет читаться.

Запуск: python3 tests/test_db_compat.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LEGACY_SCHEMA = """
CREATE TABLE Conversations
(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    UserMessage TEXT NOT NULL,
    JarvisResponse TEXT NOT NULL,
    Timestamp TEXT NOT NULL
);

CREATE TABLE Memories
(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Key TEXT NOT NULL UNIQUE,
    Value TEXT NOT NULL,
    Category TEXT NOT NULL DEFAULT 'User',
    CreatedAt TEXT NOT NULL
);

CREATE TABLE Meta
(
    Key TEXT PRIMARY KEY,
    Value TEXT NOT NULL
);
"""

NEW_SCHEMA = """
CREATE TABLE Conversations
(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    UserMessage TEXT NOT NULL,
    ZereResponse TEXT NOT NULL,
    Timestamp TEXT NOT NULL
);
"""


def _columns(db_file: Path) -> set[str]:
    connection = sqlite3.connect(db_file)
    try:
        return {str(row[1]) for row in connection.execute("PRAGMA table_info(Conversations)")}
    finally:
        connection.close()


def _legacy_database(tmp: Path, with_row: bool = True) -> Path:
    """Создаёт базу прежней версии (колонка JarvisResponse)."""
    db_file = tmp / "legacy.db"
    connection = sqlite3.connect(db_file)
    try:
        connection.executescript(LEGACY_SCHEMA)
        if with_row:
            connection.execute(
                "INSERT INTO Conversations (UserMessage, JarvisResponse, Timestamp) "
                "VALUES (?, ?, ?)",
                ("привет из прошлой версии", "ответ прошлой версии", "2026-01-01T00:00:00.0000000"),
            )
        connection.commit()
    finally:
        connection.close()
    return db_file


def test_legacy_column_is_detected() -> None:
    """В старой базе репозиторий читает и пишет в JarvisResponse."""
    from zere.memory.database.conversation_repository import ConversationRepository
    from zere.memory.database.memory_database import MemoryDatabase

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        db_file = _legacy_database(tmp)

        with mock.patch("zere.paths.db_path", return_value=db_file):
            database = MemoryDatabase()
            repository = ConversationRepository(database)

            assert database.response_column == "JarvisResponse", "старая колонка не распознана"

            # Запись идёт в существующую колонку, а не в несуществующую ZereResponse.
            repository.save("новый вопрос", "новый ответ")
            assert repository.count() == 2, "запись в старую схему не удалась"

            # История прошлой версии по-прежнему читается.
            conversations = repository.get_last(2)
            texts = {(c.user_message, c.zere_response) for c in conversations}
            assert ("привет из прошлой версии", "ответ прошлой версии") in texts
            assert ("новый вопрос", "новый ответ") in texts

            # Поиск по ответу тоже работает в старой схеме.
            assert repository.count("ответ прошлой версии") == 1

        # Схема не переписана: посторонняя колонка не появилась.
        assert _columns(db_file) == {"Id", "UserMessage", "JarvisResponse", "Timestamp"}


def test_new_database_uses_zere_column() -> None:
    """Новая база создаётся сразу с колонкой ZereResponse."""
    from zere.memory.database.conversation_repository import ConversationRepository
    from zere.memory.database.memory_database import MemoryDatabase

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        db_file = tmp / "fresh.db"

        with mock.patch("zere.paths.db_path", return_value=db_file):
            database = MemoryDatabase()
            repository = ConversationRepository(database)

            assert database.response_column == "ZereResponse", "новая база не на ZereResponse"

            repository.save("вопрос", "ответ")
            assert repository.count() == 1
            assert repository.get_last(1)[0].zere_response == "ответ"

        assert _columns(db_file) == {"Id", "UserMessage", "ZereResponse", "Timestamp"}


def test_empty_legacy_table_keeps_legacy_column() -> None:
    """Пустая старая таблица остаётся старой — имя колонки не подменяется."""
    from zere.memory.database.memory_database import MemoryDatabase

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        db_file = _legacy_database(tmp, with_row=False)

        with mock.patch("zere.paths.db_path", return_value=db_file):
            database = MemoryDatabase()

        assert database.response_column == "JarvisResponse"
        assert _columns(db_file) == {"Id", "UserMessage", "JarvisResponse", "Timestamp"}


def test_csharp_matches_python_detection() -> None:
    """C#-редакция содержит ту же логику определения колонки."""
    source = (
        ROOT / "ZERE.Memory" / "Database" / "MemoryDatabase.cs"
    ).read_text(encoding="utf-8")
    repository = (
        ROOT / "ZERE.Memory" / "Database" / "ConversationRepository.cs"
    ).read_text(encoding="utf-8")

    assert "PRAGMA table_info(Conversations)" in source, "нет определения схемы в C#"
    assert '"JarvisResponse"' in source, "C# не знает про старую колонку"
    assert "public string ResponseColumn" in source, "нет свойства ResponseColumn"
    assert "{ResponseColumn}" in repository, "C#-запросы не используют ResponseColumn"


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов совместимости базы")


if __name__ == "__main__":
    sys.exit(main())
