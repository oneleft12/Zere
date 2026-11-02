"""Команда «YouTube и музыка»: что именно просит пользователь.

Отдельный тип, чтобы сервис и обработчик не разбирали фразу дважды: роутер
превращает свободную формулировку в одну из восьми команд, а исполнение
остаётся в `YouTubeService`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Открыть YouTube (без воспроизведения).
OPEN = "open"
#: Включить музыку: пустой `query` — подставить запрос по умолчанию.
PLAY = "play"
PAUSE = "pause"
RESUME = "resume"
NEXT = "next"
PREVIOUS = "previous"
STATUS = "status"

#: Запрос для «включи музыку» без уточнения.
DEFAULT_QUERY = "музыка"

#: Какие ещё действия понимает сервис (для проверок и сообщений).
ACTIONS = (PAUSE, RESUME, NEXT, PREVIOUS, STATUS)


@dataclass(frozen=True)
class YouTubeCommand:
    """Разобранная команда: действие и (для `play`) поисковый запрос."""

    kind: str
    query: str = ""
