"""Клиент Jev (TypeSafe System One) через Decisions API.

Jev — не генеративная модель: на вход уходит `state` (контекст) и карта
типизированных `questions`, на выход — типизированные `answers` с
калиброванными вероятностями. Свободного текста в ответе нет по построению,
поэтому парсить нечего и «невалидный интент» получить нельзя.

Два взаимозаменяемых адреса (та же форма запроса):
- OpenRouter Decisions API — `https://openrouter.ai/api/alpha/decisions`
  (ключ OpenRouter `sk-or-...`); именно его использует ZERE;
- TypeSafe System One — `https://api.typesafe.ai/v1/systemone`.

Правила безопасности те же, что у облачного ИИ ZERE:
- ключ живёт только в конфиге/окружении бэкенда и не попадает в логи,
  тексты ошибок и ответы API;
- тексты ошибок провайдера санитизируются (`redact_secrets`) и
  маскируются;
- ошибки переводятся в понятные русские тексты и коды (`JEV_*`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from zere.ai.ai_settings import mask_key
from zere.core.logging.log_service import log_error, redact_secrets

# ── Адрес по умолчанию ──────────────────────────────────────────────
DEFAULT_BASE_URL = "https://openrouter.ai/api/alpha/decisions"
#: Алиас отслеживает свежий релиз; для продакшена лучше пинить версию
#: (`typesafe/jev-1.13`), иначе пороги могут «поплыть» на новом релизе.
DEFAULT_MODEL = "~typesafe/jev-latest"
DEFAULT_TIMEOUT = 20

# ── Типы вопросов ───────────────────────────────────────────────────
Q_CHOICE = "choice"
Q_SCORE = "score"
Q_NOUL = "noul"

# ── Коды и тексты ошибок ────────────────────────────────────────────
CODE_NO_KEY = "JEV_NO_KEY"
CODE_KEY_INVALID = "JEV_KEY_INVALID"
CODE_NO_CREDITS = "JEV_NO_CREDITS"
CODE_RATE_LIMIT = "JEV_RATE_LIMIT"
CODE_MODEL_UNAVAILABLE = "JEV_MODEL_UNAVAILABLE"
CODE_NETWORK = "JEV_NETWORK"
CODE_PROVIDER_ERROR = "JEV_PROVIDER_ERROR"
CODE_BAD_ANSWER = "JEV_BAD_ANSWER"

MESSAGE_NO_KEY = "Ключ Jev не задан — роутер выключен"
MESSAGE_KEY_INVALID = "Неверный ключ Jev"
MESSAGE_NO_CREDITS = "На балансе Jev нет средств"
MESSAGE_RATE_LIMIT = "Превышен лимит запросов к Jev"
MESSAGE_MODEL_UNAVAILABLE = "Модель Jev недоступна по этому адресу"
MESSAGE_NETWORK = "Не удалось подключиться к Jev — проверьте интернет и адрес"
MESSAGE_PROVIDER_ERROR = "Jev вернул ошибку"
MESSAGE_BAD_ANSWER = "Jev вернул ответ без ожидаемых полей"

USER_AGENT = "ZERE/1.8.0"


class JevError(Exception):
    """Нормализованная ошибка Jev: код + понятный текст."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Answer:
    """Типизированный ответ на один вопрос."""

    type: str
    #: choice → выбранный вариант (str), noul → вероятность (float),
    #: score → позиция на шкале (float).
    value: Any
    confidence: Optional[float] = None
    probabilities: dict[str, float] = field(default_factory=dict)
    legend: dict[str, str] = field(default_factory=dict)


@dataclass
class Decision:
    """Результат вызова Jev: ответы на все вопросы одним запросом."""

    model: str
    answers: dict[str, Answer]
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def cost(self) -> Optional[float]:
        value = self.usage.get("cost")
        return float(value) if isinstance(value, (int, float)) else None

    def choice(self, question_id: str) -> Optional[str]:
        answer = self.answers.get(question_id)
        if answer is None or answer.type != Q_CHOICE:
            return None
        return answer.value if isinstance(answer.value, str) else None

    def probability(self, question_id: str) -> Optional[float]:
        answer = self.answers.get(question_id)
        if answer is None or answer.type != Q_NOUL:
            return None
        return float(answer.value) if isinstance(answer.value, (int, float)) else None

    def score(self, question_id: str) -> Optional[float]:
        answer = self.answers.get(question_id)
        if answer is None or answer.type != Q_SCORE:
            return None
        return float(answer.value) if isinstance(answer.value, (int, float)) else None

    def confidence(self, question_id: str) -> Optional[float]:
        answer = self.answers.get(question_id)
        if answer is None or not isinstance(answer.confidence, (int, float)):
            return None
        return float(answer.confidence)


