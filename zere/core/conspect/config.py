"""Настройки конспектора: config/conspect.json + хранилище из config/mcp.json.

Два источника, потому что у них разная природа:

- **хранилище заметок** уже задано для MCP-плагина заметок
  (`config/mcp.json`, `env.SEEKSTONE_VAULT`). Второй раз тот же путь
  спрашивать у пользователя нельзя: разойдётся — конспекты уедут в другую
  папку, чем всё остальное;
- **всё остальное** (папка конспектов, теги, размер части, потолки) —
  личные предпочтения, они живут в `config/conspect.json`.

Файл необязателен: без него конспектор работает на значениях по умолчанию,
а хранилище всё равно берётся из `config/mcp.json`. Читаются и snake_case, и
camelCase имена — как в `config/ai.json` и `config/mcp.json`: у проекта две
редакции, и файл настроек не должен молча сбрасывать чужие ключи.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from zere import paths
from zere.core.logging.log_service import log_error

#: Папка конспектов внутри хранилища Obsidian.
DEFAULT_FOLDER = "Конспекты"

#: Теги заметки-конспекта (во frontmatter, а не в тексте: так их видит Obsidian).
DEFAULT_TAGS: tuple[str, ...] = ("конспект",)

#: Размер одной части материала в символах. При `num_ctx = 2048` и русском
#: тексте (~2.5 символа на токен) 2400 символов ≈ 960 токенов: часть плюс
#: промпт и ответ помещаются в окно модели с запасом.
DEFAULT_CHUNK_CHARS = 2400

#: Перекрытие соседних частей: мысль на стыке не должна потеряться.
DEFAULT_CHUNK_OVERLAP = 200

#: Потолок числа частей: это число вызовов модели. На слабом CPU один вызов
#: 8B-модели — десятки секунд, сорок частей — уже десятки минут.
DEFAULT_MAX_CHUNKS = 40

#: Сколько символов материала берём в чат. Больше — не интерактивно: панель
#: ждала бы ответ минутами. Для длинных материалов есть CLI (docs/CONSPECT.md).
DEFAULT_INTERACTIVE_MAX_CHARS = 20_000

#: Жёсткий потолок входного материала: защита от «конспекта» файла на 200 МБ.
DEFAULT_MAX_SOURCE_CHARS = 400_000

#: Потолок скачиваемой страницы (символов HTML) — как maxSourceChars, но для сети.
DEFAULT_MAX_DOWNLOAD_CHARS = 2_000_000

DEFAULT_TIMEOUT_SECONDS = 60


def _pick(raw: dict[str, Any], *names: str, default: Any) -> Any:
    """Первое найденное значение из имён (snake_case и camelCase)."""
    for name in names:
        if name in raw:
            return raw[name]

    return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "да", "yes", "on")

    if isinstance(value, (int, float)):
        return bool(value)

    return default


def _as_int(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default

    return number if number >= minimum else minimum


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_tags(value: Any, default: Sequence[str]) -> tuple[str, ...]:
    """Теги: список или строка «конспект, обучение». Пустые значения отброшены."""
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        return tuple(default)

    tags = tuple(part.strip().lstrip("#") for part in parts if part and part.strip())

    return tags or tuple(default)


def _as_paths(value: Any, default: Sequence[str]) -> tuple[str, ...]:
    """Список подпапок хранилища, куда разрешено писать конспекты."""
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        return tuple(default)

    return tuple(part.strip().strip("/\\") for part in parts if part and part.strip())


@dataclass
class ConspectSettings:
    """Настройки конспектора. Значения по умолчанию — рабочие «из коробки»."""

    enabled: bool = True
    #: Пусто — берём хранилище из config/mcp.json (SEEKSTONE_VAULT).
    vault: str = ""
    folder: str = DEFAULT_FOLDER
    tags: tuple[str, ...] = field(default_factory=lambda: tuple(DEFAULT_TAGS))
    #: Раскладывать конспекты по подпапкам YYYY-MM внутри папки конспектов.
    subfolder_by_month: bool = True
    #: Разрешённые подпапки хранилища (по мотивам SEEKSTONE_WRITE_PATHS):
    #: пусто — писать можно только в папку конспектов.
    write_paths: tuple[str, ...] = ()
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    max_chunks: int = DEFAULT_MAX_CHUNKS
    interactive_max_chars: int = DEFAULT_INTERACTIVE_MAX_CHARS
    max_source_chars: int = DEFAULT_MAX_SOURCE_CHARS
    max_download_chars: int = DEFAULT_MAX_DOWNLOAD_CHARS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    temperature: float = 0.3
    #: Ответ модели на одну часть материала.
    max_tokens_per_chunk: int = 400
    #: Ответ модели на сводку частей (это и есть текст конспекта).
    max_tokens_summary: int = 900

    def __post_init__(self) -> None:
        # Перекрытие не может быть больше части — иначе чанкер зациклится.
        if self.chunk_overlap >= self.chunk_chars:
            self.chunk_overlap = max(0, self.chunk_chars // 4)

    @property
    def resolved_folder(self) -> str:
        return (self.folder or DEFAULT_FOLDER).strip().strip("/\\") or DEFAULT_FOLDER


def load_conspect_settings(path: Optional[Path] = None) -> ConspectSettings:
    """Читает `config/conspect.json`. Нет файла или он битый — значения по умолчанию.

    Битый файл не должен ломать конспектор молча: пишем причину в журнал,
    но продолжаем на умолчаниях (как `load_server` в MCP-плагинах).
    """
    config_path = path if path is not None else paths.conspect_config_path()

    if not config_path.is_file():
        return ConspectSettings()

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        log_error("ConspectConfig", f"{config_path.name}: {ex}")
        return ConspectSettings()

    if not isinstance(raw, dict):
        log_error("ConspectConfig", f"{config_path.name}: ожидался объект JSON")
        return ConspectSettings()

    defaults = ConspectSettings()
    vault = _pick(raw, "vault", "vaultPath", "obsidianVault", default=defaults.vault)

    return ConspectSettings(
        enabled=_as_bool(_pick(raw, "enabled", default=defaults.enabled), defaults.enabled),
        vault=str(vault or "").strip(),
        folder=str(_pick(raw, "folder", "conspectFolder", default=defaults.folder) or ""),
        tags=_as_tags(_pick(raw, "tags", default=None), defaults.tags),
        subfolder_by_month=_as_bool(
            _pick(raw, "subfolderByMonth", "subfolder_by_month", default=defaults.subfolder_by_month),
            defaults.subfolder_by_month,
        ),
        write_paths=_as_paths(
            _pick(raw, "writePaths", "write_paths", default=None), defaults.write_paths
        ),
        chunk_chars=_as_int(
            _pick(raw, "chunkChars", "chunk_chars", default=defaults.chunk_chars),
            defaults.chunk_chars,
            minimum=200,
        ),
        chunk_overlap=_as_int(
            _pick(raw, "chunkOverlap", "chunk_overlap", default=defaults.chunk_overlap),
            defaults.chunk_overlap,
            minimum=0,
        ),
        max_chunks=_as_int(
            _pick(raw, "maxChunks", "max_chunks", default=defaults.max_chunks),
            defaults.max_chunks,
            minimum=1,
        ),
        interactive_max_chars=_as_int(
            _pick(
                raw,
                "interactiveMaxChars",
                "interactive_max_chars",
                default=defaults.interactive_max_chars,
            ),
            defaults.interactive_max_chars,
            minimum=1000,
        ),
        max_source_chars=_as_int(
            _pick(raw, "maxSourceChars", "max_source_chars", default=defaults.max_source_chars),
            defaults.max_source_chars,
            minimum=1000,
        ),
        max_download_chars=_as_int(
            _pick(raw, "maxDownloadChars", "max_download_chars", default=defaults.max_download_chars),
            defaults.max_download_chars,
            minimum=1000,
        ),
        timeout_seconds=_as_int(
            _pick(raw, "timeoutSeconds", "timeout_seconds", default=defaults.timeout_seconds),
            defaults.timeout_seconds,
            minimum=5,
        ),
        temperature=_as_float(
            _pick(raw, "temperature", default=defaults.temperature), defaults.temperature
        ),
        max_tokens_per_chunk=_as_int(
            _pick(
                raw,
                "maxTokensPerChunk",
                "max_tokens_per_chunk",
                default=defaults.max_tokens_per_chunk,
            ),
            defaults.max_tokens_per_chunk,
            minimum=64,
        ),
        max_tokens_summary=_as_int(
            _pick(raw, "maxTokensSummary", "max_tokens_summary", default=defaults.max_tokens_summary),
            defaults.max_tokens_summary,
            minimum=64,
        ),
    )


def vault_from_mcp_config(path: Optional[Path] = None) -> str:
    """Путь к хранилищу Obsidian из `config/mcp.json` (`env.SEEKSTONE_VAULT`).

    Хранилище уже задано там для плагина заметок — конспектор обязан писать
    туда же. Ошибки чтения не критичны: вернём пустую строку, вызывающий
    скажет пользователю, что хранилище не задано.
    """
    config_path = path if path is not None else paths.mcp_config_path()

    if not config_path.is_file():
        return ""

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        log_error("ConspectConfig", f"{config_path.name}: {ex}")
        return ""

    servers = raw.get("servers") if isinstance(raw, dict) else None
    obsidian = servers.get("obsidian") if isinstance(servers, dict) else None
    env = obsidian.get("env") if isinstance(obsidian, dict) else None

    if not isinstance(env, dict):
        return ""

    for key in ("SEEKSTONE_VAULT", "seekstone_vault", "vault"):
        value = env.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def resolve_vault(settings: ConspectSettings, *, mcp_config_path: Optional[Path] = None) -> str:
    """Итоговое хранилище: своё значение из conspect.json, иначе из mcp.json."""
    if settings.vault.strip():
        return settings.vault.strip()

    return vault_from_mcp_config(mcp_config_path)


__all__ = [
    "DEFAULT_CHUNK_CHARS",
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_FOLDER",
    "DEFAULT_INTERACTIVE_MAX_CHARS",
    "DEFAULT_MAX_CHUNKS",
    "DEFAULT_MAX_SOURCE_CHARS",
    "DEFAULT_TAGS",
    "ConspectSettings",
    "load_conspect_settings",
    "resolve_vault",
    "vault_from_mcp_config",
]
