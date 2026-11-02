"""Автозапуск ZERE вместе с Windows (Python-редакция).

Одна запись в пользовательском разделе реестра
``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`` — без прав
администратора и без службы: Windows запускает приложение при входе
пользователя в систему.

Состояние читается из реестра, а не из ``config.json``: источник истины —
сама Windows (запись могли удалить Task Manager'ом или другой установкой).
Отключение — удаление записи, поэтому функция обратима и ничего не оставляет
после удаления приложения.

Панель: экран «Настройки» → карточка «Запуск вместе с Windows»;
API: ``GET|POST /api/autostart`` (docs/api/openapi.yaml).
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

from zere import paths

#: Раздел реестра, который просматривает Windows при входе пользователя.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
#: Имя значения: видно в «Диспетчере задач» → «Автозагрузка».
VALUE_NAME = "ZERE"
#: Человекочитаемое место записи (в ответе API и подписи в панели).
LOCATION = rf"HKCU\{RUN_KEY}"


class AutostartError(RuntimeError):
    """Автозапуск не удалось прочитать или изменить."""


class AutostartUnsupportedError(AutostartError):
    """Платформа не Windows — автозапуск недоступен."""


class AutostartBackend(Protocol):
    """Хранилище записи автозапуска (реестр; в тестах — фейк)."""

    def read(self) -> Optional[str]:
        """Команда из записи или None, если записи нет."""

    def write(self, command: str) -> None:
        """Создать/перезаписать запись."""

    def delete(self) -> None:
        """Удалить запись (отсутствие — не ошибка)."""


@dataclass(frozen=True)
class AutostartState:
    """Состояние автозапуска для панели."""

    supported: bool
    enabled: bool
    #: Команда, которая сейчас записана в реестре (пусто — записи нет).
    command: str
    #: Команда, которой приложение запускается сейчас (её запишет включение).
    expected_command: str
    #: Запись есть, но указывает на старый путь (приложение перенесли).
    outdated: bool
    location: str
    #: Причина, по которой автозапуск недоступен или не прочитался.
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Ответ API в camelCase (как у остальных эндпоинтов панели)."""
        return {
            "supported": self.supported,
            "enabled": self.enabled,
            "command": self.command,
            "expectedCommand": self.expected_command,
            "outdated": self.outdated,
            "location": self.location,
            "reason": self.reason,
        }


class WindowsRegistryBackend:
    """Запись автозапуска в HKCU\\...\\Run через ``winreg``."""

    def __init__(self, value_name: str = VALUE_NAME, key_path: str = RUN_KEY) -> None:
        self._value_name = value_name
        self._key_path = key_path

    @staticmethod
    def _winreg() -> Any:
        # Импорт лениво: на не-Windows модуля winreg нет, а тесты и панель
        # должны собираться и запускаться без него.
        import winreg

        return winreg

    def read(self) -> Optional[str]:
        winreg = self._winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._key_path) as key:
                value, _ = winreg.QueryValueEx(key, self._value_name)
        except FileNotFoundError:
            # Нет ни ключа, ни значения — автозапуск выключен.
            return None
        except OSError as ex:
            raise AutostartError(f"Не удалось прочитать автозапуск: {ex}") from ex

        return str(value)

    def write(self, command: str) -> None:
        winreg = self._winreg()
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                self._key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, self._value_name, 0, winreg.REG_SZ, command)
        except OSError as ex:
            raise AutostartError(f"Не удалось включить автозапуск: {ex}") from ex

    def delete(self) -> None:
        winreg = self._winreg()
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self._key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, self._value_name)
        except FileNotFoundError:
            return  # записи уже нет — отключение выполнено
        except OSError as ex:
            raise AutostartError(f"Не удалось отключить автозапуск: {ex}") from ex


def launch_command(root: Optional[Path] = None) -> Optional[list[str]]:
    """Команда запуска приложения: ``zere.exe``, иначе pythonw + main.py.

    ``zere.exe`` — штатный лаунчер (окно без консоли, единственный экземпляр),
    поэтому он в приоритете. В репозитории без собранного лаунчера годится
    ``.venv\\Scripts\\pythonw.exe main.py --desktop`` — то же окно без консоли.
    None — рядом нет ни лаунчера, ни виртуального окружения.
    """
    base = Path(root) if root is not None else paths.PROJECT_ROOT

    launcher = base / "zere.exe"
    if launcher.is_file():
        return [str(launcher)]

    main_py = base / "main.py"
    scripts = base / ".venv" / "Scripts"
    for interpreter_name in ("pythonw.exe", "python.exe"):
        interpreter = scripts / interpreter_name
        if interpreter.is_file() and main_py.is_file():
            return [str(interpreter), str(main_py), "--desktop"]

    return None


def command_line(args: list[str]) -> str:
    """Строка команды для реестра: кавычки по правилам Windows (пути с пробелом)."""
    return subprocess.list2cmdline(args)


class AutostartService:
    """Чтение и переключение автозапуска ZERE вместе с Windows."""

    def __init__(
        self,
        *,
        backend: Optional[AutostartBackend] = None,
        command: Optional[str] = None,
        platform: Optional[str] = None,
        root: Optional[Path] = None,
    ) -> None:
        # platform подменяется в тестах: реестр не трогается.
        self._platform = platform if platform is not None else sys.platform
        self._backend = backend
        # Явная команда — для тестов и нестандартных сборок (None — вычислить).
        self._command = command
        self._root = root

    # ── Доступное состояние ───────────────────────────────────────

    @property
    def supported(self) -> bool:
        """Автозапуск через реестр возможен только в Windows."""
        return self._platform.startswith("win")

    @property
    def backend(self) -> Optional[AutostartBackend]:
        """Реестр создаётся при первом обращении, а не при импорте модуля."""
        if not self.supported:
            return None
        if self._backend is None:
            self._backend = WindowsRegistryBackend()
        return self._backend

    def expected_command(self) -> str:
        """Команда, которую запишет включение автозапуска (пусто — не найдена)."""
        if self._command is not None:
            return self._command

        args = launch_command(self._root)
        return command_line(args) if args else ""

    def status(self) -> AutostartState:
        """Текущее состояние: включён ли автозапуск и куда он указывает."""
        expected = self.expected_command()

        if not self.supported:
            return AutostartState(
                supported=False,
                enabled=False,
                command="",
                expected_command=expected,
                outdated=False,
                location=LOCATION,
                reason="Автозапуск вместе с Windows доступен только в Windows.",
            )

        backend = self.backend
        assert backend is not None  # supported → backend есть

        try:
            current = backend.read() or ""
            error = ""
        except AutostartError as ex:
            # Реестр не читается (политика, повреждённый профиль): честно
            # показываем причину вместо «выключено».
            current = ""
            error = str(ex)

        enabled = bool(current)
        return AutostartState(
            supported=True,
            enabled=enabled,
            command=current,
            expected_command=expected,
            outdated=bool(current and expected and current != expected),
            location=LOCATION,
            reason=error,
        )

    def set_enabled(self, enabled: bool) -> AutostartState:
        """Включить/отключить автозапуск и вернуть новое состояние."""
        if not self.supported:
            raise AutostartUnsupportedError(
                "Автозапуск вместе с Windows доступен только в Windows."
            )

        backend = self.backend
        assert backend is not None  # supported → backend есть

        if enabled:
            command = self.expected_command()
            if not command:
                raise AutostartError(
                    "Не удалось определить команду запуска ZERE: рядом нет "
                    "zere.exe и .venv\\Scripts\\pythonw.exe."
                )
            backend.write(command)
        else:
            backend.delete()

        return self.status()

