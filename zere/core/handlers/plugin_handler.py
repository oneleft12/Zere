"""Мост «сообщение → плагины-обработчики» (`ICommandHandlerPlugin`).

Зачем отдельный обработчик: `PluginManager` умеет собирать список
`command_handlers`, но конвейер о них не знал — плагины загружались, попадали
в счётчик панели и не получали ни одного сообщения (пункт P1-3 аудита,
флаг `handlersConnected: false`). Этот обработчик закрывает разрыв: он стоит
среди локальных (детерминированных) обработчиков, перед `AIHandler`, и отдаёт
сообщение первому плагину, который его узнал.

Порядок важен: плагины не должны перехватывать привычные команды, поэтому
мост стоит последним среди локальных — после памяти, процессов, файлов,
громкости и рисования.

**Сбой плагина не заслоняет остальные.** Если плагин упал в `can_handle`,
он просто не участвует в разборе. Если упал в `handle` — пробуем следующий
подходящий плагин, а сообщение об ошибке отдаём только тогда, когда ни один
не справился. Иначе один сломанный плагин отбирал бы команды у здоровых.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

from zere.core.handlers.i_zere_handler import IZereHandler
from zere.core.logging.log_service import log_error


class PluginCommandHandler(IZereHandler):
    """Раздаёт сообщения плагинам-обработчикам."""

    def __init__(self, plugin_manager: Any) -> None:
        self._plugin_manager = plugin_manager

    @property
    def plugin_manager(self) -> Any:
        return self._plugin_manager

    def _matching(self, message: str) -> Iterator[Any]:
        """Плагины, которые узнали сообщение, в порядке загрузки.

        Сбой `can_handle` одного плагина не должен ломать конвейер: плагины —
        сторонний код, и падение в них не повод не ответить пользователю.
        """
        for plugin in self._plugin_manager.command_handlers:
            try:
                if plugin.can_handle(message):
                    yield plugin
            except Exception as ex:  # noqa: BLE001 — плагин не должен ронять пайплайн
                log_error(
                    "PluginCommandHandler",
                    f"плагин {getattr(plugin, 'id', '?')} упал в can_handle: {ex}",
                )

    def can_handle(self, message: str) -> bool:
        return next(self._matching(message), None) is not None

    def handle(self, message: str) -> Optional[str]:
        failed: Optional[tuple[str, Exception]] = None

        for plugin in self._matching(message):
            plugin_id = str(getattr(plugin, "id", "?"))

            try:
                result = plugin.handle(message)
            except Exception as ex:  # noqa: BLE001 — показываем причину, не падаем
                log_error("PluginCommandHandler", f"плагин {plugin_id} упал в handle: {ex}")
                failed = (plugin_id, ex)
                continue

            # None = плагин не смог ответить → пробуем следующий.
            if result is not None:
                return result

        if failed is not None:
            plugin_id, error = failed
            return f"Плагин «{plugin_id}» не смог выполнить команду: {error}"

        return None


__all__ = ["PluginCommandHandler"]
