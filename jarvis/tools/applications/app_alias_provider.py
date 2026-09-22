"""Алиасы приложений (порт AppAliasProvider.cs — static class)."""

from __future__ import annotations

from typing import ClassVar


class AppAliasProvider:
    """Словарь алиасов: «дискорд» → «discord» и т.п."""

    # C#: public static readonly Dictionary<string, string> Aliases
    ALIASES: ClassVar[dict[str, str]] = {
        "дискорд": "discord",
        "discord": "discord",

        "телега": "telegram desktop",
        "телеграм": "telegram desktop",
        "telegram": "telegram desktop",

        "стим": "steam",
        "steam": "steam",

        "хром": "google chrome",
        "chrome": "google chrome",
        "гугл": "google chrome",
        "браузер": "google chrome",

        "код": "visual studio code",
        "vscode": "visual studio code",
        "vs code": "visual studio code",

        "эпик": "epic games launcher",
        "epic": "epic games launcher",

        "спотифай": "spotify",
        "spotify": "spotify",

        "риот": "riot client",
    }

    @classmethod
    def get_aliases(cls, app_name: str) -> list[str]:
        """Все алиасы, ведущие на указанное приложение (OrdinalIgnoreCase)."""
        return [
            key
            for key, value in cls.ALIASES.items()
            if value.lower() == app_name.lower()
        ]
