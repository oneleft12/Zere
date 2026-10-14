"""Silero TTS v5 — русский нейросетевой синтез речи.

Публичный контракт:
    SileroManager   — ленивая загрузка модели + синтез в WAV;
    SileroTtsService — адаптер под контракт PiperService/ChatTtsService.

Движок выбирается ключом `ttsEngine` в config.json: `chattts` (китайский/
английский, «человечный» тембр) или `silero` (русский, с ударениями).
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
