"""Порт ZERE.Core/Plugins/BuiltIn/Personality/PersonalityPlugin.cs."""

from __future__ import annotations

import enum

from zere.core.plugins.base_plugin import BasePlugin
from zere.core.plugins.interfaces.personality_plugin import (
    IPersonalityPlugin,
    PersonalityStyle,
)
from zere.core.plugins.interfaces.plugin import PluginType


def _enum_name(value: object) -> str:
    """System.Enum.ToString() -> имя члена без имени типа."""
    return value.name if isinstance(value, enum.Enum) else str(value)


class PersonalityPlugin(BasePlugin, IPersonalityPlugin):
    @property
    def id(self) -> str:
        return "personality"

    @property
    def name(self) -> str:
        return "Личность ZERE"

    @property
    def description(self) -> str:
        return "Встроенные стили общения ассистента"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "ZERE"

    @property
    def type(self) -> PluginType:
        return PluginType.Personality

    def __init__(self) -> None:
        self._current_style: PersonalityStyle = PersonalityStyle.Friendly

        self._prompts: dict[PersonalityStyle, str] = {
            PersonalityStyle.Friendly: (
                "Ты — ZERE, дружелюбный AI-ассистент.\n"
                "Общайся тепло, изредка используй смайлики.\n"
                "Будь как друг — помогай с радостью.\n"
                "Говори просто и понятно."
            ),
            PersonalityStyle.Formal: (
                "Ты — ZERE, официальный AI-ассистент.\n"
                "Общайся строго, профессионально.\n"
                "Используй вежливую форму общения.\n"
                "Не используй смайлики."
            ),
            PersonalityStyle.Sarcastic: (
                "Ты — ZERE, саркастичный AI-ассистент.\n"
                "Отвечай с умным юмором и иронией.\n"
                "Поддразнивай пользователя, но оставайся полезным.\n"
                "Будь как умный друг, который шутит."
            ),
            PersonalityStyle.Professional: (
                "Ты — ZERE, профессиональный AI-ассистент.\n"
                "Общайся по делу, без лишних слов.\n"
                "Давай точные и структурированные ответы.\n"
                "Фокусируйся на эффективности."
            ),
            PersonalityStyle.Casual: (
                'Ты — ZERE, неформальный AI-ассистент.\n'
                'Общайся как с другом, на "ты".\n'
                "Используй разговорные фразы.\n"
                "Будь расслабленным и весёлым."
            ),
            PersonalityStyle.Custom: (
                "Ты — ZERE, настроенный ассистент.\n"
                "Следуй кастомным инструкциям из конфигурации."
            ),
        }

        self._temperatures: dict[PersonalityStyle, float] = {
            PersonalityStyle.Friendly: 0.7,
            PersonalityStyle.Formal: 0.3,
            PersonalityStyle.Sarcastic: 0.9,
            PersonalityStyle.Professional: 0.4,
            PersonalityStyle.Casual: 0.8,
            PersonalityStyle.Custom: 0.7,
        }

    @property
    def system_prompt(self) -> str:
        return self._prompts[self._current_style]

    @property
    def temperature(self) -> float:
        return self._temperatures[self._current_style]

    @property
    def style(self) -> PersonalityStyle:
        return self._current_style

    def get_available_styles(self) -> list[str]:
        # Enum.GetNames<PersonalityStyle>().Where(s => s != "Custom")
        return [name for name in PersonalityStyle.__members__ if name != "Custom"]

    def set_style(self, style_name: str) -> None:
        style = self._parse_style(style_name)

        if style is not None:
            self._current_style = style
            print(f"[Personality] Стиль изменён на: {style_name}")
        else:
            print(f"[Personality] Неизвестный стиль: {style_name}")

    def set_initial_style(self, style_name: str) -> None:
        # Enum.TryParse<PersonalityStyle>(styleName, true, ...) — без вывода в консоль
        style = self._parse_style(style_name)

        if style is not None:
            self._current_style = style

    def set_custom_prompt(self, prompt: str) -> None:
        self._prompts[PersonalityStyle.Custom] = prompt
        self._current_style = PersonalityStyle.Custom

    def initialize(self) -> None:
        print(f"[Personality] Инициализирован. Текущий стиль: {_enum_name(self._current_style)}")

    def dispose(self) -> None:
        print("[Personality] Выгружен.")

    @staticmethod
    def _parse_style(style_name: str) -> PersonalityStyle | None:
        """Enum.TryParse<PersonalityStyle>(styleName, ignoreCase: true, out ...)."""
        if style_name is None:
            return None

        for member in PersonalityStyle:
            if member.name.lower() == style_name.lower():
                return member

        return None
