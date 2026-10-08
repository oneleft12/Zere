"""Роутер интентов ZERE на Jev (TypeSafe System One).

Jev — быстрый диспетчер: за один-два запроса он выбирает интент из реестра
(`intents.py`) и отдаёт калиброванную уверенность. Действует код: интент →
каноническая фраза → существующий обработчик пайплайна.

Подробности и обоснование порогов — docs/JEV_ROUTER.md.
"""

from zere.core.routing.intents import (
    INTENTS,
    INTENTS_BY_ID,
    Intent,
    Slot,
    build_command,
    extract_payload,
    get_intent,
)
from zere.core.routing.jev_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    Decision,
    JevClient,
    JevError,
)
from zere.core.routing.jev_router import (
    ACTION_CLARIFY,
    ACTION_CONFIRM,
    ACTION_ERROR,
    ACTION_EXECUTE,
    ACTION_LLM,
    ACTION_OFF,
    MODE_FALLBACK,
    MODE_FIRST,
    STRATEGY_DOMAIN,
    STRATEGY_SINGLE,
    EmptyCatalog,
    JevIntentRouter,
    LocalCatalog,
    RouteDecision,
    RouterSettings,
)

__all__ = [
    "INTENTS",
    "INTENTS_BY_ID",
    "Intent",
    "Slot",
    "build_command",
    "extract_payload",
    "get_intent",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "Decision",
    "JevClient",
    "JevError",
    "ACTION_CLARIFY",
    "ACTION_CONFIRM",
    "ACTION_ERROR",
    "ACTION_EXECUTE",
    "ACTION_LLM",
    "ACTION_OFF",
    "MODE_FALLBACK",
    "MODE_FIRST",
    "STRATEGY_DOMAIN",
    "STRATEGY_SINGLE",
    "EmptyCatalog",
    "JevIntentRouter",
    "LocalCatalog",
    "RouteDecision",
    "RouterSettings",
]
