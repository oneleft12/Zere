"""Тесты подключения плагинов к конвейеру и их загрузки.

Закрывают пункт P1-3 аудита: `ICommandHandlerPlugin` загружался, но не
получал ни одного сообщения, а внешние Python-плагины не грузились вообще
из-за сравнения строки с объектом модуля.

Запуск: `python3 tests/test_plugin_pipeline.py` или `pytest tests/ -q`.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.core.handlers.handler_pipeline import HandlerPipeline  # noqa: E402
from zere.core.handlers.i_zere_handler import IZereHandler  # noqa: E402
from zere.core.handlers.plugin_handler import PluginCommandHandler  # noqa: E402
from zere.core.plugins.interfaces.plugin import PluginType  # noqa: E402
from zere.core.plugins.plugin_manager import PluginManager  # noqa: E402


class FakePlugin:
    """Плагин-обработчик с управляемым поведением."""

    def __init__(
        self,
        plugin_id: str = "fake",
        matches: str = "погода",
        answer: str = "солнечно",
        *,
        crash_in_can_handle: bool = False,
        crash_in_handle: bool = False,
        silent: bool = False,
    ) -> None:
        self._id = plugin_id
        self._matches = matches
        self._answer = answer
        self._crash_can_handle = crash_in_can_handle
        self._crash_handle = crash_in_handle
        self._silent = silent
        self.handled: list[str] = []

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._id

    @property
    def description(self) -> str:
        return "тестовый плагин"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "tests"

    @property
    def type(self) -> PluginType:
        return PluginType.CommandHandler

    @property
    def supported_commands(self) -> list[str]:
        return [self._matches]

    def initialize(self) -> None:
        return

    def dispose(self) -> None:
        return

    def can_handle(self, message: str) -> bool:
        if self._crash_can_handle:
            raise RuntimeError("сломался в can_handle")
        return self._matches in message.lower()

    def handle(self, message: str) -> Optional[str]:
        if self._crash_handle:
            raise RuntimeError("сломался в handle")
        self.handled.append(message)
        return None if self._silent else self._answer


class FakeManager:
    """Минимальный PluginManager: только список обработчиков."""

    def __init__(self, handlers: list[Any]) -> None:
        self.command_handlers = handlers


class NeverHandler(IZereHandler):
    def can_handle(self, message: str) -> bool:
        return False

    def handle(self, message: str) -> Optional[str]:
        return None


class FallbackHandler(IZereHandler):
    """Обработчик-«ИИ»: отвечает на всё."""

    def can_handle(self, message: str) -> bool:
        return True

    def handle(self, message: str) -> Optional[str]:
        return f"ИИ: {message}"


# ── Мост «сообщение → плагин» ──────────────────────────────────────


def test_plugin_receives_message() -> None:
    plugin = FakePlugin()
    handler = PluginCommandHandler(FakeManager([plugin]))

    assert handler.can_handle("какая погода") is True
    assert handler.handle("какая погода") == "солнечно"
    assert plugin.handled == ["какая погода"]


def test_plugin_ignores_foreign_messages() -> None:
    handler = PluginCommandHandler(FakeManager([FakePlugin()]))

    assert handler.can_handle("включи музыку") is False
    assert handler.handle("включи музыку") is None


def test_first_matching_plugin_wins() -> None:
    first = FakePlugin("first", answer="первый")
    second = FakePlugin("second", answer="второй")
    handler = PluginCommandHandler(FakeManager([first, second]))

    assert handler.handle("погода") == "первый"
    assert second.handled == [], "второй плагин не должен вызываться"


def test_broken_plugin_does_not_break_pipeline() -> None:
    """Падение в can_handle и в handle — не повод не ответить пользователю."""
    crashing = FakePlugin("bad", crash_in_can_handle=True)
    crashing_handle = FakePlugin("bad2", matches="новости", crash_in_handle=True)
    good = FakePlugin("good", matches="новости", answer="ок")
    handler = PluginCommandHandler(FakeManager([crashing, crashing_handle, good]))

    assert handler.can_handle("погода") is False, "упавший плагин просто не подошёл"

    answer = handler.handle("новости")
    assert answer == "ок", "после упавшего плагина должен ответить следующий"


def test_crashing_handle_reports_reason() -> None:
    handler = PluginCommandHandler(FakeManager([FakePlugin(crash_in_handle=True)]))
    answer = handler.handle("погода")

    assert answer is not None
    assert "не смог выполнить команду" in answer
    assert "сломался в handle" in answer


def test_silent_plugin_falls_through_to_ai() -> None:
    """Плагин вернул None → сообщение доходит до ИИ, как раньше."""
    silent = FakePlugin(silent=True)
    pipeline = HandlerPipeline(
        [NeverHandler(), PluginCommandHandler(FakeManager([silent])), FallbackHandler()]
    )

    assert pipeline.handle("погода") == "ИИ: погода"
    assert silent.handled == ["погода"], "плагин обязан получить сообщение"


def test_plugin_slot_is_before_ai_in_pipeline() -> None:
    """Плагин отвечает раньше ИИ — иначе смысла в нём нет."""
    plugin = FakePlugin(answer="из плагина")
    pipeline = HandlerPipeline(
        [PluginCommandHandler(FakeManager([plugin])), FallbackHandler()]
    )

    assert pipeline.handle("погода") == "из плагина"


# ── Загрузка плагинов ──────────────────────────────────────────────


def test_builtin_mcp_plugins_are_loaded() -> None:
    """Встроенные MCP-плагины обязаны попадать в PluginManager.

    Раньше список встроенных модулей был жёстко привязан к модулю личности,
    и новый встроенный плагин не подхватывался.
    """
    with tempfile.TemporaryDirectory() as td:
        manager = PluginManager(plugins_path=td)
        manager.load_all()

    ids = [plugin.id for plugin in manager.plugins]

    assert "personality" in ids
    assert "playwright-mcp" in ids
    assert "obsidian-mcp" in ids

    handler_ids = [plugin.id for plugin in manager.command_handlers]
    assert "playwright-mcp" in handler_ids
    assert "obsidian-mcp" in handler_ids


def test_external_python_plugin_is_loaded() -> None:
    """Внешний плагин из ./plugins/*.py грузится.

    Регрессия: `obj.__module__ == module` сравнивал строку с объектом модуля,
    поэтому внешние Python-плагины не загружались НИКОГДА.
    """
    plugin_source = '''
"""Внешний тестовый плагин."""

from zere.core.plugins.interfaces.plugin import IPlugin, PluginType


class ExternalDemoPlugin(IPlugin):
    @property
    def id(self) -> str:
        return "external-demo"

    @property
    def name(self) -> str:
        return "Внешний демо-плагин"

    @property
    def description(self) -> str:
        return "Плагин из каталога plugins/"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def author(self) -> str:
        return "tests"

    @property
    def type(self) -> PluginType:
        return PluginType.Other
'''

    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "demo_plugin.py").write_text(plugin_source, encoding="utf-8")

        manager = PluginManager(plugins_path=td)
        manager.load_all()

    ids = [plugin.id for plugin in manager.plugins]
    assert "external-demo" in ids, f"внешний плагин не загрузился, есть: {ids}"


def test_external_plugin_goes_into_command_handlers() -> None:
    """Внешний плагин-обработчик попадает в список обработчиков."""
    plugin_source = '''
"""Внешний плагин-обработчик."""

from zere.core.plugins.interfaces.command_handler_plugin import ICommandHandlerPlugin
from zere.core.plugins.interfaces.plugin import PluginType


class ExternalHandlerPlugin(ICommandHandlerPlugin):
    @property
    def id(self) -> str:
        return "external-handler"

    @property
    def name(self) -> str:
        return "Внешний обработчик"

    @property
    def description(self) -> str:
        return "Обработчик из plugins/"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def author(self) -> str:
        return "tests"

    @property
    def type(self) -> PluginType:
        return PluginType.CommandHandler

    @property
    def supported_commands(self) -> list[str]:
        return ["привет"]

    def can_handle(self, message: str) -> bool:
        return message.strip().lower() == "привет"

    def handle(self, message: str) -> str:
        return "привет из внешнего плагина"
'''

    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "external_handler.py").write_text(plugin_source, encoding="utf-8")

        manager = PluginManager(plugins_path=td)
        manager.load_all()

        handler = PluginCommandHandler(manager)
        answer = handler.handle("привет")

    assert answer == "привет из внешнего плагина"


def test_plugin_handlers_connected_reflects_pipeline() -> None:
    """`handlersConnected` в API — про конвейер, а не про список плагинов.

    Раньше флаг был жёстко `false`; теперь он честный: у движка с мостом
    плагинов — true, у движка без конвейера — false.
    """
    from zere.api.server import _plugin_handlers_connected

    class EngineWithBridge:
        pipeline = HandlerPipeline(
            [PluginCommandHandler(FakeManager([FakePlugin()])), FallbackHandler()]
        )

    class EngineWithoutBridge:
        pipeline = HandlerPipeline([NeverHandler(), FallbackHandler()])

    class EngineWithoutPipeline:
        pass

    assert _plugin_handlers_connected(EngineWithBridge()) is True
    assert _plugin_handlers_connected(EngineWithoutBridge()) is False
    assert _plugin_handlers_connected(EngineWithoutPipeline()) is False


def test_pipeline_contains_finds_handler_type() -> None:
    bridge = PluginCommandHandler(FakeManager([]))
    pipeline = HandlerPipeline([NeverHandler(), bridge])

    assert pipeline.contains(PluginCommandHandler) is True
    assert pipeline.contains(FallbackHandler) is False
    assert len(pipeline.handlers) == 2


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]

    for test in tests:
        test()
        print(f"OK  {test.__name__}")

    print(f"ПРОЙДЕНО: {len(tests)} тестов плагинов в конвейере")

if __name__ == "__main__":
    main()
