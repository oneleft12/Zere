"""Silero TTS v5 — русский нейросетевой синтез речи.

Публичный контракт:
    SileroManager   — ленивая загрузка модели + синтез в WAV;
    SileroTtsService — адаптер под общий контракт TTS.

Движок задаётся ключом `ttsEngine` в config.json. Python-редакция умеет
только `silero` (русский, с ударениями); ChatTTS удалён, `pocket`
(клонирование голоса) есть только в C#-редакции.
"""

from zere.voice.silero.silero_manager import (
    BUILTIN_VOICES,
    DEFAULT_VOICE,
    MODEL_FILENAME,
    MODEL_ID,
    MODEL_URL,
    SAMPLE_RATE,
    SileroManager,
    SileroUnavailable,
    split_sentences,
    strip_emotions,
)
from zere.voice.silero.silero_service import SileroTtsService
from zere.voice.silero.silero_text import normalize

__all__ = [
    "BUILTIN_VOICES",
    "DEFAULT_VOICE",
    "MODEL_FILENAME",
    "MODEL_ID",
    "MODEL_URL",
    "SAMPLE_RATE",
    "SileroManager",
    "SileroTtsService",
    "SileroUnavailable",
    "normalize",
    "split_sentences",
    "strip_emotions",
]
