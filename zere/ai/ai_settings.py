"""Настройки выбора ИИ: облачный ключ пользователя или локальная модель.

Файл `config/ai.json` (gitignored) — единственное место, где лежит ключ.
Ключ используется ТОЛЬКО на бэкенде и никогда не отдаётся клиенту: наружу
уходит маска вида «sk-...abcd» (требования безопасности задачи).

Приоритет источников ключа:
1. `config/ai.json` — ключ пользователя (вводится в панели, удаляется кнопкой);
2. переменные окружения сервера — ключ владельца (`ZERE_CLOUD_API_KEY`).
   Он нужен только для аккаунта владельца: обычный пользователь его не
   видит и не может им пользоваться, если у него есть свой ключ.

Режим (`mode`):
- `auto`  — облако, если есть рабочий ключ, иначе локальная модель;
- `cloud` — только облачный ключ;
- `local` — только локальная модель.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional

from zere import paths
from zere.core.security.file_access import restrict_to_owner

# ── Режимы выбора провайдера ────────────────────────────────────────
MODE_AUTO = "auto"
MODE_CLOUD = "cloud"
MODE_LOCAL = "local"
MODES = (MODE_AUTO, MODE_CLOUD, MODE_LOCAL)

# ── Пресеты облачных провайдеров с OpenAI-совместимым API ───────────
# Один универсальный клиент (/chat/completions) + список готовых адресов:
# пользователь выбирает пресет или вводит свой Base URL («custom»).
PROVIDER_PRESETS: tuple[dict[str, str], ...] = (
    {
        "id": "openai",
        "label": "OpenAI",
        "baseUrl": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "docsUrl": "https://platform.openai.com/api-keys",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "baseUrl": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "docsUrl": "https://platform.deepseek.com/api_keys",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "baseUrl": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "docsUrl": "https://openrouter.ai/keys",
    },
    {
        "id": "groq",
        "label": "Groq",
        "baseUrl": "https://api.groq.com/openai/v1",
        "model": "llama-3.1-8b-instant",
        "docsUrl": "https://console.groq.com/keys",
    },
    {
        # OpenAI-совместимый Chat Completions: https://opencode.ai/zen/go/v1
        # Модели Responses/Anthropic (grok, gpt-*-luna, minimax, qwen) здесь
        # не подходят — выбран glm как дешёвый и с большим месячным лимитом.
        "id": "opencode-go",
        "label": "OpenCode Go (подписка)",
        "baseUrl": "https://opencode.ai/zen/go/v1",
        "model": "glm-5.3-flash",
        "docsUrl": "https://opencode.ai/console",
    },
    {
        "id": "custom",
        "label": "Свой OpenAI-совместимый сервер",
        "baseUrl": "",
        "model": "",
        "docsUrl": "",
    },
)

PROVIDER_IDS = tuple(preset["id"] for preset in PROVIDER_PRESETS)

# ── Локальные модели для слабых ПК ──────────────────────────────────
# Порядок — от «русский важнее всего» к «лишь бы влезло»: у малых моделей
# русского почти нет (см. docs/LOCAL_MODELS_RESEARCH.md, §7), поэтому
# Qwen2.5-линейка (2024) заменена на Qwen3.5 и русско-ориентированный T-lite.
# sizeHint — размер загрузки в Q4: тег без суффикса кванта тянет Q8-блоб
# вдвое больше (qwen3.5:2b = 2.7 ГБ против qwen3.5:2b-q4_K_M = 1.9 ГБ).
LOCAL_MODEL_SUGGESTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "t-tech/T-lite-it-2.1:q4_K_M",
        "label": "T-lite 2.1 (8B) — лучший русский, 16 ГБ",
        "tier": "medium",
        "sizeHint": "~5 ГБ",
    },
    {
        "id": "qwen3.5:4b-q4_K_M",
        "label": "qwen3.5:4b — быстрый, русский нормальный, 8–16 ГБ",
        "tier": "medium",
        "sizeHint": "~3.3 ГБ",
    },
    {
        "id": "qwen3.5:2b-q4_K_M",
        "label": "qwen3.5:2b — слабый ПК, 8 ГБ",
        "tier": "light",
        "sizeHint": "~1.9 ГБ",
    },
    {
        "id": "qwen3.5:0.8b",
        "label": "qwen3.5:0.8b — очень слабый ПК, 4 ГБ",
        "tier": "tiny",
        "sizeHint": "~1.2 ГБ",
    },
    {
        "id": "qwen3.5:9b-q4_K_M",
        "label": "qwen3.5:9b — максимум качества Qwen, 16 ГБ",
        "tier": "medium",
        "sizeHint": "~6.6 ГБ",
    },
    {
        "id": "qwen2.5:0.5b",
        "label": "qwen2.5:0.5b — последний резерв, 4 ГБ (русский слабый)",
        "tier": "tiny",
        "sizeHint": "~0.4 ГБ",
    },
)

# Модель, которую панель предлагает скачать одной кнопкой.
# Русский — обязательное требование ZERE, поэтому по умолчанию берётся
# русско-ориентированная модель, а не самая маленькая.
DEFAULT_LOCAL_MODEL = "t-tech/T-lite-it-2.1:q4_K_M"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"

# ── Статусы ключа ───────────────────────────────────────────────────
KEY_UNKNOWN = "unknown"
KEY_OK = "ok"
KEY_INVALID = "invalid"

# ── Источник ключа ──────────────────────────────────────────────────
SOURCE_NONE = "none"
SOURCE_USER = "user"
SOURCE_OWNER = "owner"

# ── Переменные окружения (ключ владельца/админа) ────────────────────
ENV_MODE = "ZERE_AI_MODE"
ENV_CLOUD_API_KEY = "ZERE_CLOUD_API_KEY"
ENV_CLOUD_BASE_URL = "ZERE_CLOUD_BASE_URL"
ENV_CLOUD_MODEL = "ZERE_CLOUD_MODEL"
ENV_CLOUD_PROVIDER = "ZERE_CLOUD_PROVIDER"
ENV_LOCAL_BASE_URL = "ZERE_LOCAL_BASE_URL"
ENV_LOCAL_MODEL = "ZERE_LOCAL_MODEL"


def mask_key(key: Optional[str]) -> str:
    """Маска ключа для интерфейса: «sk-...abcd».

    Полный ключ не покидает бэкенд; в UI и в логах — только маска.
    """
    if not key:
        return ""

    key = key.strip()
    if len(key) <= 8:
        return "***"

    return f"{key[:3]}...{key[-4:]}"


@dataclass
class AiSettings:
    """Настройки подключения ИИ (персист в config/ai.json)."""

    # auto | cloud | local
    mode: str = MODE_AUTO

    # --- Облачная модель (OpenAI-совместимый API) -------------------
    cloud_provider: str = "openai"
    cloud_base_url: str = "https://api.openai.com/v1"
    cloud_model: str = "gpt-4o-mini"
    # Секрет: на диск в config/ai.json (права 0600), наружу — только маска.
    cloud_api_key: str = ""
    # unknown | ok | invalid — результат последней проверки ключа.
    cloud_key_status: str = KEY_UNKNOWN
    cloud_key_checked_at: str = ""

    # --- Локальная модель (Ollama или другой OpenAI-совместимый) ----
    local_base_url: str = DEFAULT_LOCAL_BASE_URL
    local_model: str = DEFAULT_LOCAL_MODEL

    # ── Загрузка/сохранение ─────────────────────────────────────────

    @classmethod
    def load(cls, *, apply_env: bool = True) -> "AiSettings":
        """Читает config/ai.json; битый/отсутствующий файл → значения по умолчанию.

        Ключи принимаются и в snake_case (Python-редакция), и в camelCase
        (старые сборки C#-редакции): файл `config/ai.json` общий, и раньше
        каждая редакция писала свой формат — при расхождении настройки
        (облачная модель, ключ) молча сбрасывались на значения по умолчанию.
        """
        settings = cls()
        path = paths.ai_config_path()

        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    settings._apply_file(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            settings = cls()

        if apply_env:
            settings._apply_env()

        return settings

    def _apply_file(self, data: dict[str, Any]) -> None:
        """Переносит поля файла в настройки: snake_case и camelCase, без None."""
        known = {f.name for f in fields(self)}
        aliases = {_camel(name): name for name in known}

        for key, value in data.items():
            if value is None:
                continue

            target = key if key in known else aliases.get(key)
            if target is not None:
                setattr(self, target, value)

    def _apply_env(self) -> None:
        """Переменные окружения владельца сервера (перекрывают значения из файла).

        Ключ владельца живёт только в окружении сервера: он не попадает
        в config/ai.json, не отдаётся клиенту и не может быть удалён из UI.
        """
        env_mode = os.environ.get(ENV_MODE, "").strip().lower()
        if env_mode in MODES:
            self.mode = env_mode

        provider = os.environ.get(ENV_CLOUD_PROVIDER, "").strip().lower()
        if provider in PROVIDER_IDS:
            self.cloud_provider = provider

        base_url = os.environ.get(ENV_CLOUD_BASE_URL, "").strip()
        if base_url:
            self.cloud_base_url = base_url

        model = os.environ.get(ENV_CLOUD_MODEL, "").strip()
        if model:
            self.cloud_model = model

        local_base = os.environ.get(ENV_LOCAL_BASE_URL, "").strip()
        if local_base:
            self.local_base_url = local_base

        local_model = os.environ.get(ENV_LOCAL_MODEL, "").strip()
        if local_model:
            self.local_model = local_model

    def save(self) -> None:
        """Атомарная запись с правами 0600 (файл содержит секрет)."""
        path = paths.ai_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {f.name: getattr(self, f.name) for f in fields(self)}
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Секрет: сужаем права до владельца ещё до публикации файла на месте.
        # На Windows os.chmod ACL не меняет — нужен icacls, см.
        # zere/core/security/file_access.py (раньше ключ наследовал права
        # папки и читался любым локальным пользователем).
        restrict_to_owner(tmp_path)

        tmp_path.replace(path)

        restrict_to_owner(path)

    # ── Ключ: источники и маски ─────────────────────────────────────

    @staticmethod
    def env_api_key() -> str:
        return os.environ.get(ENV_CLOUD_API_KEY, "").strip()

    def user_api_key(self) -> str:
        return (self.cloud_api_key or "").strip()

    def active_key(self) -> tuple[str, str]:
        """(ключ, источник): ключ пользователя важнее ключа владельца.

        Ключ владельца используется только как запасной вариант и только
        для его аккаунта — в UI он помечен как «ключ сервера».
        """
        user_key = self.user_api_key()
        if user_key:
            return user_key, SOURCE_USER

        owner_key = self.env_api_key()
        if owner_key:
            return owner_key, SOURCE_OWNER

        return "", SOURCE_NONE

    def has_key(self) -> bool:
        key, _ = self.active_key()
        return bool(key)

    def has_working_key(self) -> bool:
        """Ключ есть и не помечен как нерабочий (проверенный или ещё не проверенный)."""
        key, _ = self.active_key()
        return bool(key) and self.cloud_key_status != KEY_INVALID

    # ── Публичное представление (без секретов) ──────────────────────

    def cloud_public(self) -> dict[str, Any]:
        key, source = self.active_key()

        return {
            "provider": self.cloud_provider,
            "baseUrl": self.cloud_base_url,
            "model": self.cloud_model,
            "keySaved": bool(key),
            "keySource": source,
            # Маска: полный ключ клиенту не отдаётся никогда.
            "keyMask": mask_key(key),
            "keyStatus": self.cloud_key_status if key else KEY_UNKNOWN,
            "keyCheckedAt": self.cloud_key_checked_at or None,
        }

    def local_public(self) -> dict[str, Any]:
        return {
            "baseUrl": self.local_base_url,
            "model": self.local_model,
            "suggestions": [dict(item) for item in LOCAL_MODEL_SUGGESTIONS],
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "cloud": self.cloud_public(),
            "local": self.local_public(),
            "presets": [dict(preset) for preset in PROVIDER_PRESETS],
        }

    # ── Совместимость с camelCase (как у ZereConfig) ────────────────

    _CAMEL_ALIASES = {
        "Mode": "mode",
        "CloudProvider": "cloud_provider",
        "CloudBaseUrl": "cloud_base_url",
        "CloudModel": "cloud_model",
        "CloudKeyStatus": "cloud_key_status",
        "LocalBaseUrl": "local_base_url",
        "LocalModel": "local_model",
    }

    def __getattr__(self, name: str) -> Any:
        target = self._CAMEL_ALIASES.get(name)
        if target is not None:
            return getattr(self, target)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def to_camel_dict(self) -> dict[str, Any]:
        """Словарь настроек для UI (camelCase, без секрета)."""
        data = asdict(self)
        data.pop("cloud_api_key", None)
        return {_camel(key): value for key, value in data.items()}


def description_path(path: Optional[Path] = None) -> str:
    """Человекочитаемый путь к файлу настроек ИИ (для UI/логов)."""
    target = path or paths.ai_config_path()
    try:
        return str(target.relative_to(paths.PROJECT_ROOT))
    except ValueError:
        return str(target)


def _camel(key: str) -> str:
    """snake_case → camelCase (как ключи config.json)."""
    head, *tail = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)
