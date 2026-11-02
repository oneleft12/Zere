"""Порт ZERE.Core/Handlers/WindowsHandler.cs."""

from __future__ import annotations

from zere.core.handlers.i_zere_handler import IZereHandler
from zere.tools.applications.application_launcher import ApplicationLauncher
from zere.tools.files.file_manager import FileManager
from zere.tools.windows.pending_action import PendingAction
from zere.tools.windows.safe_action_manager import ConfirmOutcome, SafeActionManager
from zere.tools.windows.windows_command_router import WindowsCommandRouter
from zere.tools.windows.windows_command_type import WindowsCommandType

#: Явные папки-команды — зона FileHandler (он идёт после WindowsHandler).
_FOLDER_PREFIXES = (
    "открой папку",
    "открыть папку",
    "открой каталог",
    "открыть каталог",
    "открой директорию",
    "открыть директорию",
    "покажи папку",
    "открой путь",
    "найди папку",
)


class WindowsHandler(IZereHandler):
    def __init__(
        self,
        launcher: ApplicationLauncher,
        safe_actions: SafeActionManager,
        files: FileManager | None = None,
    ) -> None:
        self._launcher = launcher
        self._router = WindowsCommandRouter()
        self._safe_actions = safe_actions
        # Необязателен: «открой загрузки» сначала пробует приложение, затем
        # стандартную папку. В тестах без FileManager поведение прежнее.
        self._files = files

    def can_handle(self, message: str) -> bool:
        lower = message.lower().strip()

        # Отмена ожидающего действия — всегда наша команда.
        if lower == "нет":
            return True

        # Отрицания («не выключай компьютер») не считаем командами
        # питания — ответ отдаёт LLM.
        negated = WindowsCommandRouter.is_negated(lower)
        power = not negated and (
            "выключи компьютер" in lower
            or "выключить компьютер" in lower
            or "выруби компьютер" in lower
            or "выключай компьютер" in lower
            or "выключи комп" in lower
            or "выключить комп" in lower
            or "выруби комп" in lower
            or "выключай комп" in lower
            or "заверши работу" in lower
            or "shutdown" in lower
            or "power off" in lower
            or "выключи пк" in lower
            or "выключить пк" in lower
            or "выруби пк" in lower
            # Restart
            or "перезагрузи компьютер" in lower
            or "перезагрузить компьютер" in lower
            or "перезагрузи комп" in lower
            or "перезагрузить комп" in lower
            or lower == "перезагрузка"
            or lower.startswith("перезагрузка ")
            or "reboot" in lower
            or "restart" in lower
            or "рестарт" in lower
            or "перезагрузи пк" in lower
            or "перезагрузить пк" in lower
            or "перезапусти компьютер" in lower
            or "перезапусти комп" in lower
            # Sleep
            or lower == "сон"
            or "режим сна" in lower
            or "спящий режим" in lower
            or "компьютер в сон" in lower
            or "комп в сон" in lower
            or "заморозь" in lower
            or "hibernate" in lower
            or "уходи спать" in lower
        )

        folder_command = lower.startswith(_FOLDER_PREFIXES) or lower in (
            "открой её",
            "открой ее",
        )

        return (
            (lower.startswith("открой ") and not folder_command)
            or lower == "обнови индекс"
            or lower == "сколько приложений"
            # «найди файл …» и «найди папку …» — зона FileHandler (он идёт
            # после нас): без этого исключения поиск был бы недостижим.
            or (
                lower.startswith("найди ")
                and not lower.startswith("найди файл")
                and not lower.startswith("найди папку")
            )
            or power
            # Confirmations
            or lower == "да"
            or lower == "подтверди"
            or lower == "выполни"
            or lower == "сделай"
            or lower == "выполняй"
        )

    def handle(self, message: str) -> str:
        lower = message.lower().strip()

        if lower in ("да", "подтверди", "выполни", "сделай", "выполняй"):
            outcome = self._safe_actions.confirm()
            if outcome is ConfirmOutcome.EXECUTED:
                # Подтверждённой командой могла быть команда роутера интентов
                # Jev («очисти память» и т. п.) — тогда показываем ответ
                # обработчика, а не общее «Выполняю команду».
                result = self._safe_actions.last_result
                return result if result else "Выполняю команду."
            if outcome is ConfirmOutcome.EXPIRED:
                ttl = SafeActionManager.CONFIRM_TTL_SECONDS
                return f"Время подтверждения истекло ({ttl} секунд) — команда сброшена. Повторите команду."
            if outcome is ConfirmOutcome.FAILED:
                return "Не удалось выполнить команду."
            return "Нет команды для подтверждения."

        if lower == "нет":
            self._safe_actions.cancel()
            return "Команда отменена."

        if lower == "обнови индекс":
            self._launcher.rebuild_index()
            return "Индекс приложений успешно обновлён."

        if lower == "сколько приложений":
            return f"В индексе {len(self._launcher.get_installed_applications())} приложений."

        if (
            lower.startswith("найди ")
            and not lower.startswith("найди файл")
            and not lower.startswith("найди папку")
        ):
            query = message[len("найди ") :].strip()
            needle = query.casefold()

            apps = [
                f"• {a.name}"
                for a in list(self._launcher.get_installed_applications().values())[:]
                if needle in a.name.casefold()
            ][:10]

            result = "\n".join(apps)

            if result.strip():
                return result

            # Приложений нет — ищем папку: «найди проекты» должен находить
            # папку, даже если пользователь не сказал «найди папку …».
            finder = getattr(self._files, "find_folders", None)
            if finder is not None:
                folder_answer = finder(query)
                if "не найдена." not in folder_answer or "Поиск ограничен" in folder_answer:
                    return folder_answer

            return "Ничего не найдено."

        if lower.startswith("открой "):
            app = message[len("открой") :].strip()

            if self._launcher.launch(app):
                return f"Открываю {app}."

            # «открой загрузки/документы» — не приложение, а стандартная
            # папка. Явные «открой папку …» сюда не доходят: их обрабатывает
            # FileHandler (can_handle выше).
            if self._files is not None and self._files.can_open_folder(app):
                return self._files.open_folder(app)

            return f"Не удалось найти приложение «{app}»."

        command = self._router.parse(message)

        if command == WindowsCommandType.Shutdown:
            self._safe_actions.request(PendingAction.SHUTDOWN)
            ttl = SafeActionManager.CONFIRM_TTL_SECONDS
            return f"Вы уверены, что хотите выключить компьютер? Напишите «да» или «нет» (подтверждение действует {ttl} секунд)."

        if command == WindowsCommandType.Restart:
            self._safe_actions.request(PendingAction.RESTART)
            ttl = SafeActionManager.CONFIRM_TTL_SECONDS
            return f"Вы уверены, что хотите перезагрузить компьютер? Напишите «да» или «нет» (подтверждение действует {ttl} секунд)."

        if command == WindowsCommandType.Sleep:
            self._safe_actions.request(PendingAction.SLEEP)
            ttl = SafeActionManager.CONFIRM_TTL_SECONDS
            return f"Перевести компьютер в сон? Напишите «да» или «нет» (подтверждение действует {ttl} секунд)."

        return "Команда Windows не распознана."
