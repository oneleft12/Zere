"""Обработчик конвейера: «законспектируй …» в чате и голосом.

Место в конвейере — сразу после файловых команд и до `AIHandler`: конспект
обязан обрабатываться кодом, а не «объясняться» моделью. Плагины MCP стоят
позже, поэтому команды заметок (`заметки найди …`) этим обработчиком не
перехватываются.

Что обработчик решает сам, а что отдаёт движку (`zere/core/conspect/`):

- **триггер и источник** — здесь: URL → страница, существующий путь → файл,
  длинный текст в сообщении → материал «как есть»;
- **потолок чата** — здесь: конвейер синхронный, панель ждёт ответ, поэтому
  материал больше `interactiveMaxChars` не берём в чат, а отправляем в CLI
  (`python -m zere.core.conspect …`), где прогресс виден и никто не ждёт;
- **чанкование, модель, запись заметки** — в движке.

Исключений наружу нет: любая ошибка (нет модели, нет хранилища, сеть)
превращается в короткий русский ответ — он же уходит в озвучку.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional

from zere.core.conspect.ai_bridge import model_label, preflight
from zere.core.conspect.config import (
    ConspectSettings,
    load_conspect_settings,
    resolve_vault,
)
from zere.core.conspect.errors import ConspectError
from zere.core.conspect.summarizer import Summarizer, plan_parts
from zere.core.conspect.text import SourceText, is_url, read_source
from zere.core.conspect.vault import VaultWriter
from zere.core.handlers.i_zere_handler import IZereHandler
from zere.core.logging.log_service import log_error

#: Слова-триггеры. Порядок важен: длинные разбираются раньше коротких.
_SOURCE_TRIGGERS: tuple[str, ...] = (
    "законспектируй",
    "законспектировать",
    "сделай конспект",
    "сделать конспект",
    "сделай выжимку",
    "сделай краткое содержание",
    "краткое содержание",
    "конспект",
)

#: Фразы, по которым показываем сохранённые конспекты.
_LIST_PHRASES = frozenset(
    {
        "конспекты",
        "мои конспекты",
        "список конспектов",
        "покажи конспекты",
        "какие есть конспекты",
        "конспекты список",
    }
)

#: Мусор между триггером и источником: «законспектируй, пожалуйста, файл …».
_FILLER = re.compile(
    r"^(?:[,:\-—]|\s|\bпожалуйста\b|\bпжлст\b|\bмне\b|\bэтот\b|\bэту\b|\bвот\b)+",
    re.IGNORECASE,
)

#: «конспект файла X», «конспект статьи X», «конспект из X» — предлоги и уточнения.
_SOURCE_HINTS = re.compile(
    r"^(?:файл|файла|файл\s+|статью|статьи|статья|статье|текст|текста|"
    r"видео|ролик|лекцию|лекции|книгу|книги|из|от|по|про|это|вот)\s+",
    re.IGNORECASE,
)

#: С какого размера остаток сообщения считается материалом, а не командой.
_MIN_INLINE_CHARS = 300

#: Сколько конспектов показываем в ответе на «конспекты».
_MAX_LIST = 10


class ConspectHandler(IZereHandler):
    """«Законспектируй <файл|ссылка|текст>» → заметка в хранилище Obsidian."""

    def __init__(
        self,
        ai: Any,
        settings: Optional[ConspectSettings] = None,
        *,
        writer: Optional[VaultWriter] = None,
        session: Optional[Any] = None,
    ) -> None:
        #: Объект с `generate(...)` — `AiService` (и `status()` для проверки).
        self._ai = ai
        self._settings = settings if settings is not None else load_conspect_settings()
        #: Явный писатель (тесты) или None — тогда хранилище ищется по настройкам.
        self._writer = writer
        self._session = session

    @property
    def settings(self) -> ConspectSettings:
        return self._settings

    @property
    def writer(self) -> VaultWriter:
        """Писатель заметок. Строится на каждый вызов: правки конфига видны сразу."""
        if self._writer is not None:
            return self._writer

        return VaultWriter(
            resolve_vault(self._settings) or ".",
            folder=self._settings.resolved_folder,
            subfolder_by_month=self._settings.subfolder_by_month,
            write_paths=self._settings.write_paths,
        )

    # ── Конвейер ────────────────────────────────────────────────────

    def can_handle(self, message: str) -> bool:
        if not self._settings.enabled:
            return False

        return self._source_from(message) is not None or self._is_list(message)

    def handle(self, message: str) -> Optional[str]:
        if not self._settings.enabled:
            return None

        if self._is_list(message):
            return self._list_answer()

        parsed = self._source_from(message)

        if parsed is None:
            return None

        return self._conspect(parsed)

    # ── Разбор фразы ────────────────────────────────────────────────

    @staticmethod
    def _is_list(message: str) -> bool:
        return " ".join((message or "").lower().split()) in _LIST_PHRASES

    def _source_from(self, message: str) -> Optional[str]:
        """Источник из фразы. `None` — это не команда конспекта.

        Обработчик обязан понимать, «его» это фраза или нет: конвейер
        спрашивает `can_handle` на каждом сообщении, и жадный разбор отобрал
        бы команды у `AIHandler`.
        """
        text = (message or "").strip()
        lower = text.lower()

        for trigger in _SOURCE_TRIGGERS:
            if not lower.startswith(trigger):
                continue

            rest = text[len(trigger):]

            # «конспекты», «конспектный» — не наш случай: за триггером должна
            # идти граница (пробел, двоеточие, запятая, дефис) или конец фразы.
            if rest[:1].isalnum() and trigger == "конспект":
                continue

            rest = _FILLER.sub("", rest)
            rest = _SOURCE_HINTS.sub("", rest, count=1)
            rest = _FILLER.sub("", rest)

            return rest.strip() or ""

        return None

    # ── Работа ──────────────────────────────────────────────────────

    def _conspect(self, value: str) -> str:
        settings = self._settings

        if not value:
            return self._usage()

        try:
            source = self._load_source(value)
        except ConspectError as ex:
            return ex.message

        if source is None:
            return self._hint_for(value)

        planned, _ = plan_parts(source.text, settings)

        if source.chars > settings.interactive_max_chars:
            return self._too_long(source, planned)

        summarizer = Summarizer(
            self._ai,
            settings,
            writer=self.writer,
            preflight=lambda: preflight(self._ai),
            model=model_label(self._ai),
        )

        try:
            result = summarizer.conspect(source)
        except ConspectError as ex:
            return ex.message
        except Exception as ex:  # noqa: BLE001 — конвейер не должен падать из-за конспекта
            log_error("ConspectHandler", f"{value[:120]}: {ex}")

            return f"Не удалось сделать конспект: {ex}"

        return self._answer(result)

    def _load_source(self, value: str) -> Optional[SourceText]:
        """Источник из значения: URL, файл или длинный текст в самом сообщении."""
        settings = self._settings

        if is_url(value):
            return read_source(
                value,
                timeout=settings.timeout_seconds,
                max_chars=settings.max_source_chars,
                max_download_chars=settings.max_download_chars,
                session=self._session,
            )

        candidate = Path(value.strip('"').strip("'")).expanduser()

        if candidate.exists():
            return read_source(str(candidate), max_chars=settings.max_source_chars)

        # Путь «выглядит как путь» (есть разделители или расширение) — но файла
        # нет: это ошибка пользователя, а не материал.
        if self._looks_like_path(value) and len(value) < _MIN_INLINE_CHARS:
            raise ConspectError(
                "CONSPECT_SOURCE_NOT_FOUND",
                f"Файл не найден: {candidate}. Укажите полный путь или ссылку.",
            )

        if len(value) >= _MIN_INLINE_CHARS:
            return self._inline_source(value)

        return None

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        text = (value or "").strip()

        if "\\" in text or "/" in text:
            return True

        return Path(text).suffix.lower() in (
            ".md",
            ".txt",
            ".pdf",
            ".markdown",
            ".html",
            ".htm",
            ".rst",
            ".csv",
            ".json",
        )

    @staticmethod
    def _inline_source(text: str) -> SourceText:
        """Материал прямо в сообщении: заголовок — первая непустая строка."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        first = lines[0] if lines else "Сообщение"
        title = first[:80] + ("…" if len(first) > 80 else "")

        return SourceText(text=text, title=title, origin="сообщение в чате", kind="text")

    def _too_long(self, source: SourceText, planned: int) -> str:
        settings = self._settings
        target = source.origin if source.kind != "text" else "<файл или ссылка>"

        return (
            f"Материал большой: {source.chars} символов (≈{planned} частей). "
            f"В чате конспектирую до {settings.interactive_max_chars} символов — "
            "иначе ответа ждать десятки минут. Запустите в консоли:\n"
            f'python -m zere.core.conspect "{target}" --max-chunks {settings.max_chunks}'
        )

    def _hint_for(self, value: str) -> str:
        """Значение не URL, не файл и не похоже на материал — учим формулировке."""
        short = value[:120] + ("…" if len(value) > 120 else "")

        return (
            f"Не понял, что конспектировать: «{short}».\n{self._usage()}"
        )

    def _usage(self) -> str:
        return (
            "Скажите: «законспектируй C:\\путь\\лекция.md», "
            "«законспектируй https://example.com/статья» или пришлите текст "
            f"целиком (от {_MIN_INLINE_CHARS} символов). "
            "Сохранённые конспекты — «конспекты». "
            "Длинные материалы — в консоли: python -m zere.core.conspect <источник>."
        )

    # ── Ответы ──────────────────────────────────────────────────────

    def _answer(self, result: Any) -> str:
        location = result.relative_path or "(не сохранено)"

        parts = (
            f"{result.parts_used} из {result.parts_total}"
            if result.parts_used != result.parts_total
            else str(result.parts_total)
        )
        text = (
            f"Готово. Конспект: {location}. "
            f"Частей материала: {parts}, время: {result.seconds:.0f} с."
        )

        if result.warnings:
            text += " Замечания: " + "; ".join(result.warnings) + "."

        return text

    def _list_answer(self) -> str:
        settings = self._settings

        try:
            writer = self.writer
            notes = writer.list_notes(limit=_MAX_LIST)
        except ConspectError as ex:
            return ex.message

        folder = f"{writer.root / writer.folder}"

        if not notes:
            return (
                f"Конспектов пока нет. Папка: {folder}. "
                "Скажите «законспектируй <файл или ссылка>»."
            )

        lines: List[str] = [f"Конспекты ({len(notes)}):"]

        for index, note in enumerate(notes, start=1):
            lines.append(f"{index}. {note.title} — {note.relative}")

        return "\n".join(lines)


__all__ = ["ConspectHandler"]
