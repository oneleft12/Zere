"""Разбор фраз «включи музыку на ютубе» и управление воспроизведением.

Роутер только распознаёт намерение — ничего не запускает. Сторона исполнения
живёт в `YouTubeService` (браузер Playwright MCP или браузер по умолчанию),
поэтому фразы можно проверять без сети и без браузера.

Почему фразы собраны здесь, а не в Playwright-плагине: «открыть ютуб» и
«включить музыку» — пользовательские команды, а не управление браузером.
Плагин остаётся драйвером, который умеет выполнить JS на странице.
"""

from __future__ import annotations

import re
from typing import Optional

from zere.tools.media.youtube_command import (
    DEFAULT_QUERY,
    NEXT,
    OPEN,
    PAUSE,
    PLAY,
    PREVIOUS,
    RESUME,
    STATUS,
    YouTubeCommand,
)

_SPACES_RE = re.compile(r"\s+")
_TRAILING_PUNCTUATION_RE = re.compile(r"[.!?,;:]+$")

#: Слова, после которых фраза перестаёт быть командой музыки: «включи
#: музыку громче» — это громкость, а не запрос «громче».
_VOLUME_WORDS = ("громче", "тише", "погромче", "потише", "громкость", "звук")

_PAUSE_PHRASES = frozenset(
    {
        "пауза",
        "поставь на паузу",
        "поставить на паузу",
        "приостанови",
        "приостанови музыку",
        "останови музыку",
        "выключи музыку",
        "стоп музыка",
        "стоп музыку",
        "pause",
        "pause music",
    }
)

_RESUME_PHRASES = frozenset(
    {
        "продолжи",
        "продолжить",
        "продолжи музыку",
        "сними с паузы",
        "включи обратно",
        "играй дальше",
        "resume",
        "unpause",
    }
)

_NEXT_PHRASES = frozenset(
    {
        "следующий трек",
        "следующая песня",
        "следующий",
        "следующая",
        "переключи трек",
        "переключи на следующий",
        "next",
        "next track",
    }
)

_PREVIOUS_PHRASES = frozenset(
    {
        "предыдущий трек",
        "предыдущая песня",
        "предыдущий",
        "предыдущая",
        "верни трек",
        "previous",
        "previous track",
    }
)

_STATUS_PHRASES = frozenset(
    {
        "что играет",
        "что сейчас играет",
        "какая музыка играет",
        "какой трек играет",
        "что за трек",
        "что за песня",
        "what is playing",
        "what's playing",
        "what song is playing",
    }
)

_OPEN_PHRASES = frozenset(
    {
        "ютуб",
        "youtube",
        "ютюб",
        "открой ютуб",
        "открой youtube",
        "открой ютюб",
        "открыть ютуб",
        "запусти ютуб",
        "запусти youtube",
        "включи ютуб",
        "включи youtube",
        "open youtube",
    }
)

#: «Включи музыку» без уточнения — отдельные точные фразы.
_PLAY_DEFAULT_PHRASES = frozenset(
    {
        "включи музыку",
        "включи музыка",
        "вруби музыку",
        "поставь музыку",
        "включи ютуб музыку",
        "включи музыку ютуб",
        "ютуб музыка",
        "youtube music",
        "включи музыку на ютубе",
        "поставь музыку на ютубе",
        "play music",
        "play music on youtube",
    }
)

#: Глаголы, с которых начинается «включи <запрос> на ютубе».
_PLAY_VERBS = ("включи", "поставь", "вруби", "запусти", "play")

#: Как пользователь называет площадку в конце фразы.
_YOUTUBE_SUFFIXES = (" на ютубе", " на youtube", " в ютубе", " youtube")

#: Слова «музыка» рядом с глаголом: «включи музыку джаз» → запрос «джаз».
_MUSIC_WORDS = ("музыку", "музыка", "music")


def _normalize(message: str) -> str:
    """Нижний регистр, один пробел, без хвостовой пунктуации."""
    text = _SPACES_RE.sub(" ", message.strip().lower())
    text = _TRAILING_PUNCTUATION_RE.sub("", text)

    for filler in ("пожалуйста", "давай", "ну "):
        if text.startswith(filler):
            text = text[len(filler) :].strip()
        text = text.replace(f" {filler}", "")

    text = _TRAILING_PUNCTUATION_RE.sub("", text.strip())

    return _SPACES_RE.sub(" ", text).strip()


def _strip_verb(text: str) -> Optional[str]:
    """Убирает первый глагол: «включи джаз» → «джаз»."""
    for verb in _PLAY_VERBS:
        if text == verb:
            return ""
        if text.startswith(verb + " "):
            return text[len(verb) :].strip()
    return None


def _strip_music_word(text: str) -> str:
    """Убирает «музыку»: «музыку джаз» → «джаз», «музыку» → «»."""
    for word in _MUSIC_WORDS:
        if text == word:
            return ""
        if text.startswith(word + " "):
            return text[len(word) :].strip()
    return text


def _looks_like_volume(text: str) -> bool:
    """Фраза про громкость, а не про выбор музыки."""
    return any(word in text for word in _VOLUME_WORDS)


def _parse_play(text: str) -> Optional[YouTubeCommand]:
    """«включи музыку [запрос]», «включи <запрос> на ютубе»."""
    if text in _PLAY_DEFAULT_PHRASES:
        return YouTubeCommand(PLAY)

    # «включи на ютубе джаз» / «поставь на ютубе лофай».
    for verb in _PLAY_VERBS:
        prefix = f"{verb} на ютубе "
        if text.startswith(prefix):
            query = text[len(prefix) :].strip()
            if query and not _looks_like_volume(query):
                return YouTubeCommand(PLAY, query)
            return None

    # «включи джаз на ютубе» / «поставь лофай на youtube».
    for suffix in _YOUTUBE_SUFFIXES:
        if not text.endswith(suffix):
            continue

        head = text[: -len(suffix)].strip()
        if not head:
            continue

        rest = _strip_verb(head)
        if rest is None:
            continue

        # «включи youtube» — это открыть сайт, а не включить музыку.
        if not rest:
            continue

        rest = _strip_music_word(rest)
        if rest and not _looks_like_volume(rest):
            return YouTubeCommand(PLAY, rest)
        return YouTubeCommand(PLAY) if not rest else None

    # «включи музыку джаз» — площадка не названа, но музыка очевидна.
    for verb in _PLAY_VERBS:
        prefix = f"{verb} музыку "
        if text.startswith(prefix):
            query = text[len(prefix) :].strip()
            if query and not _looks_like_volume(query):
                return YouTubeCommand(PLAY, query)
            return None

    return None


class YouTubeCommandRouter:
    """Распознаёт команды YouTube; `None` — это не наша фраза."""

    def parse(self, message: str) -> Optional[YouTubeCommand]:
        text = _normalize(message)

        if not text:
            return None

        if text in _PAUSE_PHRASES:
            return YouTubeCommand(PAUSE)

        if text in _RESUME_PHRASES:
            return YouTubeCommand(RESUME)

        if text in _NEXT_PHRASES:
            return YouTubeCommand(NEXT)

        if text in _PREVIOUS_PHRASES:
            return YouTubeCommand(PREVIOUS)

        if text in _STATUS_PHRASES:
            return YouTubeCommand(STATUS)

        play = _parse_play(text)

        if play is not None:
            return play

        if text in _OPEN_PHRASES:
            return YouTubeCommand(OPEN)

        return None


__all__ = ["YouTubeCommandRouter", "DEFAULT_QUERY"]
