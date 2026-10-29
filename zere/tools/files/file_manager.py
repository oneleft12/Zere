"""Операции с файлами на рабочем столе (порт FileManager.cs)."""

from __future__ import annotations

from pathlib import Path


class FileManager:
    """Создание/поиск/удаление файлов и папок на рабочем столе."""

    def __init__(self) -> None:
        one_drive_desktop = Path.home() / "OneDrive" / "Desktop"

        if one_drive_desktop.is_dir():
            self._desktop = one_drive_desktop
        else:
            # Environment.SpecialFolder.DesktopDirectory
            self._desktop = Path.home() / "Desktop"

        self._last_file: Path | None = None

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
