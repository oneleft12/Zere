"""Обработчик «YouTube и музыка» (только Python-редакция).

Стоит перед `WindowsHandler`: «открой ютуб» иначе уходит в поиск приложений и
заканчивается «Не удалось найти приложение». Фразы разбирает
`YouTubeCommandRouter`, исполняет `YouTubeService`; сам обработчик ничего не
запускает, поэтому его легко тестировать.
"""

from __future__ import annotations

from typing import Optional

from zere.core.handlers.i_zere_handler import IZereHandler
from zere.tools.media.youtube_command import (
    NEXT,
    OPEN,
    PAUSE,
    PLAY,
    PREVIOUS,
    RESUME,
    STATUS,
)
from zere.tools.media.youtube_command_router import YouTubeCommandRouter
from zere.tools.media.youtube_service import YouTubeService


class MediaHandler(IZereHandler):
    def __init__(self, service: YouTubeService) -> None:
        self._service = service
        self._router = YouTubeCommandRouter()

    def can_handle(self, message: str) -> bool:
        return self._router.parse(message) is not None

    def handle(self, message: str) -> Optional[str]:
        command = self._router.parse(message)

        if command is None:
            return None

        if command.kind == OPEN:
            return self._service.open_youtube()

        if command.kind == PLAY:
            return self._service.play_music(command.query)

        if command.kind in (PAUSE, RESUME, NEXT, PREVIOUS, STATUS):
            return self._service.control(command.kind)

        return None


__all__ = ["MediaHandler"]
