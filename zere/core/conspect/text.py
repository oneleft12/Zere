"""Извлечение текста из источника: локальный файл, PDF, страница по URL.

Здесь намеренно нет MCP-серверов файловой системы и выкачивания страниц:

- **файлы** читаются встроенно — сторонний процесс с правами пользователя
  в критическом пути конспекта не нужен, а `filesystem-mcp` дал бы чужому
  серверу доступ ко всему диску (docs/CONSPECT.md, §7);
- **страницы** забираются `requests` — он уже зависимость проекта, а
  разбирать HTML умеет стандартный `HTMLParser`, поэтому `fetch-mcp` не
  нужен: браузер (Playwright MCP) остаётся для страниц, которые без JS
  вообще не отдают текст.

Сеть — единственное место, где конспектор выходит наружу, и только по явной
команде пользователя с URL. Приватные адреса (127.0.0.1, 192.168.*, …) по
умолчанию запрещены: иначе ссылка из чужого текста превратилась бы в запрос
к локальным службам машины.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, List, Optional, Sequence
from urllib.parse import urlparse

from zere.core.conspect.errors import (
    DOWNLOAD_FAILED,
    SOURCE_EMPTY,
    SOURCE_NOT_FOUND,
    SOURCE_TOO_LARGE,
    SOURCE_UNSUPPORTED,
    URL_FORBIDDEN,
    ConspectError,
)

#: Расширения, которые читаем как текст.
TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".text",
        ".rst",
        ".log",
        ".csv",
        ".tsv",
        ".json",
        ".yaml",
        ".yml",
        ".srt",
        ".vtt",
        ".py",
        ".cs",
        ".js",
        ".ts",
        ".html",
        ".htm",
    }
)

#: Расширения PDF (нужен необязательный парсер pypdf).
PDF_SUFFIXES = frozenset({".pdf"})

#: Кодировки, которые пробуем по порядку: UTF-8, UTF-8 с BOM, Windows-1251.
_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1251")

#: Теги, содержимое которых текстом не является.
_DROP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "canvas",
        "iframe",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
        "select",
        "option",
    }
)

#: Теги, после которых начинается новая строка.
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "br",
        "li",
        "ul",
        "ol",
        "tr",
        "td",
        "th",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "hr",
        "figure",
        "figcaption",
        "dt",
        "dd",
    }
)

_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_HTML_SUFFIXES = frozenset({".html", ".htm"})


@dataclass
class SourceText:
    """Извлечённый материал: что конспектировать и откуда он взялся."""

    text: str
    title: str
    origin: str
    #: `file` | `url` | `text` — для ответа пользователю и frontmatter заметки.
    kind: str

    @property
    def chars(self) -> int:
        return len(self.text)


def _host_like(value: str) -> bool:
    """Похоже ли на имя хоста: «example.com» — да, «привет» и «/tmp» — нет."""
    candidate = (value or "").strip()

    if not candidate or "/" in candidate:
        return False

    labels = candidate.split(".")

    if len(labels) < 2 or any(not label for label in labels):
        return False

    return len(labels[-1]) >= 2


def is_url(value: str) -> bool:
    """Похоже ли значение на http(s)-адрес.

    Разбирать это приходится вручную: `urlparse` от `C:\\папка\\файл` видит
    «хост» `c:`, а от `лекция.md` — домен `.md` (такое расширение у Молдовы
    тоже есть). Ошибка тут дорогая: команда «законспектируй C:\\лекция.md»
    ушла бы в сеть вместо файла.

    Правила: явная схема, `www.`, имя хоста с точкой или путь с хостом в
    начале. Имя с известным файловым расширением (`lection.md`, `book.pdf`)
    адресом не считается никогда.
    """
    candidate = (value or "").strip()

    if not candidate or " " in candidate or "\\" in candidate:
        return False

    if re.match(r"^[A-Za-z]:", candidate):
        return False

    if "://" in candidate:
        parsed = urlparse(candidate)

        return parsed.scheme in ("http", "https") and bool(parsed.netloc)

    if Path(candidate).suffix.lower() in (TEXT_SUFFIXES | PDF_SUFFIXES):
        return False

    head = candidate.split("/", 1)[0]

    if candidate.startswith("www."):
        return _host_like(head)

    # Без схемы и без пути адресом считаем только ASCII-хост: «ya.ru» — да,
    # «лекция.ру» — нет (это скорее имя файла, чем домен).
    if "/" not in candidate:
        return head.isascii() and _host_like(head)

    return _host_like(head)


def normalize_url(value: str) -> str:
    """Достраивает схему: «example.com/статья» → «https://example.com/статья»."""
    candidate = (value or "").strip()

    if re.match(r"^[A-Za-z]:", candidate) or "\\" in candidate:
        raise ConspectError(URL_FORBIDDEN, f"Это не адрес, а путь: {candidate}")

    return candidate if "://" in candidate else f"https://{candidate}"


