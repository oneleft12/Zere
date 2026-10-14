"""Контракт конспекта: промпты и сборка заметки.

Контракт — это то, что пользователь «шлифует» под себя: разделы, порядок,
жёсткость требований. Он вынесен отдельно от логики, чтобы правка формата
не трогала чанкование, сеть и запись в хранилище.

Два промпта, потому что материал обрабатывается в два прохода (map-reduce):

1. **по части** — сжатые заметки по фрагменту, без вступлений и выводов;
2. **по сводке** — те же разделы, но уже по всему материалу: только факты,
   которые есть в заметках частей.

Оба прохода помещаются в окно модели (`num_ctx = 2048`): часть — до 2400
символов, ответ — до 400 токенов; сводка — это уже сжатые заметки частей.

Заметка собирается здесь же и всегда содержит frontmatter: заголовок,
источник, дату, теги и число частей. Так Obsidian видит конспект как обычную
заметку (поиск, теги, ссылки), а не как безымянный текстовый файл.
"""

from __future__ import annotations

import re
from datetime import date as _date
from typing import Sequence

#: Системная роль. Русский язык обязателен: правило проекта (docs/AI_PROVIDERS.md)
#: добавляется к любой личности, но здесь промпт свой и отдельный.
SYSTEM_PROMPT = (
    "Ты — конспектировщик ZERE. Ты работаешь только с текстом, который дал "
    "пользователь: ничего не выдумываешь, не добавляешь знаний от себя и не "
    "пересказываешь то, чего в тексте нет. Отвечаешь только на русском языке, "
    "кратко и по делу, в формате Markdown."
)

#: Разделы итогового конспекта. Порядок и названия — часть контракта.
SECTIONS: tuple[str, ...] = (
    "Суть",
    "Ключевые тезисы",
    "Термины",
    "Action items",
    "Открытые вопросы",
)

#: Разделы, которые в заметке не нужны (модель их иногда дописывает).
_FORBIDDEN_TAIL = (
    "Надеюсь, это поможет",
    "Если нужно",
    "Дайте знать",
)

#: Символы, которых в имени файла быть не должно. Не выбрасываем, а заменяем
#: дефисом: «плохое<>имя» читается как «плохое-имя», а «плохоеимя» теряет смысл.
_SLUG_DROP = re.compile(r"[^\w\s.-]", flags=re.UNICODE)
_SLUG_SPACES = re.compile(r"[\s_-]+")
_SLUG_DOTS = re.compile(r"\.{2,}")


def part_prompt(index: int, total: int, chunk: str) -> str:
    """Промпт первого прохода: заметки по одной части материала."""
    return (
        f"Ниже {index}-я часть из {total} одного материала.\n"
        "Сделай по ней сжатые заметки для последующей сводки.\n\n"
        "Правила:\n"
        "— только факты из этой части, своими словами;\n"
        "— без вступлений («в этой части…»), без выводов и без предложений помощи;\n"
        "— тезисы — маркированным списком, каждый пункт — одна мысль;\n"
        "— отдельно перечисли термины, которые в части определяются, и дела, "
        "которые из неё следуют (кому и что сделать), если они есть;\n"
        "— если в части нет ничего содержательного, ответь ровно «нет данных».\n\n"
        f"Часть {index}:\n{chunk}"
    )


def summary_prompt(partials: Sequence[str], source_title: str) -> str:
    """Промпт второго прохода: сводка заметок в один конспект."""
    joined = "\n\n".join(
        f"### Часть {number}\n{text}" for number, text in enumerate(partials, start=1)
    )

    return (
        f"Ниже заметки по частям материала «{source_title}».\n"
        "Собери из них один конспект.\n\n"
        "Формат ответа — Markdown, ровно такие разделы и в таком порядке:\n"
        f"## {SECTIONS[0]}\n(2–4 предложения: о чём материал и что в нём главное)\n"
        f"## {SECTIONS[1]}\n(список ключевых тезисов, 5–12 пунктов, по одному "
        "предложению каждый)\n"
        f"## {SECTIONS[2]}\n(термины и определения из материала; если их нет — "
        "напиши «нет»)\n"
        f"## {SECTIONS[3]}\n(конкретные дела с ответственным и сроком, если они "
        "названы; если дел нет — напиши «нет»)\n"
        f"## {SECTIONS[4]}\n(вопросы, которые материал оставил открытыми; если "
        "их нет — напиши «нет»)\n\n"
        "Правила: ничего не выдумывать; повторы между частями убрать; "
        "не писать вступлений, извинений и предложений помощи.\n\n"
        f"{joined}"
    )


