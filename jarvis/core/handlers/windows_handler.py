"""Порт JARVIS.Core/Handlers/WindowsHandler.cs."""

from __future__ import annotations

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.tools.applications.application_launcher import ApplicationLauncher
from jarvis.tools.windows.pending_action import PendingAction
from jarvis.tools.windows.safe_action_manager import SafeActionManager
from jarvis.tools.windows.windows_command_router import WindowsCommandRouter
from jarvis.tools.windows.windows_command_type import WindowsCommandType


class WindowsHandler(IJarvisHandler):
    def __init__(self, launcher: ApplicationLauncher, safe_actions: SafeActionManager) -> None:
        self._launcher = launcher
        self._router = WindowsCommandRouter()
        self._safe_actions = safe_actions

    def can_handle(self, message: str) -> bool:
        lower = message.lower().strip()

        return (
            lower.startswith("открой ")
            or lower == "обнови индекс"
            or lower == "сколько приложений"
            or lower.startswith("найди ")
            # Shutdown
            or "выключи компьютер" in lower
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
            or "перезагрузка" in lower
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
            # Confirmations
            or lower == "да"
            or lower == "нет"
            or lower == "подтверди"
            or lower == "выполни"
            or lower == "сделай"
            or lower == "выполняй"
        )

    def handle(self, message: str) -> str:
        lower = message.lower().strip()

        if lower in ("да", "подтверди", "выполни", "сделай", "выполняй"):
            return "Выполняю команду." if self._safe_actions.confirm() else "Нет команды для подтверждения."

        if lower == "нет":
            self._safe_actions.cancel()
            return "Команда отменена."

        if lower == "обнови индекс":
            self._launcher.rebuild_index()
            return "Индекс приложений успешно обновлён."

        if lower == "сколько приложений":
            return f"В индексе {len(self._launcher.get_installed_applications())} приложений."

        if lower.startswith("найди "):
            query = lower.replace("найди ", "")

            apps = [
                f"• {a.name}"
                for a in list(self._launcher.get_installed_applications().values())[:]
                if query.lower() in a.name.lower()
            ][:10]

            result = "\n".join(apps)

            if result is None or result.strip() == "":
                return "Ничего не найдено."

            return result

        if lower.startswith("открой "):
            app = message[len("открой") :].strip()

            return f"Открываю {app}." if self._launcher.launch(app) else f"Не удалось найти приложение «{app}»."

        command = self._router.parse(message)

        if command == WindowsCommandType.Shutdown:
            self._safe_actions.request(PendingAction.Shutdown)
            return "Вы уверены, что хотите выключить компьютер? Напишите «да», «подтверди», «выполни» или «нет»."

        if command == WindowsCommandType.Restart:
            self._safe_actions.request(PendingAction.Restart)
            return "Вы уверены, что хотите перезагрузить компьютер? Напишите «да», «подтверди», «выполни» или «нет»."

        if command == WindowsCommandType.Sleep:
            self._safe_actions.request(PendingAction.Sleep)
            return "Перевести компьютер в сон? Напишите «да», «подтверди», «выполни» или «нет»."

        return "Команда Windows не распознана."
