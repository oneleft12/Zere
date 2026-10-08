"""Обработчик-обёртка: свободная фраза → интент Jev → каноническая команда.

Ставится между локальными обработчиками и `AIHandler` (режим `fallback`,
по умолчанию): локальные обработчики уже попробовали свои точные фразы —
если не вышло, спрашиваем Jev и при достаточной уверенности прогоняем
каноническую команду по тем же локальным обработчикам. В режиме `first`
обработчик встаёт в начало пайплайна.

Ключевое правило: обработчик никогда не отвечает вместо ИИ и не выполняет
команды сам — он только переводит формулировку и передаёт её существующим
обработчикам со всеми их подтверждениями. Поэтому поведение ZERE без
роутера и с роутером отличается лишь там, где роутер уверен.

    decision.action == execute  → каноническая фраза → локальный пайплайн
    decision.action == confirm  → SafeActionManager.request(ROUTER_COMMAND)
                                  (подтверждение «да» выполняет пайплайн)
    decision.action == clarify  → вопрос пользователю
    llm | off | error           → None → отвечает AIHandler

Роутер выключен (нет ключа) → обработчик вообще не регистрируется
(`build_jev_handler`), горячий путь не меняется.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from zere.core.handlers.handler_pipeline import HandlerPipeline
from zere.core.handlers.i_zere_handler import IZereHandler
from zere.core.routing.jev_router import (
    ACTION_CLARIFY,
    ACTION_CONFIRM,
    ACTION_EXECUTE,
    MODE_FIRST,
    JevIntentRouter,
    LocalCatalog,
    RouteDecision,
    RouterSettings,
)
from zere.tools.windows.pending_action import PendingAction


class JevRoutingHandler(IZereHandler):
    """Переводит свободную фразу в каноническую команду через Jev."""

    def __init__(
        self,
        router: JevIntentRouter,
        local_pipeline: HandlerPipeline,
        *,
        safe_actions: Optional[Any] = None,
        log: Optional[Any] = None,
    ) -> None:
        self._router = router
        self._local = local_pipeline
        self._safe_actions = safe_actions
        self._log = log

        # Менеджер подтверждений держит «да/нет» и TTL, а выполняет команду
        # роутера — пайплайн: менеджер про обработчики ничего не знает.
        if safe_actions is not None and hasattr(safe_actions, "set_command_executor"):
            safe_actions.set_command_executor(self._run_command)

    @property
    def router(self) -> JevIntentRouter:
        return self._router

    @property
    def goes_first(self) -> bool:
        """Режим `first`: обработчик встаёт в начало пайплайна."""
        return self._router.settings.mode == MODE_FIRST

    # ── IZereHandler ────────────────────────────────────────────────

    def can_handle(self, message: str) -> bool:
        # Если роутер не настроен, обработчик не должен забирать сообщения.
        return self._router.settings.ready()

    def handle(self, message: str) -> Optional[str]:
        decision = self._router.route(message)
        self._log_decision(message, decision)

        if decision.action == ACTION_EXECUTE:
            # Каноническая фраза не разобралась — отдаём ИИ, не выдумываем ответ.
            return self._local.handle(decision.command)

        if decision.action == ACTION_CONFIRM:
            if self._safe_actions is None:
                # Нечем подтвердить — спрашиваем пользователя, но не выполняем.
                return decision.question
            self._safe_actions.request(PendingAction.ROUTER_COMMAND, decision.command)
            return decision.question

        if decision.action == ACTION_CLARIFY:
            return decision.question

        # llm | off | error — дальше отвечает AIHandler, как без роутера.
        return None

    # ── Выполнение после «да» ───────────────────────────────────────

    def _run_command(self, command: str) -> Optional[str]:
        """Выполняет подтверждённую команду роутера (зовёт SafeActionManager)."""
        return self._local.handle(command)

    # ── Телеметрия ──────────────────────────────────────────────────

    def _log_decision(self, message: str, decision: RouteDecision) -> None:
        if self._log is None:
            return

        confidence = (
            "—" if decision.confidence is None else f"{decision.confidence:.2f}"
        )
        line = (
            f"[JevRouter] {decision.action} intent={decision.intent_id or '—'} "
            f"conf={confidence} {decision.latency_ms}мс «{message[:80]}»"
        )
        if decision.command:
            line += f" → «{decision.command}»"
        if decision.reason:
            line += f" ({decision.reason})"

        try:
            # LogService сам вычищает секреты; сбой логирования не должен
            # ломать ответ пользователю.
            self._log.info(line)
        except Exception:  # noqa: BLE001
            pass


def build_jev_handler(
    *,
    local_handlers: Iterable[IZereHandler],
    settings: Optional[RouterSettings] = None,
    catalog: Optional[Any] = None,
    safe_actions: Optional[Any] = None,
    log: Optional[Any] = None,
    settings_factory: Optional[Any] = None,
) -> Optional[JevRoutingHandler]:
    """Собирает обработчик роутера, если он настроен (включён и есть ключ).

    Выключенный роутер не регистрируется вовсе: ни чтения настроек в
    горячем пути, ни запросов, ни задержки. `settings`/`settings_factory`
    инжектируются в тестах.
    """
    resolved: Optional[RouterSettings] = None
    if settings is not None:
        resolved = settings
    else:
        factory = settings_factory or RouterSettings.load
        resolved = factory()

    if resolved is None or not resolved.ready():
        return None

    router = JevIntentRouter(
        resolved,
        catalog=catalog if catalog is not None else LocalCatalog(),
    )
    return JevRoutingHandler(
        router,
        HandlerPipeline(list(local_handlers)),
        safe_actions=safe_actions,
        log=log,
    )


def arrange_handlers(
    local_handlers: Iterable[IZereHandler],
    ai_handler: IZereHandler,
    jev_handler: Optional[JevRoutingHandler],
) -> list[IZereHandler]:
    """Порядок пайплайна с роутером интентов.

    - роутера нет → как раньше: локальные обработчики, затем ИИ;
    - `fallback` → роутер после локальных обработчиков, перед ИИ:
      он закрывает их промахи, а не перехватывает привычные команды;
    - `first` → роутер в начале: он решает первым, а при неуверенности
      сообщение доходит до локальных обработчиков и затем до ИИ.
    """
    local = list(local_handlers)

    if jev_handler is None:
        return [*local, ai_handler]

    if jev_handler.goes_first:
        return [jev_handler, *local, ai_handler]

    return [*local, jev_handler, ai_handler]


__all__ = ["JevRoutingHandler", "arrange_handlers", "build_jev_handler"]
