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

    def create_folder(self, name: str) -> str:
        path = self._desktop / name

        if path.is_dir():
            return f'Папка "{name}" уже существует.'

        path.mkdir(parents=True)

        return f'Папка "{name}" создана.'

    def create_file(self, name: str) -> str:
        path = self._desktop / name

        if path.is_file():
            return f'Файл "{name}" уже существует.'

        path.write_text("", encoding="utf-8")

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

    def delete_file(self, name: str) -> bool:
        name_lower = name.lower()

        for file in self._desktop.rglob("*"):
            if file.is_file() and file.name.lower() == name_lower:
                file.unlink()
                return True

        return False
