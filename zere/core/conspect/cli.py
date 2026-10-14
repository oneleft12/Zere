"""CLI конспектора: `python -m zere.core.conspect <источник> [ключи]`.

Зачем отдельная команда, если есть чат: **длинные материалы**. В чате конспект
ограничен `interactiveMaxChars` (по умолчанию 20 000 символов), потому что
панель ждёт ответ синхронно: часовая лекция — это десятки минут работы модели
на CPU. CLI снимает это ограничение: он печатает прогресс по частям, его можно
оставить в фоне, а результат — та же заметка в хранилище.

Примеры:

    python -m zere.core.conspect lecture.md
    python -m zere.core.conspect https://example.com/article --tags нейросети,обучение
    python -m zere.core.conspect book.pdf --folder Книги --max-chunks 60
    python -m zere.core.conspect --list
    python -m zere.core.conspect lecture.md --dry-run          # показать, не писать

Коды возврата: 0 — конспект сделан, 1 — отказ с причиной.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Optional, Sequence

from zere.ai.ai_service import AiService
from zere.core.conspect.ai_bridge import model_label, preflight
from zere.core.conspect.chunking import chunk_text
from zere.core.conspect.config import (
    ConspectSettings,
    load_conspect_settings,
    resolve_vault,
)
from zere.core.conspect.errors import ConspectError
from zere.core.conspect.summarizer import Summarizer
from zere.core.conspect.text import read_source
from zere.core.conspect.vault import VaultWriter

_BAD_ARGS = "CONSPECT_BAD_ARGS"

#: Ключи, которым нужно значение.
_VALUE_KEYS = ("--folder", "--tags", "--max-chunks")


def _parse_args(argv: Sequence[str]) -> dict[str, Any]:
    """Простой разбор аргументов: ключей мало, и ошибки получаются понятнее."""
    options: dict[str, Any] = {
        "source": "",
        "folder": "",
        "tags": [],
        "max_chunks": None,
        "dry_run": False,
        "as_json": False,
        "list": False,
        "allow_private": False,
        "help": False,
    }
    positional: list[str] = []
    items = list(argv)
    index = 0

    while index < len(items):
        item = items[index]
        value = items[index + 1] if index + 1 < len(items) else None

        if item in ("--help", "-h"):
            options["help"] = True
        elif item in _VALUE_KEYS:
            if value is None:
                raise ConspectError(_BAD_ARGS, f"Ключ {item} требует значения.")

            index += 1

            if item == "--folder":
                options["folder"] = value
            elif item == "--tags":
                options["tags"] = [
                    tag.strip()
                    for tag in value.replace(";", ",").split(",")
                    if tag.strip()
                ]
            else:
                try:
                    options["max_chunks"] = int(value)
                except ValueError as ex:
                    raise ConspectError(
                        _BAD_ARGS, "Значение --max-chunks должно быть числом."
                    ) from ex
        elif item == "--dry-run":
            options["dry_run"] = True
        elif item == "--json":
            options["as_json"] = True
        elif item == "--list":
            options["list"] = True
        elif item == "--allow-private":
            options["allow_private"] = True
        elif item.startswith("-"):
            raise ConspectError(_BAD_ARGS, f"Неизвестный ключ: {item}")
        else:
            positional.append(item)

        index += 1

    options["source"] = " ".join(positional).strip()

    return options


def _build_writer(settings: ConspectSettings) -> VaultWriter:
    vault = resolve_vault(settings)

    return VaultWriter(
        vault or ".",
        folder=settings.resolved_folder,
        subfolder_by_month=settings.subfolder_by_month,
        write_paths=settings.write_paths,
    )


def _planned(settings: ConspectSettings, text: str) -> tuple[int, bool]:
    """Сколько частей будет в материале (сообщение до запуска модели)."""
    chunks = chunk_text(text, settings.chunk_chars, settings.chunk_overlap)

    return len(chunks), len(chunks) > settings.max_chunks


def _list_notes(writer: VaultWriter) -> int:
    notes = writer.list_notes(limit=20)

    if not notes:
        print(f"Конспектов нет: {writer.root / writer.folder}")

        return 0

    print(f"Конспекты ({writer.root / writer.folder}):")

    for note in notes:
        stamp = datetime.fromtimestamp(note.absolute.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  • {note.title} — {note.relative}  ({stamp})")

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        options = _parse_args(sys.argv[1:] if argv is None else argv)
    except ConspectError as ex:
        print(f"[Конспектор] {ex.message}")

        return 1

    if options["help"]:
        print(__doc__)

        return 0

    if not options["source"] and not options["list"]:
        print(__doc__)

        return 1

    settings = load_conspect_settings()

    if options["folder"]:
        settings.folder = options["folder"]

    if options["tags"]:
        settings.tags = tuple(options["tags"])

    if options["max_chunks"] is not None:
        settings.max_chunks = max(1, int(options["max_chunks"]))

    writer = _build_writer(settings)

    if options["list"]:
        return _list_notes(writer)

    if not settings.enabled:
        print("[Конспектор] Выключен: enabled=false в config/conspect.json")

        return 1

    service = AiService()

    def progress(index: int, total: int) -> None:
        print(f"[{index}/{total}] конспектирую часть…", flush=True)

    try:
        summarizer = Summarizer(
            service,
            settings,
            writer=writer,
            preflight=lambda: preflight(service),
            progress=progress,
            model=model_label(service),
        )
        source = read_source(
            options["source"],
            timeout=settings.timeout_seconds,
            max_chars=settings.max_source_chars,
            max_download_chars=settings.max_download_chars,
            allow_private=bool(options["allow_private"]),
        )
        planned, truncated = _planned(settings, source.text)

        print(
            f"Источник: {source.kind} · {source.origin}\n"
            f"Текст: {source.chars} символов · частей: {planned}"
            + (" (материал будет обрезан по потолку частей)" if truncated else "")
        )

        result = summarizer.conspect(source, write=not options["dry_run"])
    except ConspectError as ex:
        print(f"[Конспектор] {ex.message}")

        return 1
    except KeyboardInterrupt:  # pragma: no cover — ручное прерывание
        print("\n[Конспектор] Прервано пользователем.")

        return 1
    finally:
        # Клиент ИИ закрывается в любом случае: и при отказе источника,
        # и при сбое модели, и после успешного конспекта.
        try:
            service.close()
        except Exception:  # noqa: BLE001 — закрытие клиента не критично
            pass

    if options["as_json"]:
        print(
            json.dumps(
                {
                    "title": result.title,
                    "origin": result.origin,
                    "kind": result.kind,
                    "partsTotal": result.parts_total,
                    "partsUsed": result.parts_used,
                    "partsFailed": result.parts_failed,
                    "truncated": result.truncated,
                    "seconds": round(result.seconds, 1),
                    "note": result.relative_path,
                    "warnings": result.warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif result.written:
        print(f"\nГотово. Конспект сохранён: {result.relative_path}")
        print(f"Заметка: {result.absolute_path}")
    else:
        print("\nСухой прогон — заметка не записана:\n")
        print(result.markdown)

    if result.warnings:
        print("Замечания: " + "; ".join(result.warnings))

    return 0


if __name__ == "__main__":  # pragma: no cover — точка входа CLI
    sys.exit(main())
