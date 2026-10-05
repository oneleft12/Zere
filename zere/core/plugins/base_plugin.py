"""Порт ZERE.Core/Plugins/BasePlugin.cs."""

from __future__ import annotations

import abc

from zere.core.plugins.interfaces.plugin import IPlugin, PluginType


class BasePlugin(IPlugin, abc.ABC):
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
        """Кастомный паттерн очистки ресурсов плагина. Не реализует System.IDisposable напрямую —
        управляется PluginManager.dispose_all() при перезагрузке/выключении.
        """

        # virtual void Dispose() { }
        return
