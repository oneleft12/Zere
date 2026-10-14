"""Запись конспекта в хранилище Obsidian: безопасный путь, атомарная запись.

Почему напрямую в файлы, а не через MCP-плагин заметок (`seekstone`):

1. **Сторонний процесс не нужен в критическом пути.** Конспект — встроенная
   функция ZERE, а MCP-сервер требует Node.js и живёт только внутри сессии;
   его сбой превратил бы готовый конспект в потерянный;
2. **меньше прав — меньше риска.** `seekstone` запускается с правами
   пользователя и видит всё хранилище; здесь ZERE пишет сама, только в папку
   конспектов и только теми именами, которые проверила (docs/CONSPECT.md, §7).

Поиск и чтение заметок остаются за MCP-плагином: он индексирует хранилище
и отвечает на «заметки найди …». Дублировать это здесь незачем.

Заметка не перезаписывается: если файл с таким именем уже есть, имя получает
суффикс «-2», «-3» — старый конспект пользователя дороже нового.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from zere.core.conspect.contract import slugify
from zere.core.conspect.errors import VAULT_NOT_CONFIGURED, WRITE_FAILED, ConspectError

#: Символы, недопустимые в имени файла Windows.
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')

#: Зарезервированные имена Windows (CON, NUL, COM1…).
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)

#: Потолок длины относительного пути: запас к лимиту Windows в 260 символов.
MAX_PATH_CHARS = 180


@dataclass
class WrittenNote:
    """Записанная заметка: что показать пользователю и что вернуть вызывающему."""

    relative: str
    absolute: Path
    title: str

    @property
    def name(self) -> str:
        return Path(self.relative).name


def _clean_part(part: str) -> str:
    """Имя одного сегмента пути: без хвостовых точек/пробелов и запрещённых знаков."""
    cleaned = re.sub(r"-{2,}", "-", _ILLEGAL.sub("-", part)).strip().rstrip(". ")

    if cleaned.lower() in _RESERVED:
        cleaned = f"{cleaned}-"

    return cleaned


def _frontmatter_title(path: Path) -> str:
    """Заголовок заметки из её frontmatter — для списка конспектов.

    В имени файла заголовок урезан и без пробелов (`Конспект-Лекция.md`), а
    человеку в ответе нужно «Конспект: Лекция». Читаем только начало файла и
    только первое поле `title`: полноценный YAML-разбор здесь не нужен, а
    чужая заметка (созданная не конспектором) просто даст пустую строку.
    """
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        return ""

    lines = head.splitlines()

    # Заметка без frontmatter (создана не конспектором) — берём имя файла.
    if not lines or lines[0].strip() != "---":
        return ""

    for line in lines[1:]:
        if line.strip() == "---":
            break

        if line.startswith("title:"):
            value = line[len("title:"):].strip().strip('"').strip("'")

            return " ".join(value.split())

    return ""


def safe_relative_path(relative: str) -> Path:
    """Проверяет относительный путь заметки внутри хранилища.

    Отклоняем: пустой путь, абсолютные и UNC-пути, «..», запрещённые знаки,
    слишком длинный путь. Это защита не от злого умысла модели, а от
    случайного «../» в имени источника: писатель не должен уметь выйти за
    папку конспектов.
    """
    raw = (relative or "").strip().replace("\\", "/")

    if not raw:
        raise ConspectError(WRITE_FAILED, "Пустой путь заметки.")

    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or raw.startswith("//"):
        raise ConspectError(WRITE_FAILED, f"Абсолютный путь недопустим: {relative}")

    parts: List[str] = []

    for chunk in raw.split("/"):
        if not chunk or chunk in (".", ".."):
            # «..» отбрасывать нельзя молча: это уже попытка выйти наружу.
            if chunk == "..":
                raise ConspectError(WRITE_FAILED, f"Путь выходит за хранилище: {relative}")
            continue

        parts.append(_clean_part(chunk))

    if not parts:
        raise ConspectError(WRITE_FAILED, f"Путь заметки пуст: {relative}")

    joined = "/".join(parts)

    if len(joined) > MAX_PATH_CHARS:
        raise ConspectError(WRITE_FAILED, f"Слишком длинный путь заметки: {joined}")

    return Path(*parts)


class VaultWriter:
    """Пишет заметки в хранилище Obsidian и перечисляет уже сохранённые."""

    def __init__(
        self,
        root: Path | str,
        *,
        folder: str = "Конспекты",
        subfolder_by_month: bool = True,
        write_paths: Sequence[str] = (),
    ) -> None:
        self._root = Path(root).expanduser()
        self._folder = (folder or "Конспекты").strip().strip("/\\") or "Конспекты"
        self._subfolder_by_month = subfolder_by_month
        #: Разрешённые подпапки (по мотивам SEEKSTONE_WRITE_PATHS): пусто — только папка конспектов.
        self._write_paths = tuple(item.strip().strip("/\\") for item in write_paths if item)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def resolved_root(self) -> Path:
        """Хранилище с раскрытыми путями.

        Нужно на Windows: `.resolve()` разворачивает короткие имена 8.3
        («PROFES~1»), и сравнение пути заметки с неразвёрнутым корнем
        (`relative_to`) падало бы с ValueError.
        """
        try:
            return self._root.resolve()
        except OSError:  # pragma: no cover — недоступный путь
            return self._root

    @property
    def folder(self) -> str:
        return self._folder

    def check(self) -> None:
        """Проверяет хранилище до долгой работы модели: лучше отказать сразу."""
        if not str(self._root).strip() or str(self._root) == ".":
            raise ConspectError(
                VAULT_NOT_CONFIGURED,
                "Не задано хранилище Obsidian. Укажите путь в config/conspect.json "
                "(ключ vault) или в config/mcp.json (env SEEKSTONE_VAULT).",
            )

        if not self._root.is_dir():
            raise ConspectError(
                VAULT_NOT_CONFIGURED,
                f"Хранилище Obsidian не найдено: {self._root}. Проверьте путь в "
                "config/conspect.json (ключ vault).",
            )

        allowed = self._write_paths or (self._folder,)

        try:
            self._target_dir(allowed[0], None).mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            raise ConspectError(
                WRITE_FAILED, f"Папка конспектов недоступна: {ex}"
            ) from ex

    def note_path(self, title: str, created: str) -> Path:
        """Относительный путь заметки: папка конспектов [+ YYYY-MM] / slug.md."""
        name = f"{slugify(title)}.md"

        if not self._subfolder_by_month:
            return safe_relative_path(f"{self._folder}/{name}")

        month = (created or "")[:7]

        if not re.match(r"^\d{4}-\d{2}$", month):
            month = datetime.now().strftime("%Y-%m")

        return safe_relative_path(f"{self._folder}/{month}/{name}")

    def write(self, relative: Path | str, content: str, *, title: str = "") -> WrittenNote:
        """Пишет заметку, не перезаписывая существующую.

        Имя файла — из заголовка, но при совпадении добавляется «-2», «-3»:
        конспект пользователя за прошлый месяц не должен исчезнуть из-за
        нового материала с тем же названием.
        """
        self.check()

        relative_path = (
            relative if isinstance(relative, Path) else safe_relative_path(str(relative))
        )
        allowed = self._write_paths or (self._folder,)

        # Путь обязан начинаться с разрешённой подпапки: писатель не должен
        # уметь положить заметку в корень хранилища или в чужую папку.
        head = relative_path.parts[0] if relative_path.parts else ""

        if head not in allowed:
            raise ConspectError(
                WRITE_FAILED,
                f"Запись разрешена только в {', '.join(allowed)} (получено «{head}»).",
            )

        target = self._atomic_write(relative_path, content)

        return WrittenNote(
            relative=target.relative_to(self.resolved_root).as_posix(),
            absolute=target,
            title=title,
        )

    def list_notes(self, *, limit: int = 20) -> List[WrittenNote]:
        """Последние конспекты (по времени изменения) — для команды «конспекты»."""
        if not self._root.is_dir():
            return []

        base = self._root / self._folder

        if not base.is_dir():
            return []

        files = [path for path in base.rglob("*.md") if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)

        return [
            WrittenNote(
                relative=path.resolve().relative_to(self.resolved_root).as_posix(),
                absolute=path,
                title=_frontmatter_title(path) or path.stem,
            )
            for path in files[: max(0, limit)]
        ]

    # ── Внутреннее ──────────────────────────────────────────────────

    def _target_dir(self, head: str, month: Optional[str]) -> Path:
        parts = [head]

        if month and self._subfolder_by_month:
            parts.append(month)

        return self._root.joinpath(*parts)

    def _resolve_inside(self, relative: Path) -> Path:
        """Итоговый путь и проверка, что он внутри хранилища."""
        root = self.resolved_root
        candidate = (root / relative).resolve()

        if candidate != root and root not in candidate.parents:
            raise ConspectError(
                WRITE_FAILED, f"Путь заметки вне хранилища: {relative.as_posix()}"
            )

        return candidate

    def _unique_target(self, relative: Path) -> Path:
        """Свободное имя: «note.md» → «note-2.md» → «note-3.md»…"""
        candidate = self._resolve_inside(relative)

        if not candidate.exists():
            return candidate

        stem, suffix, parent = candidate.stem, candidate.suffix, candidate.parent

        for number in range(2, 100):
            alternative = parent / f"{stem}-{number}{suffix}"
            if not alternative.exists():
                return alternative

        stamp = datetime.now().strftime("%H%M%S")

        return parent / f"{stem}-{stamp}{suffix}"

    def _atomic_write(self, relative: Path, content: str) -> Path:
        """Пишет заметку через временный файл: обрыв не оставит половину текста."""
        target = self._unique_target(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.zere-tmp")

        try:
            temporary.write_text(content, encoding="utf-8", newline="\n")
            os.replace(temporary, target)
        except OSError as ex:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:  # pragma: no cover — уборка не критична
                pass

            raise ConspectError(WRITE_FAILED, f"Не удалось записать заметку: {ex}") from ex

        return target


__all__ = ["MAX_PATH_CHARS", "VaultWriter", "WrittenNote", "safe_relative_path"]
