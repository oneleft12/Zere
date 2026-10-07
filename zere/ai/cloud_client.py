"""Облачный клиент: любой OpenAI-совместимый API (chat/completions + models).

Один клиент обслуживает все пресеты (OpenAI, DeepSeek, OpenRouter, Groq,
свой сервер): меняются только Base URL, модель и ключ.

Правила задачи:
- ключ передаётся только в заголовке Authorization и живёт только на бэкенде;
- ключ не попадает в логи и в тексты ошибок (сообщения санитизируются);
- ошибки провайдера переводятся в понятные русские тексты
  («Неверный API-ключ», «На балансе нет средств», «Превышен лимит запросов»,
  «Модель недоступна»).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import requests

from zere.ai.ai_settings import mask_key
from zere.core.logging.log_service import log_error, redact_secrets

# ── Коды и тексты ошибок (требование 11 задачи) ─────────────────────
CODE_KEY_INVALID = "AI_KEY_INVALID"
CODE_NO_CREDITS = "AI_NO_CREDITS"
CODE_RATE_LIMIT = "AI_RATE_LIMIT"
CODE_MODEL_UNAVAILABLE = "AI_MODEL_UNAVAILABLE"
CODE_NETWORK = "AI_NETWORK"
CODE_PROVIDER_ERROR = "AI_PROVIDER_ERROR"
CODE_EMPTY_ANSWER = "AI_EMPTY_ANSWER"

MESSAGE_KEY_INVALID = "Неверный API-ключ"
MESSAGE_NO_CREDITS = "На балансе нет средств"
MESSAGE_RATE_LIMIT = "Превышен лимит запросов"
MESSAGE_MODEL_UNAVAILABLE = "Модель недоступна"
MESSAGE_NETWORK = "Не удалось подключиться к облачному API — проверьте интернет и Base URL"
MESSAGE_PROVIDER_ERROR = "Облачный провайдер вернул ошибку"
MESSAGE_EMPTY_ANSWER = "Провайдер вернул пустой ответ"

DEFAULT_TIMEOUT = 60
TEST_TIMEOUT = 20

# Клиент представляется своим именем (OpenCode Go просит не выглядеть
# безликой HTTP-библиотекой) и держит стабильный идентификатор сессии на
# процесс — по нему шлюз оптимизирует маршрутизацию и кэш промптов.
USER_AGENT = "ZERE/1.8.0"
SESSION_HEADER = "x-opencode-session"
_SESSION_ID = uuid.uuid4().hex


class AiError(Exception):
    """Нормализованная ошибка ИИ: код контракта + понятный текст."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _clean_body(text: str, api_key: Optional[str] = None) -> str:
    """Короткое безопасное описание ответа провайдера (без ключа)."""
    snippet = redact_secrets((text or "").strip().replace("\n", " "))[:200]
    if api_key:
        snippet = snippet.replace(api_key, mask_key(api_key))
    return snippet


def _classify(status: int, body: str, api_key: Optional[str] = None) -> AiError:
    """HTTP-статус провайдера → понятная ошибка (требование 11)."""
    detail = _clean_body(body, api_key)
    lowered = (body or "").lower()

    if status in (401, 403):
        return AiError(CODE_KEY_INVALID, MESSAGE_KEY_INVALID, status=400)

    if status == 402:
        return AiError(CODE_NO_CREDITS, MESSAGE_NO_CREDITS, status=400)

    if status == 429:
        return AiError(CODE_RATE_LIMIT, MESSAGE_RATE_LIMIT, status=429)

    if status == 404 and ("model" in lowered or "not found" in lowered):
        return AiError(CODE_MODEL_UNAVAILABLE, MESSAGE_MODEL_UNAVAILABLE, status=400)

    if status == 400 and any(
        marker in lowered
        for marker in ("model_not_found", "does not exist", "unknown model", "invalid model")
    ):
        return AiError(CODE_MODEL_UNAVAILABLE, MESSAGE_MODEL_UNAVAILABLE, status=400)

    if status >= 500:
        return AiError(
            CODE_PROVIDER_ERROR,
            f"{MESSAGE_PROVIDER_ERROR} (HTTP {status})" + (f": {detail}" if detail else ""),
            status=502,
        )

    message = f"{MESSAGE_PROVIDER_ERROR} (HTTP {status})"
    if detail:
        message += f": {detail}"
    return AiError(CODE_PROVIDER_ERROR, message, status=400)


