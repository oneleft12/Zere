"""Сервис выбора провайдера ИИ: облачный ключ пользователя или локальная модель.

Собирает воедино настройки (`AiSettings`), облачный OpenAI-совместимый
клиент (`CloudClient`) и проверку локального сервера (`LocalModelService`),
а `AiProviderProxy` подставляется в `AIHandler` вместо прежнего
`OllamaClient` — интерфейс `generate/warmup/close` сохранён, поэтому
остальной код (голос, консоль, панель) не меняется.

Приоритет (требование 5 задачи):
- `auto`  — облачный ключ, если он есть; иначе локальная модель;
- `cloud` — только ключ;
- `local` — только локальная модель.

Ключ живёт только здесь (на бэкенде): наружу — маска «sk-...abcd»,
в логи — ничего (см. redact_secrets в LogService).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Iterator, Optional

from zere.ai.ai_settings import (
    KEY_INVALID,
    KEY_OK,
    KEY_UNKNOWN,
    MODE_AUTO,
    MODE_CLOUD,
    MODE_LOCAL,
    MODES,
    PROVIDER_PRESETS,
    AiSettings,
    description_path,
    mask_key,
)
from zere.ai.cloud_client import (
    CODE_KEY_INVALID,
    CODE_MODEL_UNAVAILABLE,
    CODE_NETWORK,
    AiError,
    CloudClient,
)
from zere.ai.local_model import (
    CODE_LOCAL_MODEL_MISSING,
    CODE_LOCAL_SERVER_DOWN,
    MESSAGE_LOCAL_MODEL_MISSING,
    MESSAGE_LOCAL_SERVER_DOWN,
    PROBE_CACHE_SECONDS,
    LocalModelService,
)
from zere.ai.ollama_client import OllamaClient
from zere.core.logging.log_service import log_error, redact_secrets

# Точная формулировка из задачи (требование 5): ни ключа, ни локальной модели.
MESSAGE_NOT_CONFIGURED = "Чтобы начать, введите API-ключ или установите локальную модель"

PROVIDER_CLOUD = "cloud"
PROVIDER_LOCAL = "local"
PROVIDER_NONE = "none"

MESSAGE_CLOUD_KEY_MISSING = (
    "Введите API-ключ облачной модели в настройках ИИ или переключитесь на локальную модель"
)
MESSAGE_KEY_INVALID_HINT = (
    "Неверный API-ключ. Проверьте ключ в настройках ИИ («Проверить ключ»)."
)
MESSAGE_LOCAL_SERVER_HINT = (
    "Локальный сервер не запущен. Установите и запустите Ollama: https://ollama.com/download"
)


class AiService:
    """Настройки ИИ, проверки и выбор провайдера для одного пользователя панели."""

    def __init__(
        self,
        settings: Optional[AiSettings] = None,
        *,
        session: Optional[Any] = None,
        config: Optional[Any] = None,
        local_client_factory: Optional[Any] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._config = config
        self._settings = settings if settings is not None else AiSettings.load()

        self._cloud = CloudClient(session, timeout=self._timeout_seconds())
        self._local = LocalModelService(session, client=self._cloud)

        # Фабрика локального клиента: по умолчанию — нативный OllamaClient
        # (паритет с прежним поведением), в тестах подменяется.
        self._local_client_factory = local_client_factory or self._create_ollama_client

        self._local_client: Optional[Any] = None
        self._local_client_model: str = ""

        self._probe_cache: Optional[tuple[float, str, dict[str, Any]]] = None

        self.proxy = AiProviderProxy(self)

    # ── Настройки ───────────────────────────────────────────────────

    @property
    def settings(self) -> AiSettings:
        return self._settings

    def _timeout_seconds(self) -> int:
        value = getattr(self._config, "llm_timeout_seconds", 60) if self._config else 60
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            timeout = 60
        return timeout if timeout > 0 else 60

    def _create_ollama_client(self, model: str) -> Any:
        keep_alive = getattr(self._config, "llm_keep_alive", -1) if self._config else -1
        timeout_minutes = (
            getattr(self._config, "ollama_timeout_minutes", 10) if self._config else 10
        )
        return OllamaClient(
            model,
            timeout_minutes,
            keep_alive=keep_alive,
            timeout_seconds=self._timeout_seconds(),
        )

    def reload(self) -> None:
        """Перечитывает config/ai.json (например, после правки вручную)."""
        with self._lock:
            self._settings = AiSettings.load()
            self._invalidate_local_client()
            self._invalidate_probe()

    def _invalidate_local_client(self) -> None:
        if self._local_client is not None:
            try:
                self._local_client.close()
            except Exception:  # noqa: BLE001 — закрытие best-effort
                pass
        self._local_client = None
        self._local_client_model = ""

    def _invalidate_probe(self) -> None:
        self._probe_cache = None

    # ── Проба локального сервера (с кэшем) ──────────────────────────

    def local_probe(self, *, force: bool = False, extra_roots: bool = False) -> dict[str, Any]:
        """Состояние локального сервера.

        extra_roots=True дополнительно пробует стандартные адреса Ollama
        (localhost/127.0.0.1/docker). Для фонового опроса статуса он не нужен:
        поиск по стандартным адресам — это отдельное действие пользователя
        («Проверить локальную модель») и лишняя задержка в /api/ai.
        """
        with self._lock:
            base_url = self._settings.local_base_url
            cached = self._probe_cache

            if (
                not force
                and cached is not None
                and cached[1] == base_url
                and cached[2] == extra_roots
                and (time.monotonic() - cached[0]) < PROBE_CACHE_SECONDS
            ):
                return cached[3]

        result = self._local.probe(base_url, extra_roots=extra_roots)

        with self._lock:
            self._probe_cache = (time.monotonic(), base_url, extra_roots, result)

        return result

    # ── Статус для панели (GET /api/ai) ─────────────────────────────

    def status(
        self,
        *,
        probe_local: bool = True,
        extra_roots: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            settings = self._settings

        cloud = settings.cloud_public()
        local_public = settings.local_public()

        if probe_local:
            probe = self.local_probe(force=force, extra_roots=extra_roots)
        else:
            probe = {
                "server": "unknown",
                "baseUrl": settings.local_base_url,
                "api": "",
                "models": [],
                "detail": "",
            }

        model = settings.local_model
        installed = self._local.installed(model, probe.get("models") or [])
        server_up = probe.get("server") == "up"
        can_pull = server_up and probe.get("api") == "ollama"

        if server_up and installed:
            local_status = "available"
            local_text = "Локальная модель доступна"
        elif server_up:
            local_status = "model-missing"
            local_text = "Локальная модель недоступна"
        else:
            local_status = "server-down"
            local_text = MESSAGE_LOCAL_SERVER_DOWN

        local = {
            **local_public,
            "server": "up" if server_up else "down",
            "api": probe.get("api") or "",
            "resolvedBaseUrl": probe.get("baseUrl") or settings.local_base_url,
            "models": list(probe.get("models") or []),
            "modelInstalled": installed,
            "status": local_status,
            "statusText": local_text,
            "detail": probe.get("detail") or "",
            "canPull": can_pull,
            "installHint": (
                None
                if server_up and installed
                else LocalModelService.install_hint(model)
            ),
        }

        active = self._active_provider(probe)

        if active == PROVIDER_CLOUD:
            summary = f"Подключено: облачная модель · {cloud['provider']}/{cloud['model']}"
            ready = True
            message = "Запросы идут в облачную модель."
        elif active == PROVIDER_LOCAL:
            summary = f"Подключено: локальная модель · {local['model']}"
            ready = True
            message = "Запросы идут в локальную модель."
        else:
            summary = "Подключите API-ключ или используйте локальную модель"
            ready = False
            message = MESSAGE_NOT_CONFIGURED

        return {
            "mode": settings.mode,
            "activeProvider": active,
            "ready": ready,
            "summary": summary,
            "message": message,
            "cloud": cloud,
            "local": local,
            "presets": [dict(preset) for preset in PROVIDER_PRESETS],
            "settingsPath": description_path(),
        }

    def _active_provider(self, probe: Optional[dict[str, Any]] = None) -> str:
        """Какой провайдер будет использован прямо сейчас (без сети, если можно)."""
        with self._lock:
            settings = self._settings
            mode = settings.mode
            cloud_ready = settings.has_key()
            key_status = settings.cloud_key_status

        if mode == MODE_CLOUD:
            return PROVIDER_CLOUD if cloud_ready else PROVIDER_NONE

        if mode == MODE_LOCAL:
            return self._local_ready(probe)

        # auto: облако при рабочем ключе, иначе локальная модель
        if cloud_ready and key_status != KEY_INVALID:
            return PROVIDER_CLOUD

        local = self._local_ready(probe)
        if local == PROVIDER_LOCAL:
            return PROVIDER_LOCAL

        # Ключ есть, но помечен нерабочим: честно показываем «нет провайдера»
        # (пользователю нужно перепроверить ключ), локальной модели тоже нет.
        return PROVIDER_NONE

    def _local_ready(self, probe: Optional[dict[str, Any]] = None) -> str:
        with self._lock:
            settings = self._settings

        data = probe if probe is not None else self.local_probe()

        if data.get("server") != "up":
            return PROVIDER_NONE

        if not self._local.installed(settings.local_model, data.get("models") or []):
            return PROVIDER_NONE

        return PROVIDER_LOCAL

    # ── Правка настроек ─────────────────────────────────────────────

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Частичное обновление настроек (mode/адреса/модели). Без ключа."""
        with self._lock:
            settings = self._settings

            if "mode" in payload:
                mode = payload["mode"]
                if mode not in MODES:
                    raise AiError(
                        "AI_VALIDATION",
                        f"Режим «{mode}» не поддерживается: {', '.join(MODES)}.",
                    )
                settings.mode = mode

            if "cloudProvider" in payload:
                settings.cloud_provider = str(payload["cloudProvider"])

            if "cloudBaseUrl" in payload:
                settings.cloud_base_url = str(payload["cloudBaseUrl"]).strip()

            if "cloudModel" in payload:
                settings.cloud_model = str(payload["cloudModel"]).strip()

            if "localBaseUrl" in payload:
                settings.local_base_url = str(payload["localBaseUrl"]).strip()

            if "localModel" in payload:
                settings.local_model = str(payload["localModel"]).strip()

            settings.save()
            self._invalidate_local_client()
            self._invalidate_probe()

        return self.status()

    def save_key(self, payload: dict[str, Any], *, validate: bool = True) -> dict[str, Any]:
        """Сохраняет ключ пользователя, предварительно проверив его (требование 3).

        Не рабочий ключ не сохраняется: клиент получает понятную ошибку.
        """
        api_key = str(payload.get("apiKey") or "").strip()

        if not api_key:
            raise AiError("AI_VALIDATION", "Введите API-ключ.", status=400)

        with self._lock:
            settings = self._settings
            if "cloudProvider" in payload:
                settings.cloud_provider = str(payload["cloudProvider"])
            if "cloudBaseUrl" in payload:
                settings.cloud_base_url = str(payload["cloudBaseUrl"]).strip()
            if "cloudModel" in payload:
                settings.cloud_model = str(payload["cloudModel"]).strip()

            base_url = settings.cloud_base_url
            model = settings.cloud_model

        if validate:
            self._verify_key(api_key, base_url, model)

        with self._lock:
            self._settings.cloud_api_key = api_key
            self._settings.cloud_key_status = KEY_OK
            self._settings.cloud_key_checked_at = _utc_now()
            self._settings.save()

        return self.status()

    def test_key(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Проверка ключа без сохранения (кнопка «Проверить ключ»)."""
        with self._lock:
            settings = self._settings
            base_url = str(payload.get("cloudBaseUrl") or settings.cloud_base_url).strip()
            model = str(payload.get("cloudModel") or settings.cloud_model).strip()

            provided = payload.get("apiKey")
            if provided:
                api_key = str(provided).strip()
            else:
                api_key, _source = settings.active_key()
                if not api_key:
                    raise AiError("AI_VALIDATION", "Сначала введите API-ключ.", status=400)

        result = self._verify_key(api_key, base_url, model)

        # Помечаем состояние ключа, только если проверялся активный ключ
        # (введённый «на пробу» в файл не пишется и статус не меняет).
        if not provided and settings.cloud_api_key == api_key:
            with self._lock:
                self._settings.cloud_key_status = KEY_OK
                self._settings.cloud_key_checked_at = _utc_now()
                self._settings.save()

        return {
            "ok": True,
            "message": result.get("message", "Ключ рабочий."),
            "models": list(result.get("models") or []),
            "checkedWith": result.get("checkedWith", "models"),
            "keyMask": mask_key(api_key),
        }

    def _verify_key(self, api_key: str, base_url: str, model: str) -> dict[str, Any]:
        """Рабочий запрос к API для проверки ключа; ошибка — AiError."""
        try:
            return self._cloud.test_key(base_url, api_key, model)
        except AiError as ex:
            log_error(
                "AiService",
                f"проверка ключа ({mask_key(api_key)}) не прошла: {ex.code}",
            )
            # Ключ пользователя помечаем нерабочим: панель покажет это в статусе.
            if ex.code == CODE_KEY_INVALID:
                with self._lock:
                    if self._settings.cloud_api_key == api_key:
                        self._settings.cloud_key_status = KEY_INVALID
                        self._settings.cloud_key_checked_at = _utc_now()
                        self._settings.save()
            raise

    def delete_key(self) -> dict[str, Any]:
        """Удаляет ключ пользователя (ключ владельца из окружения не трогаем)."""
        with self._lock:
            self._settings.cloud_api_key = ""
            self._settings.cloud_key_status = KEY_UNKNOWN
            self._settings.cloud_key_checked_at = ""
            self._settings.save()

        return self.status(probe_local=False)

    # ── Локальная модель: статус, тест, загрузка ────────────────────

    def local_status(self, *, force: bool = True) -> dict[str, Any]:
        """Состояние локальной модели (для GET /api/ai/local).

        Явная проверка пользователя: ищем сервер и на стандартных адресах
        Ollama, а не только по введённому Base URL.
        """
        return self.status(probe_local=True, extra_roots=True, force=force)["local"]

    def test_local(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}

        with self._lock:
            base_url = str(body.get("localBaseUrl") or self._settings.local_base_url).strip()
            model = str(body.get("localModel") or self._settings.local_model).strip()

        try:
            result = self._local.test(base_url, model)
        finally:
            self._invalidate_probe()

        return {
            "ok": True,
            "message": result["message"],
            "server": result["server"],
            "models": list(result.get("models") or []),
        }

    def pull_model(self, model: Optional[str] = None) -> Iterator[dict[str, Any]]:
        """SSE-события загрузки модели через локальный Ollama (кнопка «Скачать»)."""
        with self._lock:
            target = (model or self._settings.local_model).strip()
            base_url = self._settings.local_base_url

        try:
            for event in self._local.pull(base_url, target):
                if event.get("status") in ("done", "error"):
                    self._invalidate_probe()
                    self._invalidate_local_client()
                yield event
        except Exception as ex:  # noqa: BLE001 — поток не должен рвать соединение
            log_error("AiService", f"загрузка модели: {redact_secrets(str(ex))}")
            yield {
                "status": "error",
                "code": "AI_PULL_FAILED",
                "message": "Не удалось скачать модель — смотрите логи.",
            }

    # ── Генерация ───────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Главный вход: провайдер по приоритету, ошибки — понятным текстом.

        Сигнатура совпадает с OllamaClient.generate (в т.ч. позиционные
        аргументы) — AIHandler и голосовой режим вызывают её одинаково.
        """
        provider = self._active_provider()

        if provider == PROVIDER_CLOUD:
            try:
                return self._generate_cloud(prompt, system_prompt, temperature, max_tokens)
            except AiError as ex:
                log_error("AiService", f"облако: {ex.code}")
                # auto: облако упало — если есть локальная модель, отвечаем ею
                if self._settings.mode == MODE_AUTO and self._local_ready() == PROVIDER_LOCAL:
                    local_answer = self._try_local(prompt, system_prompt, temperature, max_tokens)
                    if local_answer is not None:
                        return local_answer
                return self._error_text(ex)

        if provider == PROVIDER_LOCAL:
            answer = self._try_local(prompt, system_prompt, temperature, max_tokens)
            if answer is not None:
                return answer
            return MESSAGE_LOCAL_SERVER_HINT

        return self._no_provider_text()

    def _generate_cloud(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        with self._lock:
            settings = self._settings
            api_key, _source = settings.active_key()
            base_url = settings.cloud_base_url
            model = settings.cloud_model

        if not api_key:
            raise AiError("AI_KEY_MISSING", MESSAGE_CLOUD_KEY_MISSING, status=400)

        return self._cloud.generate(
            prompt,
            system_prompt=system_prompt,
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _try_local(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> Optional[str]:
        """Локальная генерация; None — провайдер недоступен (текст даст вызывающий)."""
        probe = self.local_probe()

        if probe.get("server") != "up":
            return None

        with self._lock:
            settings = self._settings
            model = settings.local_model
            base_url = probe.get("baseUrl") or settings.local_base_url
            api = probe.get("api") or ""

        if not self._local.installed(model, probe.get("models") or []):
            return None

        try:
            if api == "openai":
                # Не-Ollama локальный сервер: тот же OpenAI-совместимый путь.
                try:
                    return self._cloud.generate(
                        prompt,
                        system_prompt=system_prompt,
                        base_url=base_url,
                        api_key="",
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except AiError as ex:
                    # Тексты облачных ошибок («облачный API», «ключ») для
                    # локального сервера не подходят: переводим в локальные.
                    log_error("AiService", f"локально (openai): {ex.code}")
                    if ex.code == CODE_MODEL_UNAVAILABLE:
                        return (
                            f"{MESSAGE_LOCAL_MODEL_MISSING}. Скачайте модель «{model}» "
                            "средствами вашего локального сервера."
                        )
                    return (
                        f"{MESSAGE_LOCAL_SERVER_DOWN} или не отвечает "
                        f"({base_url})."
                    )

            client = self._local_ollama_client(model)
            return client.generate(prompt, system_prompt, temperature, max_tokens=max_tokens)
        except AiError as ex:
            log_error("AiService", f"локально: {ex.code}")
            return self._error_text(ex)
        except Exception as ex:  # noqa: BLE001 — ошибка модели не роняет движок
            log_error("AiService", f"локально: {redact_secrets(str(ex))}")
            return MESSAGE_LOCAL_SERVER_HINT

    def _local_ollama_client(self, model: str) -> Any:
        with self._lock:
            if self._local_client is not None and self._local_client_model == model:
                return self._local_client

            self._invalidate_local_client()
            self._local_client = self._local_client_factory(model)
            self._local_client_model = model
            return self._local_client

    # ── Тексты ошибок (требование 11) ───────────────────────────────

    def _error_text(self, error: AiError) -> str:
        if error.code == CODE_KEY_INVALID:
            return MESSAGE_KEY_INVALID_HINT
        if error.code == CODE_LOCAL_SERVER_DOWN:
            return MESSAGE_LOCAL_SERVER_HINT
        if error.code == CODE_LOCAL_MODEL_MISSING:
            return self._local_missing_text()
        if error.code == CODE_MODEL_UNAVAILABLE:
            return error.message
        if error.code == CODE_NETWORK:
            return error.message
        return error.message

    def _local_missing_text(self) -> str:
        with self._lock:
            model = self._settings.local_model

        return (
            f"{MESSAGE_LOCAL_MODEL_MISSING}. Скачайте её в панели "
            f"(«Скачать модель») или командой: ollama pull {model}"
        )

    def _no_provider_text(self) -> str:
        """Нет рабочего провайдера — понятное объяснение причины.

        В режиме «Авто» (по умолчанию) — точная формулировка из задачи.
        В явных режимах сообщение конкретнее: ключ не работает / локальный
        сервер не запущен / модель не загружена.
        """
        with self._lock:
            settings = self._settings
            mode = settings.mode
            key_saved = settings.has_key()
            key_status = settings.cloud_key_status

        if key_saved and key_status == KEY_INVALID:
            return MESSAGE_KEY_INVALID_HINT

        if mode == MODE_LOCAL:
            probe = self.local_probe()
            if probe.get("server") != "up":
                return MESSAGE_LOCAL_SERVER_HINT
            return self._local_missing_text()

        return MESSAGE_NOT_CONFIGURED

    # ── Совместимость с OllamaClient ────────────────────────────────

    def warmup(self) -> None:
        """Прогрев активного локального провайдера (облако не прогреваем)."""
        if self._active_provider() != PROVIDER_LOCAL:
            return

        try:
            probe = self.local_probe()
            if probe.get("api") == "ollama":
                with self._lock:
                    model = self._settings.local_model
                self._local_ollama_client(model).warmup()
        except Exception as ex:  # noqa: BLE001 — прогрев не критичен
            log_error("AiService", f"прогрев: {redact_secrets(str(ex))}")

    def close(self) -> None:
        self._invalidate_local_client()
        self._cloud.close()
        self._local.close()


class AiProviderProxy:
    """Прослойка в AIHandler: интерфейс OllamaClient, выбор провайдера на лету.

    Панель меняет настройки ИИ без перезапуска ZERE — прокси читает их
    на каждый запрос.
    """

    def __init__(self, service: AiService) -> None:
        self._service = service

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        return self._service.generate(
            prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def warmup(self) -> None:
        self._service.warmup()

    def close(self) -> None:
        self._service.close()

    @property
    def service(self) -> AiService:
        return self._service


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
