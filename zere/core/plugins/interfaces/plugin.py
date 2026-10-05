"""Порт ZERE.Core/Plugins/Interfaces/IPlugin.cs (IPlugin + PluginType)."""

from __future__ import annotations

import abc
import enum


class PluginType(enum.Enum):
    Personality = 0
    CommandHandler = 1
    MemoryProvider = 2
    VoiceEngine = 3
    Other = 4


class IPlugin(abc.ABC):
    @property
    @abc.abstractmethod
    def id(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def version(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def author(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def type(self) -> PluginType:
        ...

    def initialize(self) -> None:
        """virtual void Initialize() { }"""

    def dispose(self) -> None:
        """virtual void Dispose() { }"""
