"""Порт JARVIS.Core/Handlers/WindowsHandler.cs."""

from __future__ import annotations

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.tools.applications.application_launcher import ApplicationLauncher
from jarvis.tools.windows.pending_action import PendingAction
from jarvis.tools.windows.safe_action_manager import ConfirmOutcome, SafeActionManager
from jarvis.tools.windows.windows_command_router import WindowsCommandRouter
from jarvis.tools.windows.windows_command_type import WindowsCommandType


class WindowsHandler(IJarvisHandler):
    def __init__(self, launcher: ApplicationLauncher, safe_actions: SafeActionManager) -> None:
        self._launcher = launcher
        self._router = WindowsCommandRouter()
        self._safe_actions = safe_actions

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

        return (
            lower.startswith("открой ")
            or lower == "обнови индекс"
            or lower == "сколько приложений"
            or lower.startswith("найди ")
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
                return "Выполняю команду."
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
