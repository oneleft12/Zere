"""Тесты FileManager: работа на рабочем столе и защита от path traversal.

Рабочий стол подменяется временным каталогом (Path.home), поэтому тесты
ничего не создают в реальном профиле пользователя. Проверяется именно то,
что нельзя проверить «на глаз»: абсолютные пути, `..`, диски Windows и
итоговая проверка «путь внутри рабочего стола».
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zere.tools.files.file_manager import FileManager


@pytest.fixture
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Пустой рабочий стол внутри tmp; OneDrive-ветки нет."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "zere.tools.files.folder_search._windows_known_folder", lambda guid: None
    )
    folder = tmp_path / "Desktop"
    folder.mkdir()
    return folder


@pytest.fixture
def manager(desktop: Path) -> FileManager:
    return FileManager()


def test_uses_desktop_folder(manager: FileManager, desktop: Path) -> None:
    assert manager.create_folder("папка") == 'Папка "папка" создана.'
    assert (desktop / "папка").is_dir()


def test_one_drive_desktop_wins_when_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    one_drive = tmp_path / "OneDrive" / "Desktop"
    one_drive.mkdir(parents=True)

    manager = FileManager()
    manager.create_file("note.txt")

    assert (one_drive / "note.txt").is_file()
    assert not (tmp_path / "Desktop" / "note.txt").exists()


def test_existing_folder_is_reported(manager: FileManager) -> None:
    manager.create_folder("dup")
    assert manager.create_folder("dup") == 'Папка "dup" уже существует.'


def test_create_file_and_remember_last(manager: FileManager, desktop: Path) -> None:
    assert manager.create_file("note.txt") == 'Файл "note.txt" создан.'

    assert (desktop / "note.txt").is_file()
    assert (desktop / "note.txt").read_text(encoding="utf-8") == ""
    assert manager.last_created_name == "note.txt"


def test_existing_file_is_reported_and_not_overwritten(manager: FileManager, desktop: Path) -> None:
    (desktop / "note.txt").write_text("важное", encoding="utf-8")

    assert manager.create_file("note.txt") == 'Файл "note.txt" уже существует.'
    assert (desktop / "note.txt").read_text(encoding="utf-8") == "важное"


def test_nested_file(manager: FileManager, desktop: Path) -> None:
    manager.create_file("sub/note.txt")

    assert (desktop / "sub" / "note.txt").is_file()


def test_exists_and_delete(manager: FileManager, desktop: Path) -> None:
    manager.create_file("note.txt")

    assert manager.exists("note.txt") is True
    assert manager.exists("missing.txt") is False

    assert manager.delete_file("note.txt") is True
    assert not (desktop / "note.txt").exists()
    assert manager.delete_file("note.txt") is False


def test_delete_matches_case_insensitively_in_subfolders(manager: FileManager, desktop: Path) -> None:
    (desktop / "sub").mkdir()
    (desktop / "sub" / "Photo.PNG").write_text("x", encoding="utf-8")

    assert manager.delete_file("photo.png") is True
    assert not (desktop / "sub" / "Photo.PNG").exists()


def test_find_file_by_full_name_and_without_extension(manager: FileManager, desktop: Path) -> None:
    (desktop / "отчёт_2026.md").write_text("x", encoding="utf-8")

    by_name = manager.find_file("отчёт_2026")
    assert "отчёт_2026.md" in by_name

    by_extension = manager.find_file(".md")
    assert "отчёт_2026.md" in by_extension


def test_find_file_reports_nothing(manager: FileManager) -> None:
    assert manager.find_file("нет-такого") == 'Файл "нет-такого" не найден.'


def test_find_file_limits_results(manager: FileManager, desktop: Path) -> None:
    for index in range(15):
        (desktop / f"file{index}.txt").write_text("x", encoding="utf-8")

    answer = manager.find_file("file")
    assert answer.count("•") == 10


def test_create_folder_refreshes_folder_search(manager: FileManager, desktop: Path) -> None:
    # Первый поиск строит индекс и запоминает отсутствие папки.
    assert "не найдена" in manager.find_folders("новая")

    manager.create_folder("новая")

    # Создание папки сбрасывает индекс — ждать TTL не нужно.
    assert "новая" in manager.find_folders("новая")


@pytest.mark.parametrize(
    "name",
    [
        "../secret.txt",
        "..",
        ".",
        "/etc/passwd",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "c:/windows/win.ini",
        "sub/../../secret.txt",
        "   ",
    ],
)
def test_traversal_is_rejected(manager: FileManager, name: str) -> None:
    assert manager.create_file(name).startswith("Недопустимый путь")
    assert manager.create_folder(name).startswith("Недопустимый путь")
    assert manager.exists(name) is False


def test_symlink_escaping_desktop_is_rejected(
    manager: FileManager, desktop: Path, tmp_path: Path
) -> None:
    """Симлинк внутри рабочего стола не должен вывести запись наружу."""
    outside = tmp_path / "outside"
    outside.mkdir()

    try:
        (desktop / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("симлинки недоступны в этой файловой системе")

    answer = manager.create_file("link/escape.txt")

    assert answer.startswith("Недопустимый путь")
    assert not (outside / "escape.txt").exists()
