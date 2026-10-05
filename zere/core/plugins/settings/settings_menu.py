"""Порт ZERE.Core/Plugins/Settings/SettingsMenu.cs."""

from __future__ import annotations

import enum
import os
from typing import List, Optional

from zere.core.configuration.zere_config import ZereConfig
from zere.core.plugins.plugin_config import PluginConfig
from zere.core.plugins.plugin_manager import PluginManager


def _enum_name(value: object) -> str:
    """System.Enum.ToString() -> имя члена без имени типа."""
    return value.name if isinstance(value, enum.Enum) else str(value)


def _console_clear() -> None:
    """Console.Clear()."""
    os.system("cls" if os.name == "nt" else "clear")


def _read_choice() -> Optional[str]:
    """Console.ReadLine()?.Trim()."""
    try:
        return input().strip()
    except EOFError:
        return None


def _pause() -> None:
    """Console.ReadLine() — ожидание Enter (без Trim)."""
    try:
        input()
    except EOFError:
        return


def _try_parse_int(text: Optional[str]) -> Optional[int]:
    """int.TryParse(...)."""
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


class SettingsMenu:
    def __init__(self, plugin_manager: PluginManager, config: PluginConfig) -> None:
        self._plugin_manager = plugin_manager
        self._config = config

    def show(self) -> None:
        while True:
            _console_clear()
            print("╔══════════════════════════════════════╗")
            print(f"║       НАСТРОЙКИ ZERE v{ZereConfig.load().Version}          ║")
            print("╠══════════════════════════════════════╣")
            print("║  1. Личность ассистента            ║")
            print("║  2. Плагины                        ║")
            print("║  3. Конфигурация                   ║")
            print("║  4. О плагинах                     ║")
            print("║  0. Выход                          ║")
            print("╚══════════════════════════════════════╝")
            print("\nВыберите пункт: ", end="")

            choice = _read_choice()

            if choice == "1":
                self._show_personality_menu()
            elif choice == "2":
                self._show_plugins_menu()
            elif choice == "3":
                self._show_config_menu()
            elif choice == "4":
                self._show_about_plugins()
            elif choice == "0":
                return

    def _show_personality_menu(self) -> None:
        personality = self._plugin_manager.active_personality

        while True:
            _console_clear()
            print("╔══════════════════════════════════════╗")
            current_style = _enum_name(personality.style) if personality is not None else "Не задан"
            print(f"║  Текущий стиль: {current_style}")
            print("╠══════════════════════════════════════╣")

            personalities = self._plugin_manager.personalities
            index = 1

            for p in personalities:
                for style in p.get_available_styles():
                    is_active = " [АКТИВЕН]" if current_style == style else ""
                    print(f"║  {index}. {style}{is_active}")
                    index += 1

            print("╠══════════════════════════════════════╣")
            print("║  0. Назад                          ║")
            print("╚══════════════════════════════════════╝")
            print("\nВыберите стиль: ", end="")

            choice = _read_choice()

            if choice == "0":
                return

            num = _try_parse_int(choice)

            if num is not None and num > 0 and num <= index - 1:
                all_styles: List[str] = []
                for p in personalities:
                    all_styles.extend(p.get_available_styles())

                selected_style = all_styles[num - 1]

                for p in personalities:
                    available_styles = p.get_available_styles()

                    if selected_style in available_styles:
                        p.set_style(selected_style)
                        self._plugin_manager.set_active_personality(p.id)
                        # P1-3: без сохранения стиля он сбрасывался при рестарте
                        self._config.ActivePersonalityId = p.id
                        self._config.ActivePersonalityStyle = selected_style

                PluginConfig.save(self._config)

                print(f"\nСтиль изменён на: {selected_style}")
                print("Нажмите Enter для продолжения...")
                _pause()

    def _show_plugins_menu(self) -> None:
        while True:
            _console_clear()
            print("╔══════════════════════════════════════╗")
            print("║           ПЛАГИНЫ                  ║")
            print("╠══════════════════════════════════════╣")

            plugins = self._plugin_manager.plugins
            index = 1

            for plugin in plugins:
                print(f"║  {index}. {plugin.name} v{plugin.version}")
                print(f"║     Тип: {_enum_name(plugin.type)} | Автор: {plugin.author}")
                index += 1

            if len(plugins) == 0:
                print("║  Плагины не загружены               ║")

            print("╠══════════════════════════════════════╣")
            print("║  R. Перезагрузить плагины          ║")
            print("║  0. Назад                          ║")
            print("╚══════════════════════════════════════╝")
            print("\nВыберите действие: ", end="")

            choice = _read_choice()

            if choice == "0":
                return

            if choice is not None and choice.lower() == "r":
                self._plugin_manager.dispose_all()
                self._plugin_manager.load_all()
                print("Плагины перезагружены. Нажмите Enter...")
                _pause()

    def _show_config_menu(self) -> None:
        while True:
            _console_clear()
            print("╔══════════════════════════════════════╗")
            print("║        КОНФИГУРАЦИЯ                ║")
            print("╠══════════════════════════════════════╣")
            print(f"║  Активная личность: {self._config.ActivePersonalityId}")
            print(f"║  Настроек плагинов: {len(self._config.PluginSettings)}")
            print("╠══════════════════════════════════════╣")
            print("║  0. Назад                          ║")
            print("╚══════════════════════════════════════╝")
            print("\nНажмите Enter для возврата...", end="")
            _pause()
            return

    def _show_about_plugins(self) -> None:
        _console_clear()
        print("╔══════════════════════════════════════╗")
        print("║       О ПЛАГИНАХ                   ║")
        print("╠══════════════════════════════════════╣")
        print("║  Плагины загружаются из папки      ║")
        print("║  ./plugins/                        ║")
        print("║                                    ║")
        print("║  Формат: .dll файлы               ║")
        print("║  Интерфейсы:                       ║")
        print("║  - IPersonalityPlugin              ║")
        print("║  - ICommandHandlerPlugin           ║")
        print("║                                    ║")
        print("║  Настройки применяются к началу   ║")
        print("║  сессии. Внутри сессии нельзя     ║")
        print("║  менять стиль.                     ║")
        print("╚══════════════════════════════════════╝")
        print("\nНажмите Enter для возврата...", end="")
        _pause()
