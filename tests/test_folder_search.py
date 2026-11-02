"""Тесты поиска папок: ранжирование, пределы обхода, кэш и открытие.

Проверяется то, что нельзя увидеть «на глаз»: служебные каталоги не попадают
в индекс, ссылки не зацикливают обход, лимиты времени/числа каталогов
честно помечают выдачу как неполную, а неоднозначный запрос не открывает
первую попавшуюся папку.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from zere.tools.files.file_command_router import FileCommandRouter
from zere.tools.files.file_command_type import FileCommandType
from zere.tools.files.file_manager import FileManager
from zere.tools.files.folder_opener import FolderOpener
from zere.tools.files.folder_search import (
    FolderSearchService,
    _default_roots,
    _known_paths,
    _norm,
    _translit,
    best_match,
)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    # Нейтральное имя корня: путь pytest содержит имя теста, и совпадение
    # с ним маскировало бы проверяемое поведение.
    root = tmp_path / "base"
    (root / "Проекты" / "2026").mkdir(parents=True)
    (root / "Документы" / "Проект Альфа").mkdir(parents=True)
    (root / "Документы" / "Проект Бета").mkdir(parents=True)
    (root / "Downloads").mkdir()
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / ".hidden").mkdir()
    return root


def service(root: Path, **kwargs: object) -> FolderSearchService:
    options = {
        "include_system_roots": False,
        "max_depth": 4,
        "max_entries": 1000,
        "budget_seconds": 5.0,
        "index_ttl_seconds": 60.0,
    }
    options.update(kwargs)
    return FolderSearchService(roots=[root], **options)  # type: ignore[arg-type]


# ── Ранжирование ────────────────────────────────────────────────────


def test_exact_name_wins(tree: Path) -> None:
    result = service(tree).search("проекты")

    assert result.hits[0].name == "Проекты"
    assert result.hits[0].reason == "exact"
    assert result.hits[0].score == 1000


def test_prefix_matches_are_ranked_before_deep_matches(tree: Path) -> None:
    result = service(tree).search("проект")

    names = [hit.name for hit in result.hits]
    assert names[:2] == ["Проекты", "Проект Альфа"] or names[:2] == ["Проекты", "Проект Бета"]
    assert "Проекты" in names
    assert "Проект Альфа" in names


def test_multi_word_query_matches_reordered_tokens(tree: Path) -> None:
    result = service(tree).search("альфа проект")

    assert result.hits
    assert result.hits[0].name == "Проект Альфа"


def test_case_and_yo_are_ignored(tree: Path) -> None:
    (tree / "Ёлка").mkdir()

    assert service(tree).search("елка").hits[0].name == "Ёлка"
    assert service(tree).search("ПРОЕКТЫ").hits[0].name == "Проекты"


def test_latin_query_finds_cyrillic_folder(tree: Path) -> None:
    assert _translit("проекты") == "proekty"
    assert service(tree).search("proekty").hits[0].name == "Проекты"


def test_cyrillic_query_finds_latin_folder(tree: Path) -> None:
    (tree / "proekt42").mkdir()

    result = service(tree).search("проект42")

    assert result.hits[0].name == "proekt42"
    assert result.hits[0].score == 1000
    assert result.hits[0].reason == "exact"


def test_russian_query_finds_english_folder(tree: Path) -> None:
    (tree / "Projects").mkdir()

    names = [hit.name for hit in service(tree).search("проекты").hits]

    assert "Projects" in names


def test_typo_is_tolerated(tree: Path) -> None:
    result = service(tree).search("проеты")

    assert result.hits
    assert result.hits[0].name == "Проекты"
    assert result.hits[0].reason == "fuzzy"


# ── Пределы и пропуски ───────────────────────────────────────────────


def test_service_folders_are_not_indexed(tree: Path) -> None:
    result = service(tree).search("node_modules")

    assert result.hits == ()


def test_hidden_folders_are_not_indexed(tree: Path) -> None:
    assert service(tree).search("hidden").hits == ()


def test_depth_limit(tree: Path) -> None:
    deep = tree / "a" / "b" / "c" / "d" / "цель"
    deep.mkdir(parents=True)

    assert service(tree, max_depth=2).search("цель").hits == ()
    assert service(tree, max_depth=6).search("цель").hits


def test_entry_limit_marks_result_truncated(tree: Path) -> None:
    for index in range(20):
        (tree / f"папка{index}").mkdir()

    result = service(tree, max_entries=2).search("папка")

    assert result.truncated is True
    assert result.indexed <= 2


def test_symlink_loop_does_not_hang(tree: Path) -> None:
    loop = tree / "loop"
    try:
        loop.symlink_to(tree, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("символические ссылки недоступны")

    result = service(tree).search("loop")

    # Ссылка не индексируется и не зацикливает обход.
    assert result.hits == ()
    assert result.truncated is False


def test_direct_path_returns_existing_folder(tree: Path) -> None:
    target = tree / "Проекты"

    result = service(tree).search(str(target))

    assert result.total == 1
    assert result.hits[0].path == target.resolve()
    assert result.hits[0].reason == "path"


def test_empty_query_returns_standard_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "zere.tools.files.folder_search._windows_known_folder", lambda guid: None
    )
    (tmp_path / "Desktop").mkdir()
    (tmp_path / "Documents").mkdir()
    (tmp_path / "Downloads").mkdir()

    result = FolderSearchService(roots=None, include_system_roots=False).search("")

    names = [hit.name for hit in result.hits]
    assert names[:3] == ["Desktop", "Documents", "Downloads"]
    assert all(hit.reason == "known" for hit in result.hits)


def test_alias_opens_standard_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "zere.tools.files.folder_search._windows_known_folder", lambda guid: None
    )
    (tmp_path / "Downloads").mkdir()

    search = FolderSearchService(roots=None, include_system_roots=False)

    assert search.search("загрузки").hits[0].name == "Downloads"
    assert search.resolve("загрузки") == (tmp_path / "Downloads").resolve()


# ── Кэш и однозначность ─────────────────────────────────────────────


def test_index_is_cached_until_refresh(tree: Path) -> None:
    search = service(tree)

    assert search.search("новая").hits == ()

    (tree / "новая").mkdir()

    assert search.search("новая").hits == ()
    assert search.search("новая", refresh=True).hits[0].name == "новая"


def test_best_match_rejects_ambiguity(tree: Path) -> None:
    result = service(tree).search("проект", limit=10)

    assert len(result.hits) >= 2
    assert best_match(result.hits) is None


def test_best_match_accepts_exact_name(tree: Path) -> None:
    result = service(tree).search("проекты")

    assert best_match(result.hits) == (tree / "Проекты").resolve()


def test_best_match_rejects_duplicate_exact_names(tmp_path: Path) -> None:
    (tmp_path / "a" / "Проекты").mkdir(parents=True)
    (tmp_path / "b" / "Проекты").mkdir(parents=True)

    result = service(tmp_path).search("проекты")

    assert len(result.hits) == 2
    assert all(hit.score == 1000 for hit in result.hits)
    assert best_match(result.hits) is None


def test_known_paths_and_roots_are_sane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        "zere.tools.files.folder_search._windows_known_folder", lambda guid: None
    )
    (tmp_path / "Desktop").mkdir()
    (tmp_path / "Documents").mkdir()

    known = _known_paths()
    roots = _default_roots(include_system=False)

    assert known["desktop"] == tmp_path / "Desktop"
    assert known["home"] == tmp_path
    assert tmp_path / "Desktop" in roots
    assert tmp_path / "Documents" in roots


# ── FileManager: текст и открытие ───────────────────────────────────


class FakeStartfile:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def __call__(self, path: str) -> None:
        self.opened.append(path)


def manager_for(tree: Path) -> tuple[FileManager, FakeStartfile]:
    fake = FakeStartfile()
    files = FileManager(
        folders=service(tree),
        opener=FolderOpener(system="nt", startfile=fake),
    )
    return files, fake


def test_find_folders_formats_paths(tree: Path) -> None:
    files, _ = manager_for(tree)

    answer = files.find_folders("проекты")

    assert "Найденные папки" in answer
    assert "Проекты" in answer
    assert str(tree / "Проекты") in answer


def test_find_folders_reports_nothing(tree: Path) -> None:
    files, _ = manager_for(tree)

    assert files.find_folders("нет-такой") == 'Папка "нет-такой" не найдена.'


def test_open_folder_calls_startfile(tree: Path) -> None:
    files, fake = manager_for(tree)

    answer = files.open_folder("проекты")

    assert "Открываю папку" in answer
    assert fake.opened == [str((tree / "Проекты").resolve())]
    assert files.last_found_folder == (tree / "Проекты").resolve()


def test_open_ambiguous_folder_asks_to_clarify(tree: Path) -> None:
    files, fake = manager_for(tree)

    answer = files.open_folder("проект")

    assert "Нашёл несколько папок" in answer
    assert "открой папку 1" in answer
    assert fake.opened == []

    answer = files.open_folder("2")
    assert "Открываю папку" in answer
    assert len(fake.opened) == 1


def test_open_folder_by_number_without_search(tree: Path) -> None:
    files, fake = manager_for(tree)

    assert "Сначала найдите папку" in files.open_folder("1")
    assert fake.opened == []


def test_open_last_folder_with_empty_query(tree: Path) -> None:
    files, fake = manager_for(tree)

    files.open_folder("проекты")
    fake.opened.clear()

    assert "Открываю папку" in files.open_folder("")
    assert fake.opened == [str((tree / "Проекты").resolve())]


def test_open_empty_query_after_ambiguous_search_asks_number(tree: Path) -> None:
    files, fake = manager_for(tree)

    assert "Нашёл несколько папок" in files.open_folder("проект")
    assert "несколько папок" in files.open_folder("")
    assert fake.opened == []


def test_open_path_for_panel(tree: Path) -> None:
    files, fake = manager_for(tree)

    opened, message = files.open_path(tree / "Проекты")

    assert opened is True
    assert "Открываю папку" in message
    assert fake.opened == [str(tree / "Проекты")]


def test_opener_reports_missing_folder(tmp_path: Path) -> None:
    opener = FolderOpener(system="nt", startfile=FakeStartfile())

    opened, message = opener.open(tmp_path / "нет")

    assert opened is False
    assert "не найдена" in message


def test_norm_and_translit_helpers() -> None:
    assert _norm("  ЁЛКА ") == "елка"
    assert _translit("ёж") == "ezh"


# ── Разбор команд ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("phrase", "expected", "value"),
    [
        ("найди папку проекты", FileCommandType.FIND_FOLDER, "проекты"),
        ("найти папку отчёты", FileCommandType.FIND_FOLDER, "отчёты"),
        ("поищи папку фото", FileCommandType.FIND_FOLDER, "фото"),
        ("где папка загрузки", FileCommandType.FIND_FOLDER, "загрузки"),
        ("открой папку проекты", FileCommandType.OPEN_FOLDER, "проекты"),
        ("открыть каталог фото", FileCommandType.OPEN_FOLDER, "фото"),
        ("покажи папку документы", FileCommandType.OPEN_FOLDER, "документы"),
        ("открой папку", FileCommandType.OPEN_FOLDER, ""),
        ("открой её", FileCommandType.OPEN_FOLDER, ""),
    ],
)
def test_router_parses_folder_commands(
    phrase: str, expected: FileCommandType, value: str
) -> None:
    parsed = FileCommandRouter().parse(phrase)

    assert parsed.type is expected
    assert parsed.value == value


def test_router_does_not_steal_file_commands() -> None:
    parsed = FileCommandRouter().parse("найди файл отчёт")

    assert parsed.type is FileCommandType.FIND_FILE
    assert parsed.value == "отчёт"


def test_windows_path_is_not_a_direct_folder_on_linux(tmp_path: Path) -> None:
    """Путь Windows не должен приниматься за локальный каталог в тестах."""
    if os.name == "nt":
        pytest.skip("тест про поведение не-Windows")

    search = service(tmp_path)

    assert search.search(r"Z:\нет-такого").hits == ()