# ── Конструкторы вопросов ───────────────────────────────────────────
def choice_question(instructions: str, criteria: dict[str, str]) -> dict[str, Any]:
    """Выбор одного варианта из заданного множества."""
    return {"type": Q_CHOICE, "instructions": instructions, "criteria": dict(criteria)}


def score_question(instructions: str, criteria: list[Any]) -> dict[str, Any]:
    """Позиция на упорядоченной шкале (первый критерий — низ шкалы)."""
    return {"type": Q_SCORE, "instructions": instructions, "criteria": list(criteria)}


def noul_question(instructions: str, criteria: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Калиброванное «да/нет» как вероятность (probability of yes)."""
    question: dict[str, Any] = {"type": Q_NOUL, "instructions": instructions}
    if criteria:
        question["criteria"] = dict(criteria)
    return question


def _clean_body(text: str, api_key: Optional[str] = None) -> str:
    """Короткое безопасное описание ответа провайдера.

    Сначала литеральный ключ заменяется маской, и только потом включается
    общий вычиститель секретов: иначе он съедает ключ в «***» и полезная
    маска «sk-...abcd» до текста ошибки не доходит.
    """
    snippet = (text or "").strip().replace("\n", " ")
    if api_key and api_key in snippet:
        snippet = snippet.replace(api_key, mask_key(api_key))
    return redact_secrets(snippet)[:200]


def _classify(status: int, body: str, api_key: Optional[str] = None) -> JevError:
    """HTTP-статус провайдера → понятная ошибка Jev."""
    detail = _clean_body(body, api_key)
    lowered = (body or "").lower()

    if status in (401, 403):
        return JevError(CODE_KEY_INVALID, MESSAGE_KEY_INVALID, status=400)

    if status == 402:
        return JevError(CODE_NO_CREDITS, MESSAGE_NO_CREDITS, status=400)

    if status == 429:
        return JevError(CODE_RATE_LIMIT, MESSAGE_RATE_LIMIT, status=429)

    if status == 404 and ("model" in lowered or "not found" in lowered):
        return JevError(CODE_MODEL_UNAVAILABLE, MESSAGE_MODEL_UNAVAILABLE, status=400)

    if status == 400 and any(
        marker in lowered
        for marker in (
            "model_not_found",
            "does not exist",
            "unknown model",
            "invalid model",
            "no endpoints found",
        )
    ):
        return JevError(CODE_MODEL_UNAVAILABLE, MESSAGE_MODEL_UNAVAILABLE, status=400)

    if status >= 500:
        message = f"{MESSAGE_PROVIDER_ERROR} (HTTP {status})"
        if detail:
            message += f": {detail}"
        return JevError(CODE_PROVIDER_ERROR, message, status=502)

    message = f"{MESSAGE_PROVIDER_ERROR} (HTTP {status})"
    if detail:
        message += f": {detail}"
    return JevError(CODE_PROVIDER_ERROR, message, status=400)


def _parse_answer(payload: Any) -> Optional[Answer]:
    """Ответ одного вопроса → типизированный Answer (None — не разобрали)."""
    if not isinstance(payload, dict):
        return None

    answer_type = payload.get("type")
    probabilities: dict[str, float] = {}
    raw_probabilities = payload.get("probabilities")
    if isinstance(raw_probabilities, dict):
        probabilities = {
            str(key): float(value)
            for key, value in raw_probabilities.items()
            if isinstance(value, (int, float))
        }

    legend: dict[str, str] = {}
    raw_legend = payload.get("legend")
    if isinstance(raw_legend, dict):
        legend = {str(key): str(value) for key, value in raw_legend.items()}

    confidence = payload.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else None

    if answer_type == Q_CHOICE:
        value = payload.get("choice")
        if not isinstance(value, str):
            return None
        return Answer(Q_CHOICE, value, confidence, probabilities, legend)

    if answer_type == Q_NOUL:
        value = payload.get("noul")
        if not isinstance(value, (int, float)):
            return None
        return Answer(Q_NOUL, float(value), confidence, probabilities, legend)

    if answer_type == Q_SCORE:
        value = payload.get("score")
        if not isinstance(value, (int, float)):
            return None
        return Answer(Q_SCORE, float(value), confidence, probabilities, legend)

    return None


class JevClient:
    """Один POST: state + questions → типизированные answers."""

    def __init__(
        self,
        session: Optional[Any] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        # session инжектируется в тестах (requests.Session-совместимый объект)
        self._session = session if session is not None else requests.Session()
        self._base_url = self.normalize_base_url(base_url)
        self._api_key = (api_key or "").strip()
        self._model = (model or DEFAULT_MODEL).strip()
        self._timeout = timeout

    # ── Вспомогательное ─────────────────────────────────────────────

    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        """Убирает хвостовой слэш; принимает и базу API, и полный эндпоинт."""
        return (base_url or "").strip().rstrip("/")

    @property
    def model(self) -> str:
        return self._model

    def endpoint(self) -> str:
        """Полный URL запроса решений.

        Принимаем и «.../alpha/decisions» (как в документации OpenRouter),
        и базу API («https://openrouter.ai/api» или «.../api/v1») — тогда
        путь дописывается сам.
        """
        base = self._base_url
        if base.endswith("/decisions") or base.endswith("/systemone"):
            return base
        if base.endswith("/v1") or base.endswith("/api"):
            return f"{base}/alpha/decisions"
        return f"{base}/decisions"

    def has_key(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # ── Основной вызов ──────────────────────────────────────────────

    def decide(self, state: Any, questions: dict[str, dict[str, Any]]) -> Decision:
        """Отправляет state и вопросы; ошибки — JevError."""
        if not self._api_key:
            raise JevError(CODE_NO_KEY, MESSAGE_NO_KEY, status=400)

        if not questions:
            raise JevError(CODE_BAD_ANSWER, MESSAGE_BAD_ANSWER, status=400)

        body: dict[str, Any] = {
            "model": self._model,
            "state": state,
            "questions": questions,
        }

        try:
            response = self._session.post(
                self.endpoint(),
                headers=self._headers(),
                json=body,
                timeout=self._timeout,
            )
        except requests.exceptions.Timeout as ex:
            log_error("JevClient", "таймаут запроса решений")
            raise JevError(
                CODE_NETWORK,
                "Jev не ответил вовремя (таймаут).",
                status=504,
            ) from ex
        except requests.exceptions.RequestException as ex:
            log_error("JevClient", f"сеть: {redact_secrets(str(ex))}")
            raise JevError(CODE_NETWORK, MESSAGE_NETWORK, status=502) from ex

        if response.status_code >= 400:
            raise _classify(response.status_code, response.text, self._api_key)

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as ex:
            raise JevError(CODE_PROVIDER_ERROR, MESSAGE_PROVIDER_ERROR, status=502) from ex

        if not isinstance(payload, dict):
            raise JevError(CODE_BAD_ANSWER, MESSAGE_BAD_ANSWER, status=502)

        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, dict):
            raise JevError(CODE_BAD_ANSWER, MESSAGE_BAD_ANSWER, status=502)

        answers: dict[str, Answer] = {}
        for question_id, raw in raw_answers.items():
            answer = _parse_answer(raw)
            if answer is not None:
                answers[str(question_id)] = answer

        if not answers:
            raise JevError(CODE_BAD_ANSWER, MESSAGE_BAD_ANSWER, status=502)

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}

        return Decision(
            model=str(payload.get("model") or self._model),
            answers=answers,
            usage=usage,
            raw=payload,
        )

    def check(self) -> dict[str, Any]:
        """Проверка ключа и адреса минимальным запросом решений.

        Возвращает {ok, model, cost, message}; ошибка — JevError.
        """
        decision = self.decide(
            state={"message": "привет"},
            questions={
                "is_command": noul_question(
                    "Просит ли пользователь выполнить действие на компьютере?"
                )
            },
        )
        probability = decision.probability("is_command")

        message = f"Jev отвечает (модель «{decision.model}»)"
        if decision.cost is not None:
            message += f", стоимость запроса ${decision.cost:.6f}"
        message += "."

        return {
            "ok": True,
            "model": decision.model,
            "probability": probability,
            "cost": decision.cost,
            "message": message,
        }

    def close(self) -> None:
        close = getattr(self._session, "close", None)
        if callable(close):
            close()