def is_private_host(host: str) -> bool:
    """Локальный или приватный адрес: localhost, 127.*, 192.168.*, ::1, *.local."""
    name = (host or "").strip().strip("[]").lower()

    if not name:
        return True

    if name in ("localhost", "localhost.localdomain") or name.endswith(".local"):
        return True

    if "." not in name and ":" not in name:
        # Имя без точки — внутрисетевой хост (например, «router»).
        return True

    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False

    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


# ── HTML → текст ──────────────────────────────────────────────────


class _TextExtractor(HTMLParser):
    """Вытаскивает текст страницы: без script/style и с переносами по блокам."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._title: List[str] = []
        self._skip_depth = 0
        self._in_title = False

    @property
    def title(self) -> str:
        return " ".join("".join(self._title).split())

    @property
    def text(self) -> str:
        raw = "".join(self._parts)
        raw = _WHITESPACE.sub(" ", raw)
        lines = [" ".join(line.split()) for line in raw.split("\n")]

        return _MANY_NEWLINES.sub("\n\n", "\n".join(lines)).strip()

    def handle_starttag(self, tag: str, attrs: Sequence[tuple[str, Optional[str]]]) -> None:
        name = tag.lower()

        if name in _DROP_TAGS:
            self._skip_depth += 1
            return

        if name == "title":
            self._in_title = True

        if name in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: Sequence[tuple[str, Optional[str]]]) -> None:
        if tag.lower() in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()

        if name in _DROP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if name == "title":
            self._in_title = False

        if name in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return

        if self._in_title:
            self._title.append(data)

        self._parts.append(data)


def html_to_text(html: str) -> str:
    """HTML → читаемый текст (скрипты, навигация и служебные теги отброшены)."""
    if not html:
        return ""

    parser = _TextExtractor()

    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — битый HTML не должен ломать конспект
        return _WHITESPACE.sub(" ", unescape(html)).strip()

    return parser.text


def html_title(html: str, fallback: str = "") -> str:
    """Заголовок страницы из `<title>` (пусто — вызывающий возьмёт адрес)."""
    if not html:
        return fallback

    parser = _TextExtractor()

    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001
        return fallback

    return parser.title or fallback


# ── Локальные файлы ───────────────────────────────────────────────


def _decode(raw: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace")


def _looks_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:8192]


def _read_pdf(path: Path) -> str:
    """Текст PDF через необязательный pypdf.

    Парсер не входит в обязательные зависимости (он нужен только для PDF и
    ставится установщиком), поэтому импорт локальный: без пакета выдаём
    понятную причину, а не падаем при старте ZERE.
    """
    try:
        import pypdf  # noqa: PLC0415 — необязательная зависимость
    except ImportError as ex:
        raise ConspectError(
            SOURCE_UNSUPPORTED,
            "Для PDF нужен пакет pypdf: установите его (pip install pypdf) "
            "или сохраните текст в .md/.txt.",
        ) from ex

    try:
        reader = pypdf.PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as ex:  # noqa: BLE001 — битый или защищённый PDF
        raise ConspectError(
            SOURCE_UNSUPPORTED,
            f"Не удалось прочитать PDF «{path.name}»: {ex}. "
            "Если это скан, нужен OCR — сохраните текст в .md/.txt.",
        ) from ex

    return "\n\n".join(page.strip() for page in pages if page.strip())


def read_file_source(path: Path, *, max_chars: int = 400_000) -> SourceText:
    """Читает локальный файл как материал для конспекта."""
    target = Path(path).expanduser()

    if not target.exists() or not target.is_file():
        raise ConspectError(SOURCE_NOT_FOUND, f"Файл не найден: {target}")

    suffix = target.suffix.lower()

    if suffix in PDF_SUFFIXES:
        text = _read_pdf(target)
    else:
        try:
            raw = target.read_bytes()
        except OSError as ex:
            raise ConspectError(SOURCE_UNSUPPORTED, f"Файл не читается: {ex}") from ex

        if _looks_binary(raw) and suffix not in (TEXT_SUFFIXES | _HTML_SUFFIXES):
            raise ConspectError(
                SOURCE_UNSUPPORTED,
                f"«{target.name}» — не текстовый файл. Поддерживаются: "
                ".md, .txt, .pdf и другие текстовые форматы.",
            )

        decoded = _decode(raw)
        text = html_to_text(decoded) if suffix in _HTML_SUFFIXES else decoded

    text = text.strip()

    if not text:
        raise ConspectError(SOURCE_EMPTY, f"В файле «{target.name}» нет текста.")

    if len(text) > max_chars:
        raise ConspectError(
            SOURCE_TOO_LARGE,
            f"Материал слишком большой: {len(text)} символов, "
            f"потолок — {max_chars}.",
        )

    return SourceText(text=text, title=target.stem, origin=str(target), kind="file")


# ── Страницы по URL ───────────────────────────────────────────────


def fetch_url_source(
    url: str,
    *,
    timeout: int = 60,
    max_download_chars: int = 2_000_000,
    max_chars: int = 400_000,
    session: Optional[Any] = None,
    allow_private: bool = False,
) -> SourceText:
    """Скачивает страницу и превращает её в текст.

    `session` — тесты подставляют фейковый объект с `.get(...)`: сеть в
    тестах не трогается (приём `tests/fake_http.py` в тестах ИИ).
    """
    address = normalize_url(url)
    parsed = urlparse(address)

    if parsed.scheme not in ("http", "https"):
        raise ConspectError(
            URL_FORBIDDEN, "Поддерживаются только адреса http:// и https://."
        )

    if not allow_private and is_private_host(parsed.hostname or ""):
        raise ConspectError(
            URL_FORBIDDEN,
            f"Адрес «{parsed.hostname}» ведёт на локальный или внутренний хост — "
            "конспектировать его запрещено.",
        )

    client = session
    close_client = False

    if client is None:
        import requests  # noqa: PLC0415 — уже объявлено в requirements.txt

        client = requests.Session()
        close_client = True

    try:
        response = client.get(
            address,
            timeout=timeout,
            headers={
                # Без User-Agent часть сайтов отвечает 403.
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ZERE-conspect/1.0",
                "Accept-Language": "ru,en;q=0.8",
            },
        )
        status = getattr(response, "status_code", 200)

        if status and int(status) >= 400:
            raise ConspectError(
                DOWNLOAD_FAILED, f"Страница не отдалась: код {status} ({parsed.netloc})."
            )

        html = getattr(response, "text", "") or ""
    except ConspectError:
        raise
    except Exception as ex:  # noqa: BLE001 — сеть/таймаут/DNS: причина одна
        raise ConspectError(
            DOWNLOAD_FAILED, f"Не удалось скачать страницу: {ex}"
        ) from ex
    finally:
        if close_client:
            try:
                client.close()
            except Exception:  # noqa: BLE001 — закрытие сессии не критично
                pass

    if len(html) > max_download_chars:
        html = html[:max_download_chars]

    text = html_to_text(html)

    if not text:
        raise ConspectError(
            SOURCE_EMPTY,
            f"Со страницы {parsed.netloc} не удалось вытащить текст "
            "(возможно, он рисуется скриптами — попробуйте MCP-браузер).",
        )

    if len(text) > max_chars:
        text = text[:max_chars]

    title = html_title(html, fallback=parsed.netloc)

    return SourceText(text=text, title=title, origin=address, kind="url")


def read_source(
    value: str,
    *,
    timeout: int = 60,
    max_chars: int = 400_000,
    max_download_chars: int = 2_000_000,
    session: Optional[Any] = None,
    allow_private: bool = False,
) -> SourceText:
    """Разбирает источник: URL → страница, иначе путь → файл.

    Текст «прямо в сообщении» сюда не попадает: это решает обработчик —
    у него есть порог, с какого размера фраза считается материалом.
    """
    candidate = (value or "").strip().strip('"').strip("'")

    if not candidate:
        raise ConspectError(SOURCE_EMPTY, "Не указан источник конспекта.")

    if is_url(candidate):
        return fetch_url_source(
            candidate,
            timeout=timeout,
            max_download_chars=max_download_chars,
            max_chars=max_chars,
            session=session,
            allow_private=allow_private,
        )

    return read_file_source(Path(candidate), max_chars=max_chars)


__all__ = [
    "PDF_SUFFIXES",
    "TEXT_SUFFIXES",
    "SourceText",
    "fetch_url_source",
    "html_title",
    "html_to_text",
    "is_private_host",
    "is_url",
    "normalize_url",
    "read_file_source",
    "read_source",
]