def clean_model_text(text: str) -> str:
    """Убирает служебный «мусор» модели: блок ```-обёртку и прощальные фразы."""
    cleaned = (text or "").strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

    for tail in _FORBIDDEN_TAIL:
        position = cleaned.find(tail)
        if position > 0:
            cleaned = cleaned[:position].rstrip()

    return cleaned


def note_title(source_title: str) -> str:
    """Заголовок конспекта: узнаваемое имя заметки в хранилище."""
    name = " ".join((source_title or "").split()).strip(" —-–")

    if not name:
        return "Конспект"

    if name.lower().startswith("конспект"):
        return name

    return f"Конспект: {name}"


def slugify(value: str, *, limit: int = 80, fallback: str = "конспект") -> str:
    """Имя файла из заголовка: буквы (включая кириллицу), цифры, дефисы.

    Кириллицу не транслитерируем: Obsidian ищет и сортирует такие имена
    нормально, а «konspekt-lora» вместо «конспект-lora» только мешает.
    """
    text = " ".join((value or "").split())
    text = _SLUG_DROP.sub("-", text)
    text = _SLUG_SPACES.sub("-", text)
    text = _SLUG_DOTS.sub(".", text).strip(" .-")

    if len(text) > limit:
        text = text[:limit].rstrip(" .-")

    # Точка в конце имени на Windows невозможна, а пустое имя — не файл.
    return text or fallback


def yaml_scalar(value: str) -> str:
    """Значение для frontmatter: кавычки только когда без них сломается YAML."""
    text = " ".join(str(value or "").split())

    if text == "":
        return '""'

    unsafe = (
        text[0] in "-?:,[]{}#&*!|>'\"%@`"
        or ": " in text
        or " #" in text
        or text.lower() in ("true", "false", "null", "yes", "no", "on", "off")
    )
    needs_quotes = unsafe or text != str(value)

    if not needs_quotes:
        return text

    escaped = text.replace("\\", "\\\\").replace('"', '\\"')

    return f'"{escaped}"'


def frontmatter(
    *,
    title: str,
    origin: str,
    kind: str,
    tags: Sequence[str],
    created: str,
    parts: int,
) -> str:
    """YAML-шапка заметки: её читает Obsidian (теги, поиск) и конспектор."""
    lines = [
        "---",
        f"title: {yaml_scalar(title)}",
        f"source: {yaml_scalar(origin)}",
        f"sourceType: {yaml_scalar(kind)}",
        f"created: {yaml_scalar(created)}",
        f"parts: {max(0, int(parts))}",
        "tags:",
    ]
    lines.extend(f"  - {yaml_scalar(tag)}" for tag in tags)
    lines.append("---")

    return "\n".join(lines)


def build_note(
    *,
    body: str,
    title: str,
    origin: str,
    kind: str,
    tags: Sequence[str],
    created: str,
    parts: int,
    parts_used: int,
    parts_failed: int = 0,
    truncated: bool = False,
    model: str = "",
    seconds: float = 0.0,
) -> str:
    """Собирает заметку конспекта: frontmatter + заголовок + текст + сноска."""
    blocks: list[str] = [
        frontmatter(
            title=title, origin=origin, kind=kind, tags=tags, created=created, parts=parts
        ),
        "",
        f"# {title}",
        "",
    ]

    if origin:
        label = {"url": "Ссылка", "file": "Файл", "text": "Источник"}.get(kind, "Источник")
        blocks.append(f"> {label}: {origin}")
        blocks.append("")

    blocks.append(clean_model_text(body) or "_(модель не вернула текст)_")

    notes: list[str] = [f"Частей материала: {parts_used} из {parts}"]

    if truncated:
        notes.append("материал был обрезан по потолку частей — конспект покрывает не всё")

    if parts_failed:
        notes.append(f"частей без ответа модели: {parts_failed}")

    if model:
        notes.append(f"модель: {model}")

    if seconds > 0:
        notes.append(f"время: {seconds:.0f} с")

    blocks.extend(["", "---", "_Конспект ZERE · " + "; ".join(notes) + "_", ""])

    return "\n".join(blocks).rstrip() + "\n"


def today() -> str:
    """Дата конспекта в виде YYYY-MM-DD (локальная: заметка — для человека)."""
    return _date.today().isoformat()


__all__ = [
    "SECTIONS",
    "SYSTEM_PROMPT",
    "build_note",
    "clean_model_text",
    "frontmatter",
    "note_title",
    "part_prompt",
    "slugify",
    "summary_prompt",
    "today",
    "yaml_scalar",
]
