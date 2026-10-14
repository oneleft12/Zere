"""Порт ZERE.Core/Plugins/PluginManager.cs.

Assembly.LoadFrom(...) заменён на importlib.util.spec_from_file_location:
внешние плагины — это ./plugins/*.py (не *.dll), рекурсивно как SearchOption.AllDirectories.
"""

from __future__ import annotations

import enum
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import List, Optional

from zere import paths
from zere.core.plugins.builtin.personality.personality_plugin import PersonalityPlugin
from zere.core.plugins.interfaces.command_handler_plugin import ICommandHandlerPlugin
from zere.core.plugins.interfaces.personality_plugin import IPersonalityPlugin
from zere.core.plugins.interfaces.plugin import IPlugin, PluginType


def _enum_name(value: object) -> str:
    """System.Enum.ToString() -> имя члена без имени типа."""
    return value.name if isinstance(value, enum.Enum) else str(value)


def _built_in_modules() -> List[object]:
    """Модули, из которых собираются встроенные плагины.

    Раньше список был жёстко привязан к модулю личности
    (`PersonalityPlugin.__module__`), поэтому новый встроенный плагин
    не подхватывался, пока его не допишут сюда. Теперь модули перечислены
    явно: личность + MCP-плагины (браузер и заметки).

    Импорты внутри функции — чтобы не создавать цикл на импорте пакета
    плагинов и не тянуть MCP-модуль при простом `import plugin_manager`.
    """
    from zere.core.plugins.builtin.mcp.obsidian_plugin import ObsidianMcpPlugin
    from zere.core.plugins.builtin.mcp.playwright_plugin import PlaywrightMcpPlugin

    classes = (PersonalityPlugin, PlaywrightMcpPlugin, ObsidianMcpPlugin)
    modules: List[object] = []

    for plugin_class in classes:
        module_obj = sys.modules.get(plugin_class.__module__)
        if module_obj is not None and module_obj not in modules:
            modules.append(module_obj)

    return modules


class PluginManager:
    def __init__(self, plugins_path: Optional[str] = None) -> None:
        self._plugins_path: str = plugins_path if plugins_path is not None else str(paths.plugins_dir())

        Path(self._plugins_path).mkdir(parents=True, exist_ok=True)

        self._plugins: List[IPlugin] = []
        self._personalities: List[IPersonalityPlugin] = []
        self._command_handlers: List[ICommandHandlerPlugin] = []

        self.active_personality: Optional[IPersonalityPlugin] = None  # ActivePersonality { get; private set; }

    @property
    def plugins(self) -> List[IPlugin]:
        return list(self._plugins)

    @property
    def personalities(self) -> List[IPersonalityPlugin]:
        return list(self._personalities)

    @property
    def command_handlers(self) -> List[ICommandHandlerPlugin]:
        return list(self._command_handlers)

    def load_all(self) -> None:
        self._plugins.clear()
        self._personalities.clear()
        self._command_handlers.clear()

        self._load_built_in_plugins()

        # C#: Directory.GetFiles(_pluginsPath, "*.dll", SearchOption.AllDirectories)
        # → внешние плагины на Python: ./plugins/*.py рекурсивно
        plugin_files = sorted(Path(self._plugins_path).rglob("*.py"))

        for plugin_file in plugin_files:
            try:
                self.load_plugin(str(plugin_file))
            except Exception as ex:
                print(f"[PluginManager] Ошибка загрузки {plugin_file.name}: {ex}")

        print(f"[PluginManager] Всего загружено: {len(self._plugins)} плагинов.")

    def _load_built_in_plugins(self) -> None:
        # C#: Assembly.GetExecutingAssembly().GetTypes() — встроенные плагины текущей
        # сборки (ZERE.Core). На Python — классы IPlugin, объявленные во встроенных
        # модулях плагинов, без абстрактных и интерфейсов.
        built_in_modules = _built_in_modules()

        plugin_types: list[type] = []
        for module_obj in built_in_modules:
            if module_obj is None:
                continue

            plugin_types.extend(
                obj
                for _, obj in inspect.getmembers(module_obj, inspect.isclass)
                if obj.__module__ == module_obj.__name__
                and issubclass(obj, IPlugin)
                and not inspect.isabstract(obj)
            )

        for plugin_type in plugin_types:
            try:
                plugin: IPlugin = plugin_type()
                plugin.initialize()

                self._plugins.append(plugin)

                if isinstance(plugin, IPersonalityPlugin):
                    self._personalities.append(plugin)
                elif isinstance(plugin, ICommandHandlerPlugin):
                    self._command_handlers.append(plugin)

                print(
                    f"[PluginManager] Встроенный: {plugin.name} "
                    f"v{plugin.version} ({_enum_name(plugin.type)})"
                )
            except Exception as ex:
                print(
                    f"[PluginManager] Ошибка загрузки встроенного плагина "
                    f"{plugin_type.__name__}: {ex}"
                )

    def load_plugin(self, plugin_path: str) -> None:
        """C#: private void LoadPlugin(string dllPath) — Assembly.LoadFrom → importlib."""
        path = Path(plugin_path)

        module_name = f"zere_external_plugin_{path.stem}_{abs(hash(str(path.resolve())))}"

        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Не удалось создать спецификацию для {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        plugin_types = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            # obj.__module__ — СТРОКА, module — объект модуля: сравнение
            # «строка == объект» всегда ложно, поэтому внешние Python-плагины
            # не загружались вообще (P1-3). Нужно имя модуля.
            if obj.__module__ == module.__name__
            and issubclass(obj, IPlugin)
            and not inspect.isabstract(obj)
        ]

        for plugin_type in plugin_types:
            plugin: IPlugin = plugin_type()
            plugin.initialize()

            self._plugins.append(plugin)

            if isinstance(plugin, IPersonalityPlugin):
                self._personalities.append(plugin)
            elif isinstance(plugin, ICommandHandlerPlugin):
                self._command_handlers.append(plugin)

            print(
                f"[PluginManager] Загружен: {plugin.name} "
                f"v{plugin.version} ({_enum_name(plugin.type)})"
            )

    def set_active_personality(self, plugin_id: str, style_name: Optional[str] = None) -> bool:
        personality = next((p for p in self._personalities if p.id == plugin_id), None)

        if personality is None:
            return False

        if style_name is not None and style_name != "" and isinstance(personality, PersonalityPlugin):
            personality.set_initial_style(style_name)

        self.active_personality = personality
        style = personality.style
        print(
            f"[PluginManager] Активная личность: {personality.name} | "
            f"Стиль: {_enum_name(style)}"
        )
        return True

    def get_by_id(self, id_: str) -> Optional[IPlugin]:
        return next((p for p in self._plugins if p.id == id_), None)

    def get_by_type(self, type_: PluginType) -> List[IPlugin]:
        return [p for p in self._plugins if p.type == type_]

    def dispose_all(self) -> None:
        for plugin in self._plugins:
            try:
                plugin.dispose()
            except Exception as ex:
                print(f"[PluginManager] Ошибка выгрузки {plugin.name}: {ex}")

        self._plugins.clear()
        self._personalities.clear()
        self._command_handlers.clear()
