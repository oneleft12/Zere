"""Операции с файлами на рабочем столе (порт FileManager.cs).

Папки ищутся шире рабочего стола: по стандартным папкам, профилю и локальным
дискам (`FolderSearchService`). Создание и удаление по-прежнему ограничены
рабочим столом — расширять запись без подтверждения нельзя.
"""

from __future__ import annotations

from pathlib import Path

from zere.tools.files.folder_opener import FolderOpener
from zere.tools.files.folder_search import (
    FolderHit,
    FolderSearchResult,
    FolderSearchService,
    best_match,
)

_ORDINALS = {
    "первую": 0,
    "первый": 0,
    "первая": 0,
    "вторую": 1,
    "второй": 1,
    "вторая": 1,
    "третью": 2,
    "третий": 2,
    "третья": 2,
    "четвёртую": 3,
    "четвертую": 3,
    "четвёртый": 3,
    "четвертый": 3,
}


class FileManager:
    """Создание/поиск/удаление файлов и папок на рабочем столе."""

    def __init__(
        self,
        folders: FolderSearchService | None = None,
        opener: FolderOpener | None = None,
    ) -> None:
        one_drive_desktop = Path.home() / "OneDrive" / "Desktop"

        if one_drive_desktop.is_dir():
            self._desktop = one_drive_desktop
        else:
            # Environment.SpecialFolder.DesktopDirectory
            self._desktop = Path.home() / "Desktop"

        self._last_file: Path | None = None
        self._folders = folders or FolderSearchService()
        self._opener = opener or FolderOpener()
        self._last_folder: Path | None = None
        self._last_candidates: list[FolderHit] = []

    @property
    def last_created_name(self) -> str | None:
        """Имя последнего созданного файла в этой сессии (для «удали его»)."""
        return self._last_file.name if self._last_file is not None else None

    def _resolve_path(self, name: str) -> Path | None:
        """Резолвит имя из реплики в путь внутри рабочего стола.

        Возвращает None, если путь выходит за пределы рабочего стола
        (абсолютный путь, "..", пустое имя) — защита от path traversal.
        """
        if not name or not name.strip():
            return None

        # Только относительные имена: абсолютные и drive-relative пути запрещены.
        normalized = name.replace("\\", "/")
        if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
            return None

        parts = [p for p in normalized.split("/") if p]
        if any(p in ("..", ".") for p in parts):
            return None

        try:
            full = (self._desktop / name).resolve()
            desktop = self._desktop.resolve()
        except OSError:
            return None

        # Итоговый путь обязан быть внутри рабочего стола.
        if desktop not in full.parents:
            return None

        return full

    def create_folder(self, name: str) -> str:
        path = self._resolve_path(name)

        if path is None:
            return f"Недопустимый путь «{name}»: можно создавать только внутри рабочего стола."

        if path.is_dir():
            return f'Папка "{name}" уже существует.'

        path.mkdir(parents=True)
        # Индекс папок не должен отдавать старую картину: «создай папку X»
        # и сразу «найди папку X» обязаны работать без ожидания TTL.
        self._folders.refresh()

        return f'Папка "{name}" создана.'

    def create_file(self, name: str) -> str:
        path = self._resolve_path(name)

        if path is None:
            return f"Недопустимый путь «{name}»: можно создавать только внутри рабочего стола."

        if path.is_file():
            return f'Файл "{name}" уже существует.'

        # «создай файл папка/note.txt»: промежуточные папки создаём сами —
        # иначе write_text падал FileNotFoundError и команда не работала.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        self._last_file = path
        self._folders.refresh()

        return f'Файл "{name}" создан.'

    def find_file(self, query: str) -> str:
        query_lower = query.lower()

        matches: list[Path] = []

        for file in self._desktop.rglob("*"):
            if not file.is_file():
                continue

            file_name = file.name
            no_ext = file.stem

            if query_lower in file_name.lower() or query_lower in no_ext.lower():
                matches.append(file)

            if len(matches) == 10:  # Take(10)
                break

        if not matches:
            return f'Файл "{query}" не найден.'

        return "Найденные файлы:\n\n" + "\n\n".join(
            f"• {file.name}\n{file}" for file in matches
        )

    # ── Папки в системе ──────────────────────────────────────────

    @property
    def last_found_folder(self) -> Path | None:
        """Папка, которую открывали последней (для «открой её»)."""
        return self._last_folder

    def search_folders(
        self,
        query: str,
        *,
        limit: int = 20,
        refresh: bool = False,
    ) -> FolderSearchResult:
        """Поиск папок с запоминанием кандидатов для «открой первую/2»."""
        result = self._folders.search(query, limit=limit, refresh=refresh)
        if query.strip():
            self._last_candidates = list(result.hits)
        return result

    def can_open_folder(self, query: str) -> bool:
        """Похоже ли имя на папку (алиас/путь), не запуская обход диска."""
        return self._folders.is_known_folder(query)

    def find_folders(self, query: str) -> str:
        """Текстовый ответ чата: список найденных папок с путями."""
        result = self.search_folders(query)

        if not result.hits:
            answer = f'Папка "{query}" не найдена.'
            if result.truncated:
                answer += " Поиск ограничен по времени/глубине — уточните запрос."
            return answer

        lines = [f"• {hit.name}\n{hit.path}" for hit in result.hits]
        answer = "Найденные папки:\n\n" + "\n\n".join(lines)

        if result.total > len(result.hits):
            answer += f"\n\nПоказаны первые {len(result.hits)} из {result.total}."

        if result.truncated:
            answer += (
                "\n\nПоиск ограничен по времени/глубине — уточните запрос, "
                "если нужной папки нет."
            )

        return answer

    def open_folder(self, query: str) -> str:
        """Открывает папку по имени, пути, номеру из прошлой выдачи или «её»."""
        text = query.strip()

        if not text:
            if self._last_folder is not None:
                return self._open_path(self._last_folder)

            if len(self._last_candidates) > 1:
                lines = [
                    f"{index}. {hit.name} — {hit.path}"
                    for index, hit in enumerate(self._last_candidates, 1)
                ]
                return (
                    "В прошлой выдаче несколько папок:\n\n"
                    + "\n".join(lines)
                    + "\n\nУточните: «открой папку 1»."
                )

            return self._open_path(self._single_candidate() or self._desktop)

        ordinal_text = text.casefold()
        if ordinal_text.startswith("номер "):
            ordinal_text = ordinal_text[len("номер "):].strip()

        ordinal = _ORDINALS.get(ordinal_text)
        if ordinal is None and ordinal_text.isdigit():
            ordinal = int(ordinal_text) - 1

        if ordinal is not None:
            return self._open_candidate(ordinal)

        result = self.search_folders(text, limit=5)
        self._last_candidates = list(result.hits)

        if not result.hits:
            return f'Папка "{text}" не найдена.'

        target = best_match(result.hits)
        if target is not None:
            return self._open_path(target)

        lines = [f"{index}. {hit.name} — {hit.path}" for index, hit in enumerate(result.hits, 1)]
        return (
            "Нашёл несколько папок:\n\n"
            + "\n".join(lines)
            + "\n\nУточните: «открой папку 1» (или назовите точнее)."
        )

    def open_path(self, path: str | Path) -> tuple[bool, str]:
        """Открывает конкретный путь (панель уже проверила, что это папка)."""
        target = Path(path)
        opened, message = self._opener.open(target)
        if opened:
            self._last_folder = target
        return opened, message

    def _open_candidate(self, index: int) -> str:
        if not self._last_candidates:
            return "Сначала найдите папку: «найди папку …», потом «открой папку 1»."

        if index < 0 or index >= len(self._last_candidates):
            return (
                f"В прошлой выдаче {len(self._last_candidates)} папок — "
                f"номера от 1 до {len(self._last_candidates)}."
            )

        return self._open_path(self._last_candidates[index].path)

    def _single_candidate(self) -> Path | None:
        if len(self._last_candidates) == 1:
            return self._last_candidates[0].path
        return None

    def _open_path(self, path: Path) -> str:
        opened, message = self._opener.open(path)
        if opened:
            self._last_folder = path
        return message

    def exists(self, name: str) -> bool:
        """Существует ли файл с таким именем внутри рабочего стола."""
        path = self._resolve_path(name)
        return path is not None and path.is_file()

    def delete_file(self, name: str) -> bool:
        name_lower = name.lower()

        for file in self._desktop.rglob("*"):
            if file.is_file() and file.name.lower() == name_lower:
                file.unlink()
                return True

        return False
