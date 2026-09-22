"""Парсер команд громкости (порт Windows/Volume/VolumeCommandRouter.cs)."""

from __future__ import annotations

import re
from typing import NamedTuple

from jarvis.tools.windows.volume.volume_command_type import VolumeCommandType

# Regex.Match(text, @"(громкость|звук[а]?|volume)\s+(\d{1,3})")
_VOLUME_PATTERN = re.compile(r"(громкость|звук[а]?|volume)\s+(\d{1,3})")


class ParsedVolumeCommand(NamedTuple):
    """C#-кортеж (VolumeCommandType Type, int Value)."""

    type: VolumeCommandType
    value: int


class VolumeCommandRouter:
    def parse(self, message: str) -> ParsedVolumeCommand:
        text = message.lower().strip()

        # === Установка конкретного значения ===
        # "громкость 50", "звука 75", "volume 80"
        match = _VOLUME_PATTERN.search(text)
        if match:
            value = int(match.group(2))
            # Math.Clamp(value, 0, 100)
            value = max(0, min(100, value))
            return ParsedVolumeCommand(VolumeCommandType.SET_VOLUME, value)

        # === Увеличение громкости ===
        if (
            "сделай громче" in text
            or "громче" in text
            or "прибавь звук" in text
            or "прибавь громкость" in text
            or "увеличь громкость" in text
            or "погромче" in text
            or "громкость вверх" in text
            or "звук вверх" in text
            or "больше звука" in text
        ):
            return ParsedVolumeCommand(VolumeCommandType.VOLUME_UP, 10)

        # === Уменьшение громкости ===
        if (
            "сделай тише" in text
            or "тише" in text
            or "убавь звук" in text
            or "убавь громкость" in text
            or "уменьши громкость" in text
            or "потише" in text
            or "громкость вниз" in text
            or "звук вниз" in text
            or "меньше звука" in text
        ):
            return ParsedVolumeCommand(VolumeCommandType.VOLUME_DOWN, 10)

        # === Выключение звука ===
        if (
            "выключи звук" in text
            or "замути" in text
            or "без звука" in text
            or "приглуши" in text
            or "mute" in text
            or "mute звук" in text
            or "выключи звуки" in text
        ):
            return ParsedVolumeCommand(VolumeCommandType.MUTE, 0)

        # === Включение звука ===
        if (
            "включи звук" in text
            or "размути" in text
            or "верни звук" in text
            or "включи звуки" in text
            or "unmute" in text
            or "unmute звук" in text
        ):
            return ParsedVolumeCommand(VolumeCommandType.UNMUTE, 0)

        return ParsedVolumeCommand(VolumeCommandType.NONE, 0)
