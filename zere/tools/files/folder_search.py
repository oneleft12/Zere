"""Поиск папок по системе: ограниченный обход, ранжирование, кэш индекса.

Почему не `Path.rglob("*")` по всему диску, как в `FileManager.find_file`:

- обход всего профиля/диска без границ занимает десятки секунд и подвешивает
  и чат, и панель (HTTP-запрос ждёт ответа синхронно);
- в профиле есть `AppData`, `node_modules`, `.git`, `venv` — это десятки
  тысяч каталогов, которые пользователь не ищет;
- точное имя, начало имени и часть имени должны стоять в выдаче выше, чем
  случайное совпадение в глубине.

Поэтому здесь BFS (сначала мелкие уровни), жёсткие пределы по времени и
числу каталогов, пропуск служебных/скрытых/переходных (symlink, junction)
каталогов и ранжирование совпадений. Индекс строится один раз и живёт
`index_ttl_seconds`; повторный запрос фильтрует его в памяти.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Sequence

_IS_WINDOWS = os.name == "nt"

#: Служебные и заведомо «не пользовательские» каталоги. Сравнение — casefold.
_SKIP_NAMES = frozenset(
    {
        "$recycle.bin",
        "$windows.~bt",
        "$windows.~ws",
        "$winreagent",
        "appdata",
        "application data",
        "config.msi",
        "local settings",
        "node_modules",
        "onedrivetemp",
        "perflogs",
        "program files",
        "program files (x86)",
        "programdata",
        "recovery",
        "system volume information",
        "windows",
        "winsxs",
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "site-packages",
    }
)

#: Имена стандартных папок Windows/OneDrive, которые ищутся без обхода.
_KNOWN_FOLDERS: tuple[tuple[str, str], ...] = (
    ("desktop", "Desktop"),
    ("documents", "Documents"),
    ("downloads", "Downloads"),
    ("pictures", "Pictures"),
    ("music", "Music"),
    ("videos", "Videos"),
)

#: FOLDERID_* из knownfolders.h: настоящий путь папки с учётом переноса
#: Desktop/Documents на другой диск или в OneDrive.
_KNOWN_FOLDER_GUIDS: dict[str, str] = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}

#: Псевдонимы для голосовых команд. Значение — ключ `_KNOWN_FOLDERS` или
#: специальные `home`/`onedrive`.
_ALIASES: dict[str, str] = {
    "рабочий стол": "desktop",
    "рабочем столе": "desktop",
    "desktop": "desktop",
    "документы": "documents",
    "документах": "documents",
    "documents": "documents",
    "загрузки": "downloads",
    "загрузка": "downloads",
    "загрузках": "downloads",
    "downloads": "downloads",
    "картинки": "pictures",
    "изображения": "pictures",
    "фото": "pictures",
    "pictures": "pictures",
    "музыка": "music",
    "music": "music",
    "видео": "videos",
    "videos": "videos",
    "домашняя папка": "home",
    "домашнюю папку": "home",
    "профиль": "home",
    "home": "home",
    "onedrive": "onedrive",
    "вандрайв": "onedrive",
}

#: Практическая транслитерация: «proekty» находит «Проекты».
_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

#: Частые пары «русская команда → английское имя папки». Это не перевод
#: всего на свете, а мостик для типовых названий (Projects/Downloads/...).
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "проект": ("project",),
    "проекты": ("projects",),
    "загрузки": ("downloads",),
    "документы": ("documents",),
    "фото": ("photos", "pictures"),
    "картинки": ("pictures", "images"),
    "музыка": ("music",),
    "видео": ("videos",),
    "работа": ("work",),
    "учёба": ("study", "school"),
    "учеба": ("study", "school"),
    "игры": ("games",),
    "архив": ("archive",),
    "файлы": ("files",),
}

_CYRILLIC = re.compile(r"[а-яё]")
_TOKEN_SPLIT = re.compile(r"[\W_]+", re.UNICODE)
#: FILE_ATTRIBUTE_REPARSE_POINT / FILE_ATTRIBUTE_HIDDEN (Windows).
_REPARSE_POINT = 0x400
_HIDDEN = 0x2


@dataclass(frozen=True)
class FolderHit:
    """Одно совпадение: папка, её путь и признак, по которому она найдена."""

    path: Path
    name: str
    parent: Path
    depth: int
    score: int
    reason: str
    modified: float | None = None


@dataclass(frozen=True)
class FolderSearchResult:
    """Результат запроса: выдача, полное число совпадений и пределы обхода."""

    query: str
    hits: tuple[FolderHit, ...]
    total: int
    truncated: bool
    duration_ms: int
    indexed: int
    from_cache: bool


@dataclass(frozen=True)
class _Entry:
    path: Path
    name: str
    depth: int


@dataclass(frozen=True)
class _Index:
    entries: tuple[_Entry, ...]
    truncated: bool
    built_at: float


def _norm(text: str) -> str:
    """Casefold + «ё → е» + схлопывание пробелов: «рабочий  стол» тоже стол."""
    return " ".join(text.casefold().replace("ё", "е").split())


def _translit(text: str) -> str:
    return "".join(_TRANSLIT.get(char, char) for char in text)


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_SPLIT.split(_norm(text)) if token]


def _query_variants(query: str) -> tuple[str, ...]:
    """Варианты запроса: как есть, транслит и типовые английские синонимы."""
    base = _norm(query)
    variants: list[str] = [base]

    if _CYRILLIC.search(base):
        variants.append(_translit(base))

    for synonym in _SYNONYMS.get(base, ()):
        variants.append(_norm(synonym))

    # Убираем пустые и повторы, сохраняя порядок.
    unique: list[str] = []
    for variant in variants:
        if variant and variant not in unique:
            unique.append(variant)
    return tuple(unique)


def _score_one(name: str, variant: str) -> tuple[int, str]:
    """Оценка одного варианта запроса против имени папки."""
    if not variant or not name:
        return 0, ""

    if name == variant:
        return 1000, "exact"

    if name.startswith(variant):
        return 850, "prefix"

    query_tokens = _tokens(variant)
    name_tokens = _tokens(name)

    if query_tokens and name_tokens:
        if all(
            any(token.startswith(query_token) for token in name_tokens)
            for query_token in query_tokens
        ):
            return 780, "words"

        # Запрос длиннее имени: «мои проекты» → «Проекты».
        if all(len(token) >= 2 for token in name_tokens) and all(
            any(query_token.startswith(token) for query_token in query_tokens)
            for token in name_tokens
        ):
            return 620, "words"

    if variant in name:
        return 700, "substring"

    if any(query_token in token for query_token in query_tokens for token in name_tokens):
        return 640, "part"

    # Опечатки — только для одиночного достаточно длинного слова.
    if len(variant) >= 4 and len(name_tokens) == 1:
        ratio = SequenceMatcher(None, variant, name).ratio()
        if ratio >= 0.76:
            return int(520 * ratio), "fuzzy"

    return 0, ""


def _score(name: str, variants: Sequence[str]) -> tuple[int, str]:
    best_score = 0
    best_reason = ""

    normalized_name = _norm(name)
    name_variants = [normalized_name]
    if _CYRILLIC.search(normalized_name):
        # Латиница пользователя («proekty») должна находить кириллицу.
        name_variants.append(_translit(normalized_name))

    for variant in variants:
        for name_variant in name_variants:
            score, reason = _score_one(name_variant, variant)
            if score > best_score:
                best_score, best_reason = score, reason

    return best_score, best_reason


def _windows_known_folder(guid_text: str) -> Path | None:
    """Путь FOLDERID через SHGetKnownFolderPath (None — не Windows/сбой)."""
    if not _IS_WINDOWS:
        return None

    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        parts = guid_text.split("-")
        if len(parts) != 5:
            return None

        guid = GUID()
        guid.Data1 = int(parts[0], 16)
        guid.Data2 = int(parts[1], 16)
        guid.Data3 = int(parts[2], 16)
        tail = bytes.fromhex(parts[3] + parts[4])
        guid.Data4 = (ctypes.c_ubyte * 8)(*tail)

        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long

        path_ptr = ctypes.c_wchar_p()
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
        )
        if result != 0:
            return None

        try:
            value = path_ptr.value
            return Path(value) if value else None
        finally:
            ole32 = ctypes.windll.ole32
            ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole32.CoTaskMemFree(ctypes.cast(path_ptr, ctypes.c_void_p))
    except Exception:  # noqa: BLE001 — без known folder остаются обычные пути
        return None


def _known_paths() -> dict[str, Path]:
    """Стандартные папки: настоящий FOLDERID, OneDrive или профиль."""
    home = Path.home()
    one_drive = home / "OneDrive"
    paths: dict[str, Path] = {}

    for key, folder_name in _KNOWN_FOLDERS:
        candidates: list[Path] = []
        known = _windows_known_folder(_KNOWN_FOLDER_GUIDS[key])
        if known is not None:
            candidates.append(known)
        candidates.extend((one_drive / folder_name, home / folder_name))
        paths[key] = next(
            (path for path in candidates if path.is_dir()), candidates[-1]
        )

    paths["home"] = home
    paths["onedrive"] = one_drive
    return paths


def _fixed_drives() -> list[Path]:
    """Локальные диски Windows (без съёмных и сетевых)."""
    if not _IS_WINDOWS:
        return []

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetLogicalDrives.restype = ctypes.c_uint
        kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetDriveTypeW.restype = ctypes.c_uint

        mask = kernel32.GetLogicalDrives()
        drives: list[Path] = []
        for index in range(26):
            if not mask & (1 << index):
                continue
            root = Path(f"{chr(65 + index)}:\\")
            if kernel32.GetDriveTypeW(str(root)) == 3:  # DRIVE_FIXED
                drives.append(root)
        return drives
    except Exception:  # noqa: BLE001 — без ctypes поиск по профилю тоже работает
        return []


def _dedupe(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _default_roots(include_system: bool) -> list[Path]:
    known = _known_paths()
    roots: list[Path] = []

    for key in ("desktop", "documents", "downloads", "pictures", "music", "videos", "onedrive"):
        path = known.get(key)
        if path is not None and path.is_dir():
            roots.append(path)

    home = known["home"]
    if home.is_dir():
        roots.append(home)

    if include_system:
        roots.extend(_fixed_drives())

    return _dedupe(roots)


def _is_reparse_point(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _is_hidden(st: os.stat_result, name: str) -> bool:
    if name.startswith("."):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _HIDDEN)


def _skip_name(name: str) -> bool:
    return name.casefold() in _SKIP_NAMES or name.startswith(".")


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _hit_for_path(path: Path, score: int, reason: str, depth: int) -> FolderHit:
    return FolderHit(
        path=path,
        name=path.name or path.anchor or str(path),
        parent=path.parent,
        depth=depth,
        score=score,
        reason=reason,
        modified=_mtime(path),
    )


def best_match(hits: Sequence[FolderHit]) -> Path | None:
    """Однозначный выбор: точное имя или заметный отрыв от второго места.

    Если непонятно, какая из папок имелась в виду, возвращается None —
    обработчик покажет список и попросит уточнить номер.
    """
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0].path

    top, second = hits[0], hits[1]
    # Две папки с одинаковым точным именем — это не «однозначно»: пусть
    # пользователь выберет номер, а не получит первую попавшуюся.
    if top.score >= 950 and top.score > second.score:
        return top.path
    if top.score - second.score >= 150:
        return top.path
    return None


class FolderSearchService:
    """Индекс папок с ограниченным обходом и кэшем на `index_ttl_seconds`."""

    def __init__(
        self,
        roots: Sequence[Path] | None = None,
        *,
        include_system_roots: bool = True,
        max_depth: int = 6,
        max_entries: int = 20_000,
        budget_seconds: float = 2.0,
        refresh_budget_seconds: float = 6.0,
        index_ttl_seconds: float = 60.0,
        max_results: int = 20,
    ) -> None:
        self._roots = list(roots) if roots is not None else _default_roots(include_system_roots)
        self._max_depth = max(0, max_depth)
        self._max_entries = max(1, max_entries)
        self._budget_seconds = max(0.0, budget_seconds)
        # Явное «Обновить» в панели может позволить себе более долгий обход:
        # обычный поиск ограничен 2 с, а полная пересборка индекса — 6 с.
        self._refresh_budget_seconds = max(self._budget_seconds, refresh_budget_seconds)
        self._index_ttl_seconds = max(0.0, index_ttl_seconds)
        self._max_results = max(1, max_results)
        self._index: _Index | None = None
        self._lock = threading.RLock()

    # ── Публичный API ────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        refresh: bool = False,
    ) -> FolderSearchResult:
        started = time.monotonic()
        text = (query or "").strip()
        limit = max(1, min(limit or self._max_results, 100))

        if not text:
            hits = self._known_hits()[:limit]
            return FolderSearchResult(
                query=text,
                hits=tuple(hits),
                total=len(hits),
                truncated=False,
                duration_ms=int((time.monotonic() - started) * 1000),
                indexed=0,
                from_cache=False,
            )

        direct = self._direct_path(text)
        if direct is not None:
            hit = _hit_for_path(direct, 1000, "path", 0)
            return FolderSearchResult(
                query=text,
                hits=(hit,),
                total=1,
                truncated=False,
                duration_ms=int((time.monotonic() - started) * 1000),
                indexed=0,
                from_cache=False,
            )

        alias_hits = self._alias_hits(text)
        if alias_hits:
            return FolderSearchResult(
                query=text,
                hits=tuple(alias_hits[:limit]),
                total=len(alias_hits),
                truncated=False,
                duration_ms=int((time.monotonic() - started) * 1000),
                indexed=0,
                from_cache=False,
            )

        index, from_cache = self._ensure_index(
            refresh,
            self._refresh_budget_seconds if refresh else None,
        )
        matches: list[FolderHit] = []
        seen: set[str] = set()
        variants = _query_variants(text)

        for entry in index.entries:
            score, reason = _score(entry.name, variants)
            if score <= 0:
                continue

            key = os.path.normcase(os.path.abspath(str(entry.path)))
            if key in seen:
                continue
            seen.add(key)

            matches.append(
                FolderHit(
                    path=entry.path,
                    name=entry.name,
                    parent=entry.path.parent,
                    depth=entry.depth,
                    score=score,
                    reason=reason,
                )
            )

        matches.sort(
            key=lambda hit: (
                -hit.score,
                hit.depth,
                len(hit.name),
                str(hit.path).casefold(),
            )
        )

        # Время изменения нужно только для показа: читаем его у выдачи, а не
        # у каждого каталога при обходе (на медленном диске это половина цены).
        hits = tuple(
            replace(hit, modified=_mtime(hit.path)) for hit in matches[:limit]
        )

        return FolderSearchResult(
            query=text,
            hits=hits,
            total=len(matches),
            truncated=index.truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
            indexed=len(index.entries),
            from_cache=from_cache,
        )

    def resolve(self, query: str) -> Path | None:
        """Путь, если запрос однозначен; None — нет совпадений или спор."""
        result = self.search(query, limit=5)
        return best_match(result.hits)

    def is_known_folder(self, query: str) -> bool:
        """Быстрая проверка без обхода: алиас стандартной папки или путь.

        Нужна «открой загрузки»: WindowsHandler сначала пробует приложение,
        а обход диска на каждое неизвестное имя приложения недопустим.
        """
        text = (query or "").strip()
        if not text:
            return False
        if self._alias_hits(text) or self._direct_path(text) is not None:
            return True

        if any(part in ("..", ".") for part in text.replace("\\", "/").split("/")):
            return False

        # Папка первого уровня в одном из корней: «открой Projects» без
        # полного обхода. Проверка дешёвая — корней единицы.
        for root in self._roots:
            try:
                if (root / text).is_dir():
                    return True
            except (OSError, ValueError):
                continue
        return False

    def refresh(self) -> None:
        with self._lock:
            self._index = None

    # ── Стандартные папки и псевдонимы ──────────────────────────

    def _known_hits(self) -> list[FolderHit]:
        known = _known_paths()
        order = ("desktop", "documents", "downloads", "pictures", "music", "videos", "onedrive", "home")
        hits: list[FolderHit] = []
        seen: set[str] = set()

        for key in order:
            path = known.get(key)
            if path is None or not path.is_dir():
                continue

            normalized = os.path.normcase(os.path.abspath(str(path)))
            if normalized in seen:
                continue
            seen.add(normalized)
            hits.append(_hit_for_path(path, 1000, "known", 0))

        return hits

    def _alias_hits(self, query: str) -> list[FolderHit]:
        normalized = _norm(query).strip("\"'«»")
        if not normalized:
            return []

        known = _known_paths()
        hits: list[FolderHit] = []
        seen: set[str] = set()

        for alias, key in _ALIASES.items():
            alias_norm = _norm(alias)
            if alias_norm == normalized:
                score, reason = 1000, "alias"
            elif len(normalized) >= 3 and alias_norm.startswith(normalized):
                score, reason = 850, "alias"
            else:
                continue

            path = known.get(key)
            if path is None or not path.is_dir():
                continue

            path_key = os.path.normcase(os.path.abspath(str(path)))
            if path_key in seen:
                continue
            seen.add(path_key)
            hits.append(_hit_for_path(path, score, reason, 0))

        hits.sort(key=lambda hit: (-hit.score, len(hit.name)))
        return hits

    def _direct_path(self, query: str) -> Path | None:
        text = query.strip().strip("\"'«»")
        if not text:
            return None

        expanded = os.path.expandvars(os.path.expanduser(text))
        candidate = Path(expanded)
        is_absolute = candidate.is_absolute() or (
            len(expanded) > 2 and expanded[1] == ":" and expanded[2] in "\\/"
        )

        if not is_absolute:
            return None

        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            return None
        return None

    # ── Индекс ───────────────────────────────────────────────────

    def _ensure_index(
        self, refresh: bool, budget_seconds: float | None = None
    ) -> tuple[_Index, bool]:
        with self._lock:
            now = time.monotonic()
            if (
                not refresh
                and self._index is not None
                and now - self._index.built_at <= self._index_ttl_seconds
            ):
                return self._index, True

            index = self._build_index(budget_seconds)
            self._index = index
            return index, False

    def _build_index(self, budget_seconds: float | None = None) -> _Index:
        started = time.monotonic()
        budget = self._budget_seconds if budget_seconds is None else budget_seconds
        deadline = started + budget if budget > 0 else None
        entries: list[_Entry] = []
        seen: set[str] = set()
        truncated = False

        queue: deque[tuple[Path, int]] = deque()
        for root in self._roots:
            try:
                if root.is_dir():
                    queue.append((root, 0))
            except OSError:
                continue

        while queue:
            if len(entries) >= self._max_entries or (
                deadline is not None and time.monotonic() > deadline
            ):
                truncated = True
                break

            path, depth = queue.popleft()
            key = os.path.normcase(os.path.abspath(str(path)))
            if key in seen:
                continue
            seen.add(key)

            entries.append(
                _Entry(
                    path=path,
                    name=path.name or path.anchor or str(path),
                    depth=depth,
                )
            )

            if depth >= self._max_depth:
                continue

            children: list[Path] = []
            try:
                with os.scandir(path) as iterator:
                    for child in iterator:
                        if len(entries) + len(children) >= self._max_entries:
                            truncated = True
                            break
                        if deadline is not None and time.monotonic() > deadline:
                            truncated = True
                            break

                        try:
                            if not child.is_dir(follow_symlinks=False):
                                continue
                        except OSError:
                            continue

                        if _skip_name(child.name):
                            continue

                        if _IS_WINDOWS:
                            try:
                                child_stat = child.stat(follow_symlinks=False)
                            except OSError:
                                continue
                            if _is_reparse_point(child_stat) or _is_hidden(
                                child_stat, child.name
                            ):
                                continue

                        children.append(Path(child.path))
            except (PermissionError, OSError):
                continue

            # Детерминированный порядок: одинаковые запросы дают одинаковую выдачу.
            children.sort(key=lambda child: child.name.casefold())
            for child in children:
                queue.append((child, depth + 1))

        return _Index(entries=tuple(entries), truncated=truncated, built_at=started)
