"""Оркестратор конспекта: материал → части → конспект по частям → сводка → заметка.

Схема (map-reduce) выбрана из-за жёсткого окна модели: `num_ctx = 2048` в
`OllamaClient`. Один вызов на материал невозможен физически — часовая лекция
не входит в окно, и модель увидела бы только конец текста. Поэтому:

1. **map** — каждая часть конспектируется отдельно (до 2400 символов);
2. **reduce** — заметки частей сводятся в один конспект по контракту.

Что здесь осознанно сделано «мягко»: сбой одной части не отменяет конспект
(часть помечается в сноске заметки), а сбой сводки не теряет работу — в
заметку ложатся заметки частей. Отказ возможен только тогда, когда модель не
ответила ни разу: тогда и конспекта нет, и заметку писать нечем.

Ошибки модели распознаются по тексту: `AiService.generate` возвращает
человеческое сообщение об ошибке («Введите API-ключ…»), а не исключение,
и без проверки этот текст уехал бы в заметку как конспект.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from zere.ai.ai_service import (
    MESSAGE_CLOUD_KEY_MISSING,
    MESSAGE_KEY_INVALID_HINT,
    MESSAGE_LOCAL_SERVER_HINT,
    MESSAGE_NOT_CONFIGURED,
)
from zere.ai.local_model import MESSAGE_LOCAL_MODEL_MISSING
from zere.core.conspect.chunking import chunk_stats, chunk_text
from zere.core.conspect.config import ConspectSettings
from zere.core.conspect.contract import (
    SYSTEM_PROMPT,
    build_note,
    clean_model_text,
    note_title,
    part_prompt,
    summary_prompt,
    today,
)
from zere.core.conspect.errors import (
    AI_FAILED,
    AI_UNAVAILABLE,
    SOURCE_EMPTY,
    ConspectError,
)
from zere.core.conspect.text import SourceText
from zere.core.conspect.vault import VaultWriter
from zere.core.logging.log_service import log_error

#: Тексты, которыми `AiService` сообщает «модели нет». Без этой проверки они
#: попали бы в заметку как конспект: generate возвращает их как обычный ответ.
_AI_ERROR_TEXTS = (
    MESSAGE_NOT_CONFIGURED,
    MESSAGE_CLOUD_KEY_MISSING,
    MESSAGE_KEY_INVALID_HINT,
    MESSAGE_LOCAL_SERVER_HINT,
    MESSAGE_LOCAL_MODEL_MISSING,
)

#: Дополнительные признаки ошибки в ответе модели.
_AI_ERROR_MARKERS = (
    "api-ключ",
    "api ключ",
    "локальный сервер не запущен",
    "локальная модель не загружена",
    "неверный api",
)

#: Ответ, которым модель сообщает «в этой части нет содержательного текста».
_NO_DATA = frozenset({"нет данных", "нет данных.", "no data", "(нет данных)"})

ProgressCallback = Callable[[int, int], None]


@dataclass
class ConspectResult:
    """Итог конспекта: заметка и то, как она получена."""

    title: str
    origin: str
    kind: str
    markdown: str
    parts_total: int
    parts_used: int
    parts_failed: int = 0
    truncated: bool = False
    seconds: float = 0.0
    model: str = ""
    #: Записанная заметка (None — сухой прогон: `--dry-run` в CLI).
    relative_path: Optional[str] = None
    absolute_path: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def written(self) -> bool:
        return bool(self.relative_path)


def _looks_like_error(answer: str) -> bool:
    """Ответ модели — это сообщение об ошибке ИИ, а не конспект."""
    text = (answer or "").strip().lower()

    if not text:
        return True

    if any(text == error.lower() for error in _AI_ERROR_TEXTS):
        return True

    return any(marker in text and len(text) < 400 for marker in _AI_ERROR_MARKERS)


def plan_parts(
    text: str, settings: ConspectSettings, *, max_chunks: Optional[int] = None
) -> tuple[int, bool]:
    """Сколько частей выйдет и обрежется ли материал по потолку.

    Нужно обработчику ДО запуска модели: отказать в слишком большом материале
    для чата дешевле, чем считать его двадцать минут.
    """
    chunks = chunk_text(text, settings.chunk_chars, settings.chunk_overlap)
    limit = settings.max_chunks if max_chunks is None else min(max_chunks, settings.max_chunks)

    return len(chunks), len(chunks) > limit


class Summarizer:
    """Делает конспект из материала и (если задан писатель) сохраняет заметку."""

    def __init__(
        self,
        ai: Any,
        settings: ConspectSettings,
        *,
        writer: Optional[VaultWriter] = None,
        preflight: Optional[Callable[[], Optional[str]]] = None,
        progress: Optional[ProgressCallback] = None,
        model: str = "",
    ) -> None:
        #: Любой объект с `generate(prompt, system_prompt, temperature, max_tokens)`:
        #: `AiProviderProxy`, `AiService` или фейк в тестах.
        self._ai = ai
        self._settings = settings
        self._writer = writer
        self._preflight = preflight
        self._progress = progress
        self._model = model

    @property
    def settings(self) -> ConspectSettings:
        return self._settings

    def conspect(
        self,
        source: SourceText,
        *,
        max_chunks: Optional[int] = None,
        write: bool = True,
    ) -> ConspectResult:
        """Конспектирует материал. Пишет заметку, если задан писатель и `write`."""
        settings = self._settings
        text = (source.text or "").strip()

        if not text:
            raise ConspectError(SOURCE_EMPTY, "Источник пуст — конспектировать нечего.")

        if self._preflight is not None:
            problem = self._preflight()

            if problem:
                raise ConspectError(AI_UNAVAILABLE, problem)

        if write and self._writer is not None:
            # Хранилище проверяем ДО работы модели: обидно потерять конспект
            # часовой лекции из-за опечатки в пути.
            self._writer.check()

        started = time.monotonic()
        chunks = chunk_text(text, settings.chunk_chars, settings.chunk_overlap)
        limit = settings.max_chunks if max_chunks is None else min(max_chunks, settings.max_chunks)
        truncated = len(chunks) > limit
        chunks = chunks[:limit]
        stats = chunk_stats(chunks)

        partials, failed, first_error = self._map(chunks, source, settings)

        if not partials:
            raise ConspectError(
                AI_FAILED,
                "Модель не дала ни одного ответа по материалу."
                + (f" Последняя причина: {first_error}" if first_error else ""),
            )

        body, body_warning = self._reduce(partials, source, settings)
        seconds = time.monotonic() - started
        title = note_title(source.title)
        created = today()
        warnings: List[str] = []

        if truncated:
            warnings.append(
                f"материал обрезан: частей больше потолка ({settings.max_chunks})"
            )

        if failed:
            warnings.append(f"частей без ответа модели: {failed}")

        if body_warning:
            warnings.append(body_warning)

        markdown = build_note(
            body=body,
            title=title,
            origin=source.origin,
            kind=source.kind,
            tags=settings.tags,
            created=created,
            parts=len(chunks),
            parts_used=len(partials),
            parts_failed=failed,
            truncated=truncated,
            model=self._model,
            seconds=seconds,
        )

        relative: Optional[str] = None
        absolute: Optional[Path] = None

        if write and self._writer is not None:
            note = self._writer.write(
                self._writer.note_path(title, created), markdown, title=title
            )
            relative = note.relative
            absolute = note.absolute

        return ConspectResult(
            title=title,
            origin=source.origin,
            kind=source.kind,
            markdown=markdown,
            parts_total=len(chunks),
            parts_used=len(partials),
            parts_failed=failed,
            truncated=truncated,
            seconds=seconds,
            model=self._model,
            relative_path=relative,
            absolute_path=absolute,
            warnings=warnings,
        )

    # ── Проходы ─────────────────────────────────────────────────────

    def _map(
        self, chunks: Sequence[str], source: SourceText, settings: ConspectSettings
    ) -> tuple[List[str], int, str]:
        """Первый проход: заметки по частям. Возвращает (заметки, сбои, причина)."""
        partials: List[str] = []
        failed = 0
        first_error = ""
        total = len(chunks)

        for index, chunk in enumerate(chunks, start=1):
            if self._progress is not None:
                self._progress(index, total)

            try:
                answer = self._ai.generate(
                    part_prompt(index, total, chunk),
                    SYSTEM_PROMPT,
                    settings.temperature,
                    max_tokens=settings.max_tokens_per_chunk,
                )
            except Exception as ex:  # noqa: BLE001 — сбой части не отменяет конспект
                failed += 1
                first_error = first_error or str(ex)
                log_error("Conspect", f"часть {index}/{total}: {ex}")
                continue

            cleaned = clean_model_text(answer)

            if cleaned.strip().lower() in _NO_DATA:
                continue

            if _looks_like_error(cleaned):
                failed += 1
                first_error = first_error or cleaned.strip()[:200]
                log_error(
                    "Conspect",
                    f"часть {index}/{total}: модель вернула сообщение об ошибке",
                )
                continue

            partials.append(cleaned)

        return partials, failed, first_error

    def _reduce(
        self,
        partials: Sequence[str],
        source: SourceText,
        settings: ConspectSettings,
    ) -> tuple[str, str]:
        """Второй проход: сводка. Возвращает (текст конспекта, предупреждение)."""
        if len(partials) == 1:
            # Одна часть — сводка была бы пересказом пересказа: экономит вызов.
            return partials[0], ""

        try:
            answer = self._ai.generate(
                summary_prompt(partials, source.title or "материал"),
                SYSTEM_PROMPT,
                settings.temperature,
                max_tokens=settings.max_tokens_summary,
            )
        except Exception as ex:  # noqa: BLE001 — теряем сводку, не работу
            log_error("Conspect", f"сводка частей: {ex}")
            return self._fallback_body(partials), (
                "сводка не удалась: в заметке заметки по частям"
            )

        cleaned = clean_model_text(answer)

        if _looks_like_error(cleaned):
            log_error("Conspect", "сводка частей: модель вернула сообщение об ошибке")
            return self._fallback_body(partials), (
                "сводка не удалась: в заметке заметки по частям"
            )

        return cleaned, ""

    def _fallback_body(self, partials: Sequence[str]) -> str:
        """Заметки частей как есть — честная альтернатива потерянному конспекту."""
        blocks = [
            f"## Заметки по части {number}\n\n{text}"
            for number, text in enumerate(partials, start=1)
        ]

        return "\n\n".join(blocks)


__all__ = ["ConspectResult", "Summarizer", "plan_parts"]
