"""Локальная модель: Ollama или другой OpenAI-совместимый сервер.

Проверки (требование 7 задачи):
- запущен ли локальный сервер;
- какие модели доступны;
- проходит ли тестовый запрос.

Ollama-специфика (нативные `/api/tags` и `/api/pull`) включается, когда
сервер по адресу отвечает как Ollama: тогда доступна кнопка «Скачать
модель» с прогрессом. Для прочих OpenAI-совместимых локальных серверов
работают `/models` и `/chat/completions`.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Optional
from urllib.parse import urlsplit

import requests

from zere.ai.cloud_client import (
    CODE_MODEL_UNAVAILABLE,
    CODE_NETWORK,
    MESSAGE_MODEL_UNAVAILABLE,
    MESSAGE_NETWORK,
    CloudClient,
    AiError,
)

# ── Коды и тексты локальных ошибок (требование 11) ──────────────────
CODE_LOCAL_SERVER_DOWN = "AI_LOCAL_SERVER_DOWN"
CODE_LOCAL_MODEL_MISSING = "AI_LOCAL_MODEL_MISSING"
CODE_PULL_UNSUPPORTED = "AI_PULL_UNSUPPORTED"

MESSAGE_LOCAL_SERVER_DOWN = "Локальный сервер не запущен"
MESSAGE_LOCAL_MODEL_MISSING = "Локальная модель не загружена"

# Дополнительные адреса локального сервера. Пользовательский Base URL всегда
# пробуется первым; host.docker.internal здесь намеренно нет — его DNS-резолв
# на машине без Docker занимает секунды, а панель опрашивает статус регулярно
# (в OllamaUrlResolver он остаётся для сценария docker).
FALLBACK_ROOTS: tuple[str, ...] = (
    "http://127.0.0.1:11434",
    "http://localhost:11434",
)

DEFAULT_TIMEOUT = 4
PROBE_CACHE_SECONDS = 10.0


def normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def native_root(base_url: str) -> str:
    """OpenAI-совместимый Base URL → корень нативного API Ollama.

    «http://127.0.0.1:11434/v1» → «http://127.0.0.1:11434».
    """
    root = normalize_base_url(base_url)
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


def _short_model_name(name: str) -> str:
    """«qwen3.5:2b» → «qwen3.5» (имя без тега)."""
    return (name or "").split(":")[0].strip().lower()


def model_installed(model: str, models: list[str]) -> bool:
    """Есть ли модель среди локальных.

    Сравнение строгое (имя + тег): «qwen2.5:0.5b» и «qwen2.5:1.5b» — разные
    модели, иначе панель обещала бы скачивание уже существующей. Единственное
    исключение — неявный тег: «qwen3.5» == «qwen3.5:latest».
    """
    target = (model or "").strip().lower()
    if not target:
        return False

    for available in models:
        candidate = available.strip().lower()
        if candidate == target:
            return True
        if candidate == f"{target}:latest" or target == f"{candidate}:latest":
            return True
        # Тег может отсутствовать у одной из сторон при том же имени и теге
        # по умолчанию: «qwen2.5» ↔ «qwen2.5:latest» уже покрыто выше.

    return False


def _is_local_host(base_url: str) -> bool:
    """Адрес по умолчанию (loopback/docker) → пробуем и стандартные порты."""
    host = urlsplit(normalize_base_url(base_url)).hostname or ""
    return host.lower() in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}


class LocalModelService:
    """Проверка локального сервера/модели и загрузка модели через Ollama."""

    def __init__(
        self,
        session: Optional[Any] = None,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        client: Optional[CloudClient] = None,
    ) -> None:
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout
        self._client = client if client is not None else CloudClient(
            self._session, timeout=timeout, test_timeout=timeout
        )

    # ── Проба сервера ───────────────────────────────────────────────

    @staticmethod
    def installed(model: str, models: list[str]) -> bool:
        """Есть ли модель среди доступных локальному серверу."""
        return model_installed(model, models)

    def probe(self, base_url: str, *, extra_roots: bool = True) -> dict[str, Any]:
        """Ищет живой локальный сервер и список моделей.

        Возвращает словарь с ключами: server (up|down), baseUrl, api
        (openai|ollama|""), models, detail.
        """
        candidates: list[str] = []
        configured = normalize_base_url(base_url)
        if configured:
            candidates.append(configured)
        # Стандартные адреса Ollama подставляем только для локального
        # Base URL: иначе недоступный удалённый сервер «нашёлся» бы на
        # 127.0.0.1 и статус в панели был бы ложным.
        if extra_roots and (not configured or _is_local_host(configured)):
            for root in FALLBACK_ROOTS:
                candidate = f"{root}/v1"
                if candidate not in candidates:
                    candidates.append(candidate)

        for candidate in candidates:
            result = self._probe_one(candidate)
            if result is not None:
                return result

        return {
            "server": "down",
            "baseUrl": configured or "",
            "api": "",
            "models": [],
            "detail": MESSAGE_LOCAL_SERVER_DOWN,
        }

    def _probe_one(self, base_url: str) -> Optional[dict[str, Any]]:
        """Ollama определяется первой: нативный /api/tags даёт и /api/pull.

        Порядок важен: Ollama отвечает и на /v1/models, но native-проба
        сохраняет нативный путь генерации (кэш, keep_alive, прогрев) и
        включает кнопку «Скачать модель». Прочие OpenAI-совместимые
        локальные серверы уходят на /models.
        """
        result = self._probe_ollama(base_url)
        if result is not None:
            return result
        return self._probe_openai(base_url)

    def _probe_openai(self, base_url: str) -> Optional[dict[str, Any]]:
        """GET {base}/models — стандарт OpenAI-совместимых серверов."""
        try:
            models = self._client.list_models(base_url, "", timeout=self._timeout)
        except AiError:
            return None
        except Exception:  # noqa: BLE001 — проба не должна ронять панель
            return None

        return {
            "server": "up",
            "baseUrl": base_url,
            "api": "openai",
            "models": models,
            "detail": "Локальный сервер доступен (OpenAI-совместимый API).",
        }

    def _probe_ollama(self, base_url: str) -> Optional[dict[str, Any]]:
        """GET {root}/api/tags — нативный API Ollama (даёт и /api/pull)."""
        url = f"{native_root(base_url)}/api/tags"

        try:
            response = self._session.get(url, timeout=self._timeout)
        except requests.exceptions.RequestException:
            return None
        except Exception:  # noqa: BLE001
            return None

        if response.status_code >= 400:
            return None

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return None

        models: list[str] = []
        raw_models = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(raw_models, list):
            for item in raw_models:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    models.append(item["name"])

        return {
            "server": "up",
            "baseUrl": f"{native_root(base_url)}/v1",
            "api": "ollama",
            "models": models,
            "detail": "Ollama запущена.",
        }

    # ── Тестовый запрос ─────────────────────────────────────────────

    def test(self, base_url: str, model: str) -> dict[str, Any]:
        """Минимальный запрос к локальной модели.

        Возвращает {ok, message, server, models}. Ошибка — AiError с
        понятным текстом («Локальный сервер не запущен»,
        «Локальная модель не загружена»).
        """
        status = self.probe(base_url)

        if status["server"] != "up":
            raise AiError(CODE_LOCAL_SERVER_DOWN, MESSAGE_LOCAL_SERVER_DOWN, status=400)

        resolved_url = status["baseUrl"]
        models = status["models"]

        if not model_installed(model, models):
            hint = (
                f"Локальная модель «{model}» не загружена. "
                f"Скачайте её кнопкой «Скачать модель» или командой: ollama pull {model}"
            )
            raise AiError(CODE_LOCAL_MODEL_MISSING, hint, status=400)

        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
            "stream": False,
        }

        try:
            response = self._session.post(
                f"{resolved_url}/chat/completions",
                headers={"Content-Type": "application/json"},
                json=body,
                timeout=self._timeout,
            )
        except requests.exceptions.RequestException as ex:
            raise AiError(CODE_LOCAL_SERVER_DOWN, MESSAGE_LOCAL_SERVER_DOWN, status=400) from ex

        if response.status_code >= 400:
            if response.status_code == 404:
                raise AiError(
                    CODE_LOCAL_MODEL_MISSING, MESSAGE_LOCAL_MODEL_MISSING, status=400
                )
            raise AiError(
                CODE_MODEL_UNAVAILABLE,
                f"{MESSAGE_MODEL_UNAVAILABLE} (HTTP {response.status_code})",
                status=400,
            )

        return {
            "ok": True,
            "message": f"Локальная модель «{model}» отвечает.",
            "server": "up",
            "models": models,
        }

    # ── Загрузка модели (Ollama pull) ───────────────────────────────

    def can_pull(self, base_url: str) -> bool:
        return self.probe(base_url).get("api") == "ollama"

    def pull(self, base_url: str, model: str) -> Iterator[dict[str, Any]]:
        """Поток прогресса `ollama pull`: события status/percent/done/error."""
        status = self.probe(base_url)

        if status["server"] != "up":
            yield {
                "status": "error",
                "code": CODE_LOCAL_SERVER_DOWN,
                "message": MESSAGE_LOCAL_SERVER_DOWN,
            }
            return

        if status.get("api") != "ollama":
            yield {
                "status": "error",
                "code": CODE_PULL_UNSUPPORTED,
                "message": (
                    "Автозагрузка доступна только для Ollama. "
                    f"Загрузите модель средствами вашего сервера, затем повторите проверку."
                ),
            }
            return

        root = native_root(status["baseUrl"])

        try:
            response = self._session.post(
                f"{root}/api/pull",
                json={"model": model, "stream": True},
                timeout=None,
                stream=True,
            )
        except requests.exceptions.RequestException as ex:
            yield {
                "status": "error",
                "code": CODE_NETWORK,
                "message": f"{MESSAGE_NETWORK}: {ex}",
            }
            return

        if response.status_code >= 400:
            yield {
                "status": "error",
                "code": CODE_LOCAL_MODEL_MISSING,
                "message": (
                    f"Не удалось скачать модель «{model}» (HTTP {response.status_code})."
                ),
            }
            return

        last_error: Optional[str] = None

        for line in response.iter_lines():
            if not line:
                continue

            text = line.decode("utf-8") if isinstance(line, bytes) else str(line)

            try:
                data = json.loads(text)
            except (ValueError, json.JSONDecodeError):
                continue

            if not isinstance(data, dict):
                continue

            if isinstance(data.get("error"), str):
                last_error = data["error"]
                break

            event: dict[str, Any] = {"status": "pulling"}

            if isinstance(data.get("status"), str):
                event["detail"] = data["status"]

            total = data.get("total")
            completed = data.get("completed")

            if isinstance(total, int) and isinstance(completed, int) and total > 0:
                event["total"] = total
                event["completed"] = completed
                event["percent"] = round(completed * 100 / total, 1)

            yield event

            if data.get("status") == "success":
                break

        if last_error is not None:
            yield {
                "status": "error",
                "code": CODE_LOCAL_MODEL_MISSING,
                "message": f"Ollama не смогла скачать модель: {last_error}",
            }
            return

        yield {"status": "done", "model": model, "message": f"Модель «{model}» готова."}

    # ── Инструкция по установке (требование 8) ──────────────────────

    @staticmethod
    def install_hint(model: str) -> dict[str, Any]:
        """Понятная инструкция и команда для загрузки локальной модели."""
        return {
            "title": "Локальная модель не найдена",
            "steps": [
                "1. Установите Ollama: https://ollama.com/download (или winget install Ollama.Ollama).",
                "2. Запустите сервер: ollama serve (обычно запускается сам после установки).",
                f"3. Скачайте лёгкую модель: ollama pull {model}.",
                "4. Вернитесь в панель и нажмите «Проверить локальную модель».",
            ],
            "command": f"ollama pull {model}",
            "downloadUrl": "https://ollama.com/download",
            "model": model,
        }

    def close(self) -> None:
        close = getattr(self._session, "close", None)
        if callable(close):
            close()
