"""Конспектор ZERE: материал → конспект в хранилище Obsidian.

Зачем отдельный пакет, а не «ещё один обработчик»: конспект длинного
материала — это не одна генерация, а конвейер (docs/CONSPECT.md):

    источник → текст → чанки → конспект по частям → сводка → заметка

Ключевое ограничение проекта — `num_ctx = 2048` в `OllamaClient`
(`zere/ai/ollama_client.py`): часовая лекция в окно модели не входит, и
обычный чат молча увидел бы только хвост текста. Поэтому здесь материал
режется на части, каждая конспектируется отдельно, а затем части сводятся
в один конспект (map-reduce). Это работает и на локальной 8B-модели, и на
облачном ключе, и ничего не меняет в существующем контракте ИИ.

Запись заметки идёт **напрямую в файлы хранилища** (без MCP-сервера и без
запущенного Obsidian): сторонний процесс в критическом пути конспекта не
нужен, а поиск и чтение заметок остаются за MCP-плагином (seekstone).

Входы: обработчик конвейера (`zere/core/handlers/conspect_handler.py`) для
чата и голоса и CLI (`python -m zere.core.conspect`) для длинных материалов.
"""

from __future__ import annotations

from zere.core.conspect.ai_bridge import model_label, preflight
from zere.core.conspect.config import (
    ConspectSettings,
    load_conspect_settings,
    resolve_vault,
    vault_from_mcp_config,
)
from zere.core.conspect.contract import build_note, note_title
from zere.core.conspect.errors import ConspectError
from zere.core.conspect.summarizer import ConspectResult, Summarizer, plan_parts
from zere.core.conspect.text import SourceText, is_url, read_source
from zere.core.conspect.vault import VaultWriter

__all__ = [
    "ConspectError",
    "ConspectResult",
    "ConspectSettings",
    "SourceText",
    "Summarizer",
    "VaultWriter",
    "build_note",
    "is_url",
    "load_conspect_settings",
    "model_label",
    "note_title",
    "plan_parts",
    "preflight",
    "read_source",
    "resolve_vault",
    "vault_from_mcp_config",
]
