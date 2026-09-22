"""Порт JARVIS.Core/Plugins/Interfaces/ICommandHandlerPlugin.cs."""

from __future__ import annotations

import abc

from jarvis.core.plugins.interfaces.plugin import IPlugin


class ICommandHandlerPlugin(IPlugin, abc.ABC):
    @property
    @abc.abstractmethod
    def supported_commands(self) -> list[str]:
        ...

    @abc.abstractmethod
    def can_handle(self, message: str) -> bool:
        ...

    @abc.abstractmethod
    def handle(self, message: str) -> str:
        ...
