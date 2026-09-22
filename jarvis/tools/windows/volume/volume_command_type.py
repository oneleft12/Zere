"""Типы команд громкости (порт Windows/Volume/VolumeCommandType.cs)."""

from __future__ import annotations

from enum import Enum


class VolumeCommandType(Enum):
    NONE = 0
    SET_VOLUME = 1
    VOLUME_UP = 2
    VOLUME_DOWN = 3
    MUTE = 4
    UNMUTE = 5

    # Алиасы 1:1 с именами C#-членов (None в Python — зарезервировано).
    SetVolume = SET_VOLUME
    VolumeUp = VOLUME_UP
    VolumeDown = VOLUME_DOWN
    Mute = MUTE
    UnMute = UNMUTE
