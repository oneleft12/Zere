"""Порт ZERE.Core/Plugins/Interfaces/IPersonalityPlugin.cs (IPersonalityPlugin + PersonalityStyle)."""

from __future__ import annotations

import abc
import enum

from zere.core.plugins.interfaces.plugin import IPlugin


class PersonalityStyle(enum.Enum):
    Friendly = 0
    Formal = 1
    Sarcastic = 2
    Professional = 3
    Casual = 4
    Custom = 5


class IPersonalityPlugin(IPlugin, abc.ABC):
    @property
    @abc.abstractmethod
    def system_prompt(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def temperature(self) -> float:
        ...

    @property
    @abc.abstractmethod
    def style(self) -> PersonalityStyle:
        ...

    @abc.abstractmethod
    def get_available_styles(self) -> list[str]:
        ...

    @abc.abstractmethod
    def set_style(self, style_name: str) -> None:
        ...