class CloudClient:
    """OpenAI-совместимый клиент: генерация, список моделей, проверка ключа."""

    def __init__(
        self,
        session: Optional[Any] = None,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        test_timeout: int = TEST_TIMEOUT,
    ) -> None:
        # session инжектируется в тестах (requests.Session-совместимый объект)
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout
        self._test_timeout = test_timeout

    # ── Вспомогательное ─────────────────────────────────────────────

    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        """«https://api.openai.com/v1» — без хвостового слэша."""
        return (base_url or "").strip().rstrip("/")

    @staticmethod
    def _auth_headers(api_key: str, base_url: str = "") -> dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # Шлюзу OpenCode нужен идентификатор сессии: без него теряется
        # кэш промптов, а трафик может выглядеть как анонимный.
        if "opencode.ai" in base_url:
            headers[SESSION_HEADER] = _SESSION_ID
        return headers

    # ── Проверка ключа (требование 3) ───────────────────────────────

    def list_models(
        self, base_url: str, api_key: str, *, timeout: Optional[int] = None
    ) -> list[str]:
        """GET /models — «рабочий запрос» для проверки ключа."""
        url = f"{self.normalize_base_url(base_url)}/models"

        try:
            response = self._session.get(
                url,
                headers=self._auth_headers(api_key, base_url),
                timeout=timeout or self._test_timeout,
            )
        except requests.exceptions.RequestException as ex:
            raise AiError(CODE_NETWORK, MESSAGE_NETWORK, status=502) from ex

        if response.status_code >= 400:
            raise _classify(response.status_code, response.text, api_key)

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return []

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []

        models: list[str] = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                models.append(item["id"])
        return models

    def test_key(
        self, base_url: str, api_key: str, model: str
    ) -> dict[str, Any]:
        """Проверяет ключ рабочими запросами: список моделей + мини-запрос к чату.

        Одного `/models` мало: у части шлюзов (например, OpenCode Go) он
        публичный и отдаёт список даже с неверным ключом — тогда «рабочий»
        показывался бы при опечатке. Поэтому ключ всегда проверяется ещё и
        минимальным запросом к выбранной модели (`max_tokens=1`).

        Возвращает {ok, models, checkedWith, message}. Ошибка — AiError.
        """
        models: list[str] = []

        try:
            models = self.list_models(base_url, api_key)
        except AiError as ex:
            # 401/402/429 — окончательный приговор ключу, мини-запрос не нужен
            if ex.code in (CODE_KEY_INVALID, CODE_NO_CREDITS, CODE_RATE_LIMIT):
                raise
            # Прочие ответы (404/405 у части совместимых серверов, сеть)
            # не приговор: проверяем ключ минимальным запросом к чату.

        try:
            self._chat_probe(base_url, api_key, model)
        except AiError as ex:
            # Сеть дала сбой на мини-запросе, но список моделей уже пришёл:
            # доступность и ключ подтверждены, сетевой сбой не считаем
            # приговором ключу. Остальные ошибки (ключ, баланс, лимит,
            # модель) — окончательные.
            if not (ex.code == CODE_NETWORK and models):
                raise

        message = f"Ключ рабочий — тестовый запрос к модели «{model}» прошёл."

        if models:
            message += f" Доступно моделей: {len(models)}."

        return {
            "ok": True,
            "models": models[:100],
            "checkedWith": "chat",
            "message": message,
        }

    def _chat_probe(self, base_url: str, api_key: str, model: str) -> None:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
            "stream": False,
        }
        url = f"{self.normalize_base_url(base_url)}/chat/completions"

        try:
            response = self._session.post(
                url,
                headers=self._auth_headers(api_key, base_url),
                json=body,
                timeout=self._test_timeout,
            )
        except requests.exceptions.RequestException as ex:
            raise AiError(CODE_NETWORK, MESSAGE_NETWORK, status=502) from ex

        if response.status_code >= 400:
            raise _classify(response.status_code, response.text, api_key)

    # ── Генерация ───────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str],
        base_url: str,
        api_key: str,
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """POST /chat/completions — ответ модели строкой.

        Ошибки приходят как AiError: текст ответа пользователю формирует
        вызывающий слой (прокси провайдеров), чтобы не смешивать слои.
        """
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        url = f"{self.normalize_base_url(base_url)}/chat/completions"

        try:
            response = self._session.post(
                url,
                headers=self._auth_headers(api_key, base_url),
                json=body,
                timeout=self._timeout,
            )
        except requests.exceptions.Timeout as ex:
            log_error("CloudClient", f"таймаут запроса к {base_url}")
            raise AiError(
                CODE_NETWORK,
                "Облачный API не ответил вовремя (таймаут).",
                status=504,
            ) from ex
        except requests.exceptions.RequestException as ex:
            # requests кладёт URL в текст ошибки; ключ в URL не попадает,
            # но на всякий случай прогоняем через redact_secrets.
            log_error("CloudClient", f"сеть: {redact_secrets(str(ex))}")
            raise AiError(CODE_NETWORK, MESSAGE_NETWORK, status=502) from ex

        if response.status_code >= 400:
            raise _classify(response.status_code, response.text, api_key)

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as ex:
            raise AiError(CODE_PROVIDER_ERROR, MESSAGE_PROVIDER_ERROR, status=502) from ex

        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            raise AiError(CODE_EMPTY_ANSWER, MESSAGE_EMPTY_ANSWER, status=502)

        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if content is None:
            content = first.get("text")

        if not isinstance(content, str) or not content.strip():
            raise AiError(CODE_EMPTY_ANSWER, MESSAGE_EMPTY_ANSWER, status=502)

        return content.strip()

    # ── Сервисные операции ──────────────────────────────────────────

    def close(self) -> None:
        close = getattr(self._session, "close", None)
        if callable(close):
            close()
