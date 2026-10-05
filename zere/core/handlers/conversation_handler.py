"""Порт ZERE.Core/Handlers/ConversationHandler.cs."""

from __future__ import annotations

from zere.core.handlers.i_zere_handler import IZereHandler
from zere.memory.database.conversation_repository import ConversationRepository


class ConversationHandler(IZereHandler):
    def __init__(self, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    def can_handle(self, message: str) -> bool:
        lower = message.lower().strip()

        return (
            lower == "покажи историю"
            or lower == "история"
            or lower == "история разговоров"
            or lower == "наши диалоги"
            or lower == "диалоги"
            or lower == "разговоры"
            or lower == "что мы обсуждали"
            or lower == "о чём мы говорили"
            or lower == "история чата"
            or lower == "очисти историю"
            or lower == "очисти диалоги"
            or lower == "очисть разговоры"
            or lower == "сбрось историю"
        )

    def handle(self, message: str) -> str:
        lower = message.lower().strip()

        # === Показать историю ===
        if (
            lower == "покажи историю"
            or lower == "история"
            or lower == "история разговоров"
            or lower == "наши диалоги"
            or lower == "диалоги"
            or lower == "разговоры"
            or lower == "что мы обсуждали"
            or lower == "о чём мы говорили"
            or lower == "история чата"
        ):
            history = self._conversations.get_last(20)

            if len(history) == 0:
                return "История пуста."

            return "\n\n".join(
                [f"Вы: {h.user_message}\nZERE: {h.zere_response}" for h in history]
            )

        # === Очистить историю ===
        if (
            lower == "очисти историю"
            or lower == "очисти диалоги"
            or lower == "очисть разговоры"
            or lower == "сбрось историю"
        ):
            self._conversations.clear_history()
            return "История очищена."

        return "Команда истории не распознана."
