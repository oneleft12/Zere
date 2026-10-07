"""ChatTTS — нейросетевой синтез речи (замена Piper TTS).

Публичный контракт:
    ChatTTSManager  — ленивая загрузка модели + синтез в WAV (эталонный код);
    ChatTtsService  — адаптер под контракт PiperService для VoiceManager.
"""

from zere.voice.chattts.chattts_manager import (
    BUILTIN_VOICES,
    DEFAULT_VOICE,
    SAMPLE_RATE,
    ChatTTSManager,
    ChatTtsUnavailable,
    split_sentences,
    strip_emotions,
)
from zere.voice.chattts.chattts_service import ChatTtsService

__all__ = [
    "BUILTIN_VOICES",
    "DEFAULT_VOICE",
    "SAMPLE_RATE",
    "ChatTTSManager",
    "ChatTtsService",
    "ChatTtsUnavailable",
    "split_sentences",
    "strip_emotions",
]
