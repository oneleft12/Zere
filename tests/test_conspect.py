"""Тесты движка конспектора (docs/CONSPECT.md): без сети и без модели.

Проверяем то, что нельзя проверить на живом ZERE: чанкование под окно
модели, извлечение текста из файла и страницы, безопасность записи в
хранилище и поведение при сбоях модели — часть, сводка, полный отказ.

`FakeAI` отвечает по смыслу промпта: на промпт части — заметками, на промпт
сводки — конспектом. Так тест видит, сколько вызовов модели реально сделано
(`map` + `reduce`), и не зависит от Ollama.

Запуск: `pytest tests/test_conspect.py -q`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fake_http import FakeResponse, FakeSession
from zere.ai.ai_service import MESSAGE_NOT_CONFIGURED
from zere.core.conspect import chunking, contract, text as text_module, vault
from zere.core.conspect.config import (
    ConspectSettings,
    load_conspect_settings,
    resolve_vault,
    vault_from_mcp_config,
)
from zere.core.conspect.errors import ConspectError
from zere.core.conspect.summarizer import Summarizer, plan_parts
from zere.core.conspect.text import SourceText, is_private_host, is_url, read_source
from zere.core.conspect.vault import VaultWriter, safe_relative_path

PART_ANSWER = "### Заметки\n- тезис части\n- второй тезис"
SUMMARY_ANSWER = (
    "## Суть\nМатериал про нейросети.\n"
    "## Ключевые тезисы\n- раз\n- два\n"
    "## Термины\n- LoRA — адаптер\n"
    "## Action items\n- нет\n"
    "## Открытые вопросы\n- нет"
)

#: Признак промпта сводки (второй проход map-reduce).
_SUMMARY_MARKER = "Собери из них один конспект"


class FakeAI:
    """Фейковый ИИ: ответ по виду промпта, сбои по номерам вызовов, статус для preflight."""

    def __init__(
        self,
        *,
        part: str = PART_ANSWER,
        summary: str = SUMMARY_ANSWER,
        failures: tuple[int, ...] = (),
        status: object = None,
    ) -> None:
        self.part = part
        self.summary = summary
        self.failures = set(failures)
        #: None — объект без состояния ИИ (проверка preflight пропускается).
        self.status_state = status
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        index = len(self.calls) + 1
        self.calls.append(
            {
                "prompt": prompt,
                "system": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )

        if index in self.failures:
            raise RuntimeError(f"сбой модели №{index}")

        return self.summary if _SUMMARY_MARKER in prompt else self.part

    @property
    def part_calls(self) -> list[dict[str, object]]:
        return [call for call in self.calls if _SUMMARY_MARKER not in str(call["prompt"])]

    @property
    def summary_calls(self) -> list[dict[str, object]]:
        return [call for call in self.calls if _SUMMARY_MARKER in str(call["prompt"])]

    def status(self) -> object:
        if self.status_state is None:
            # Не словарь — ai_bridge считает объект готовым (нет проверки).
            return None

        return self.status_state


@pytest.fixture()
def settings() -> ConspectSettings:
    return ConspectSettings(chunk_chars=300, chunk_overlap=50, tags=("конспект", "обучение"))


@pytest.fixture()
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "Конспекты").mkdir(parents=True)

    return root


@pytest.fixture()
def writer(vault_root: Path) -> VaultWriter:
    return VaultWriter(vault_root, folder="Конспекты")


def _long_text(paragraphs: int = 6, repeats: int = 12) -> str:
    return "\n\n".join(
        f"Абзац {number}. " + f"Мысль номер {number} про нейросети. " * repeats
        for number in range(1, paragraphs + 1)
    )


# ── Настройки ───────────────────────────────────────────────────────


def test_settings_defaults_when_file_missing(tmp_path: Path) -> None:
    settings = load_conspect_settings(tmp_path / "нет-такого.json")

    assert settings.enabled is True
    assert settings.resolved_folder == "Конспекты"
    assert settings.tags == ("конспект",)
    assert settings.subfolder_by_month is True


def test_settings_read_camel_and_snake_case(tmp_path: Path) -> None:
    path = tmp_path / "conspect.json"
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "vault": "  D:/Obsidian  ",
                "folder": "Книги/",
                "tags": "#конспект, обучение",
                "chunkChars": 1200,
                "chunk_overlap": 100,
                "maxChunks": 7,
                "writePaths": ["Книги", "Конспекты"],
                "temperature": 0.2,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings = load_conspect_settings(path)

    assert settings.vault == "D:/Obsidian"
    assert settings.folder == "Книги/"
    assert settings.resolved_folder == "Книги"
    assert settings.tags == ("конспект", "обучение")
    assert settings.chunk_chars == 1200
    assert settings.chunk_overlap == 100
    assert settings.max_chunks == 7
    assert settings.write_paths == ("Книги", "Конспекты")
    assert settings.temperature == pytest.approx(0.2)


def test_settings_broken_json_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "conspect.json"
    path.write_text("{ это не json", encoding="utf-8")

    settings = load_conspect_settings(path)

    assert settings.chunk_chars == ConspectSettings().chunk_chars


def test_settings_overlap_never_exceeds_chunk(tmp_path: Path) -> None:
    path = tmp_path / "conspect.json"
    path.write_text(json.dumps({"chunkChars": 400, "chunkOverlap": 900}), encoding="utf-8")

    settings = load_conspect_settings(path)

    assert settings.chunk_overlap < settings.chunk_chars


def test_vault_from_mcp_config(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "obsidian": {
                        "enabled": True,
                        "env": {"SEEKSTONE_VAULT": "C:\\Users\\Вы\\Documents\\ZERE Notes"},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert vault_from_mcp_config(path) == "C:\\Users\\Вы\\Documents\\ZERE Notes"


def test_vault_from_mcp_config_absent_or_broken(tmp_path: Path) -> None:
    assert vault_from_mcp_config(tmp_path / "нет.json") == ""

    broken = tmp_path / "mcp.json"
    broken.write_text("[1, 2, 3]", encoding="utf-8")

    assert vault_from_mcp_config(broken) == ""


def test_resolve_vault_prefers_own_setting(tmp_path: Path) -> None:
    mcp = tmp_path / "mcp.json"
    mcp.write_text(
        json.dumps({"servers": {"obsidian": {"env": {"SEEKSTONE_VAULT": "из-mcp"}}}}),
        encoding="utf-8",
    )
    own = ConspectSettings(vault="из-conspect")

    assert resolve_vault(own, mcp_config_path=mcp) == "из-conspect"
    assert resolve_vault(ConspectSettings(), mcp_config_path=mcp) == "из-mcp"


# ── Чанкование ──────────────────────────────────────────────────────


def test_chunk_empty_text_gives_no_parts() -> None:
    assert chunking.chunk_text("", 300, 50) == []
    assert chunking.chunk_text("   \n\n  ", 300, 50) == []
    assert chunking.chunk_text("текст", 0, 0) == []


def test_chunk_respects_limit_on_paragraphs(settings: ConspectSettings) -> None:
    chunks = chunking.chunk_text(_long_text(), settings.chunk_chars, settings.chunk_overlap)

    assert len(chunks) > 1
    assert max(len(chunk) for chunk in chunks) <= settings.chunk_chars + settings.chunk_overlap


def test_chunk_splits_long_paragraph_without_paragraph_breaks() -> None:
    sentence = "Это довольно длинное предложение про нейросети и обучение. "
    chunks = chunking.chunk_text(sentence * 40, 400, 0)

    assert len(chunks) > 1
    assert all(len(chunk) <= 400 for chunk in chunks)


def test_chunk_overlap_repeats_tail_of_previous_part(settings: ConspectSettings) -> None:
    chunks = chunking.chunk_text(_long_text(), settings.chunk_chars, settings.chunk_overlap)

    assert len(chunks) >= 2
    tail = chunks[0][-settings.chunk_overlap // 2 :].strip()

    assert tail and tail.split()[0] in chunks[1]


def test_split_sentences_does_not_break_numbers() -> None:
    parts = chunking.split_sentences("Версия 3.5 вышла 12.05.2026. Затем стало лучше.")

    assert parts == ["Версия 3.5 вышла 12.05.2026.", "Затем стало лучше."]


def test_estimate_tokens_and_stats() -> None:
    assert chunking.estimate_tokens("") == 0
    assert chunking.estimate_tokens("абвгд") >= 2

    stats = chunking.chunk_stats(["абвгд", "ежзик"])

    assert stats["parts"] == 2
    assert stats["chars"] == 10
    assert stats["tokens"] >= 4
    assert stats["maxPartTokens"] >= stats["tokens"] // 2


# ── Извлечение текста ───────────────────────────────────────────────


def test_html_to_text_drops_service_tags() -> None:
    html = (
        "<html><head><title>Лекция</title><style>p{}</style></head>"
        "<body><nav>меню сайта</nav><h1>Заголовок</h1><p>Первый абзац.</p>"
        "<script>alert(1)</script><p>Второй абзац.</p><footer>подвал</footer></body></html>"
    )
    result = text_module.html_to_text(html)

    assert "Заголовок" in result
    assert "Первый абзац." in result
    assert "alert" not in result
    assert "меню сайта" not in result
    assert "подвал" not in result


def test_html_title_extracted() -> None:
    assert text_module.html_title("<html><title> Лекция про LoRA </title></html>") == "Лекция про LoRA"
    assert text_module.html_title("мусор", fallback="запас") == "запас"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://ya.ru", True),
        ("http://example.com/a", True),
        ("example.com/article", True),
        ("ya.ru", True),
        ("www.habr.com", True),
        ("C:\\лекция.md", False),
        ("лекция.md", False),
        ("book.pdf", False),
        ("/home/user/note.md", False),
        ("привет мир", False),
        ("README", False),
        ("", False),
    ],
)
def test_is_url_table(value: str, expected: bool) -> None:
    assert is_url(value) is expected


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("192.168.1.10", True),
        ("10.0.0.5", True),
        ("::1", True),
        ("router", True),
        ("example.com", False),
        ("habr.com", False),
    ],
)
def test_is_private_host_table(host: str, expected: bool) -> None:
    assert is_private_host(host) is expected


def test_read_file_source_markdown(tmp_path: Path) -> None:
    path = tmp_path / "лекция.md"
    path.write_text("# Лекция\n\nПро нейросети.", encoding="utf-8")

    source = read_source(str(path))

    assert source.kind == "file"
    assert source.title == "лекция"
    assert "Про нейросети" in source.text
    assert source.origin == str(path)


def test_read_file_source_missing(tmp_path: Path) -> None:
    with pytest.raises(ConspectError) as error:
        read_source(str(tmp_path / "нет.md"))

    assert error.value.code == "CONSPECT_SOURCE_NOT_FOUND"


def test_read_file_source_binary_refused(tmp_path: Path) -> None:
    path = tmp_path / "данные.exe"
    path.write_bytes(b"\x00\x01\x02" + "бинарные данные".encode("utf-8"))

    with pytest.raises(ConspectError) as error:
        read_source(str(path))

    assert error.value.code == "CONSPECT_SOURCE_UNSUPPORTED"


def test_read_file_source_empty(tmp_path: Path) -> None:
    path = tmp_path / "пусто.txt"
    path.write_text("   \n\n", encoding="utf-8")

    with pytest.raises(ConspectError) as error:
        read_source(str(path))

    assert error.value.code == "CONSPECT_SOURCE_EMPTY"


def test_read_file_source_too_large(tmp_path: Path) -> None:
    path = tmp_path / "большой.txt"
    path.write_text("а" * 500, encoding="utf-8")

    with pytest.raises(ConspectError) as error:
        read_source(str(path), max_chars=100)

    assert error.value.code == "CONSPECT_SOURCE_TOO_LARGE"


def test_read_pdf_without_parser_explains_how_to_fix(tmp_path: Path) -> None:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("pypdf установлен — ветка «нет парсера» недоступна")

    path = tmp_path / "книга.pdf"
    path.write_bytes(b"%PDF-1.4 " + "сломанный файл".encode("utf-8"))

    with pytest.raises(ConspectError) as error:
        read_source(str(path))

    assert error.value.code == "CONSPECT_SOURCE_UNSUPPORTED"
    assert "pypdf" in error.value.message


def test_fetch_url_source_reads_page_and_title() -> None:
    session = FakeSession().route(
        "GET",
        "example.com/article",
        FakeResponse(
            200,
            text=(
                "<html><head><title>Статья про LoRA</title></head><body>"
                "<p>Первый абзац статьи.</p><script>x=1</script>"
                "<p>Второй абзац.</p></body></html>"
            ),
        ),
    )

    source = text_module.fetch_url_source("https://example.com/article", session=session)

    assert source.kind == "url"
    assert source.title == "Статья про LoRA"
    assert "Первый абзац статьи." in source.text
    assert "x=1" not in source.text


def test_fetch_url_source_reports_http_error() -> None:
    session = FakeSession().route("GET", "example.com", FakeResponse(404, text="нет"))

    with pytest.raises(ConspectError) as error:
        text_module.fetch_url_source("https://example.com/x", session=session)

    assert error.value.code == "CONSPECT_DOWNLOAD_FAILED"
    assert "404" in error.value.message


def test_fetch_url_source_reports_network_error() -> None:
    with pytest.raises(ConspectError) as error:
        text_module.fetch_url_source("https://example.com/x", session=FakeSession())

    assert error.value.code == "CONSPECT_DOWNLOAD_FAILED"


def test_fetch_url_source_refuses_private_host() -> None:
    with pytest.raises(ConspectError) as error:
        text_module.fetch_url_source("http://127.0.0.1:8080/admin")

    assert error.value.code == "CONSPECT_URL_FORBIDDEN"


# ── Контракт заметки ────────────────────────────────────────────────


def test_yaml_scalar_quotes_only_when_needed() -> None:
    assert contract.yaml_scalar("простое") == "простое"
    assert contract.yaml_scalar("Конспект: лекция").startswith('"')
    assert contract.yaml_scalar("- начало").startswith('"')
    assert contract.yaml_scalar("true").startswith('"')
    assert contract.yaml_scalar("") == '""'


def test_frontmatter_has_title_source_and_tags() -> None:
    block = contract.frontmatter(
        title="Конспект: Лекция",
        origin="https://example.com",
        kind="url",
        tags=("конспект", "обучение"),
        created="2026-10-14",
        parts=3,
    )

    assert block.startswith("---\n")
    assert block.rstrip().endswith("---")
    assert "sourceType: url" in block
    assert "created: 2026-10-14" in block
    assert "parts: 3" in block
    assert "  - конспект" in block
    assert "  - обучение" in block


def test_build_note_marks_truncation_and_failures() -> None:
    note = contract.build_note(
        body="## Суть\nО чём-то.",
        title="Конспект: Текст",
        origin="файл.md",
        kind="file",
        tags=("конспект",),
        created="2026-10-14",
        parts=10,
        parts_used=4,
        parts_failed=2,
        truncated=True,
        model="локально · T-lite",
        seconds=12.4,
    )

    assert note.startswith("---\n")
    assert "# Конспект: Текст" in note
    assert "> Файл: файл.md" in note
    assert "Частей материала: 4 из 10" in note
    assert "частей без ответа модели: 2" in note
    assert "материал был обрезан" in note
    assert "локально · T-lite" in note


def test_build_note_replaces_empty_body() -> None:
    note = contract.build_note(
        body="   ",
        title="Конспект",
        origin="",
        kind="text",
        tags=(),
        created="2026-10-14",
        parts=1,
        parts_used=1,
    )

    assert "модель не вернула текст" in note


def test_slugify_keeps_cyrillic_and_drops_illegal() -> None:
    assert contract.slugify("Конспект: Лекция про LoRA") == "Конспект-Лекция-про-LoRA"
    assert contract.slugify('плохое<>:"|?*имя') == "плохое-имя"
    assert contract.slugify("   ") == "конспект"
    assert len(contract.slugify("я" * 200)) == 80


def test_note_title_prefixes_once() -> None:
    assert contract.note_title("Лекция про LoRA") == "Конспект: Лекция про LoRA"
    assert contract.note_title("Конспект: Лекция") == "Конспект: Лекция"
    assert contract.note_title("") == "Конспект"


def test_clean_model_text_removes_fence_and_tail() -> None:
    assert contract.clean_model_text("```markdown\n## Суть\nтекст\n```") == "## Суть\nтекст"
    assert contract.clean_model_text("## Суть\nтекст\n\nНадеюсь, это поможет!") == "## Суть\nтекст"


# ── Писатель заметок ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "C:\\Windows\\System32\\evil.md",
        "/etc/passwd.md",
        "..\\снаружи.md",
        "../../снаружи.md",
        "",
    ],
)
def test_safe_relative_path_rejects_dangerous_paths(value: str) -> None:
    with pytest.raises(ConspectError) as error:
        safe_relative_path(value)

    assert error.value.code == "CONSPECT_WRITE_FAILED"


def test_safe_relative_path_cleans_illegal_characters() -> None:
    path = safe_relative_path('Конспекты/2026-10/имя<>:"|?*.md')

    assert path.as_posix() == "Конспекты/2026-10/имя-.md"


def test_writer_writes_note_and_never_overwrites(writer: VaultWriter) -> None:
    first = writer.write("Конспекты/2026-10/Лекция.md", "первый", title="Лекция")
    second = writer.write("Конспекты/2026-10/Лекция.md", "второй", title="Лекция")

    assert first.relative == "Конспекты/2026-10/Лекция.md"
    assert second.relative == "Конспекты/2026-10/Лекция-2.md"
    assert first.absolute.read_text(encoding="utf-8") == "первый"
    assert second.absolute.read_text(encoding="utf-8") == "второй"


def test_writer_restricts_writes_to_allowed_folder(vault_root: Path) -> None:
    writer = VaultWriter(vault_root, folder="Конспекты")

    with pytest.raises(ConspectError) as error:
        writer.write("Личное/секрет.md", "текст")

    assert error.value.code == "CONSPECT_WRITE_FAILED"


def test_writer_honours_write_paths(vault_root: Path) -> None:
    writer = VaultWriter(vault_root, folder="Конспекты", write_paths=("Конспекты", "Книги"))
    note = writer.write("Книги/2026-10/Книга.md", "текст")

    assert note.relative == "Книги/2026-10/Книга.md"


def test_writer_requires_existing_vault(tmp_path: Path) -> None:
    writer = VaultWriter(tmp_path / "нет-такого-хранилища", folder="Конспекты")

    with pytest.raises(ConspectError) as error:
        writer.check()

    assert error.value.code == "CONSPECT_VAULT_NOT_CONFIGURED"


def test_writer_note_path_uses_month_folder(writer: VaultWriter) -> None:
    assert writer.note_path("Конспект: Лекция", "2026-10-14").as_posix() == (
        "Конспекты/2026-10/Конспект-Лекция.md"
    )


def test_writer_creates_month_folder_and_leaves_no_temp_files(writer: VaultWriter) -> None:
    note = writer.write(writer.note_path("Конспект: Тест", "2026-10-14"), "текст")
    leftovers = list(writer.root.rglob("*.zere-tmp"))

    assert note.absolute.is_file()
    assert leftovers == []


def test_writer_lists_notes_newest_first(writer: VaultWriter) -> None:
    older = writer.write("Конспекты/2026-09/Старый.md", "старый", title="Старый")
    newer = writer.write("Конспекты/2026-10/Новый.md", "новый", title="Новый")

    import os
    import time

    past = time.time() - 3600
    os.utime(older.absolute, (past, past))

    notes = writer.list_notes(limit=5)

    assert [note.relative for note in notes] == [newer.relative, older.relative]


# ── Оркестратор ─────────────────────────────────────────────────────


def _source(text: str | None = None, **kwargs: object) -> SourceText:
    return SourceText(
        text=text if text is not None else _long_text(),
        title=kwargs.get("title", "Лекция про LoRA"),
        origin=kwargs.get("origin", "lecture.md"),
        kind=kwargs.get("kind", "file"),
    )


def test_conspect_maps_parts_and_reduces(settings: ConspectSettings, writer: VaultWriter) -> None:
    ai = FakeAI()
    summarizer = Summarizer(ai, settings, writer=writer, model="локально · тест")

    result = summarizer.conspect(_source())

    assert result.parts_total > 1
    assert len(ai.part_calls) == result.parts_total
    assert len(ai.summary_calls) == 1
    assert result.relative_path and result.relative_path.endswith(".md")
    written = Path(result.absolute_path).read_text(encoding="utf-8")
    assert "## Суть" in written
    assert "tags:" in written
    assert "  - обучение" in written


def test_conspect_single_part_skips_reduce(settings: ConspectSettings, writer: VaultWriter) -> None:
    ai = FakeAI()
    summarizer = Summarizer(ai, settings, writer=writer)

    result = summarizer.conspect(_source("Короткий текст про нейросети."))

    assert result.parts_total == 1
    assert ai.summary_calls == []


def test_conspect_truncates_by_max_chunks(settings: ConspectSettings, writer: VaultWriter) -> None:
    settings.max_chunks = 2
    ai = FakeAI()
    summarizer = Summarizer(ai, settings, writer=writer)

    result = summarizer.conspect(_source())

    assert result.parts_total == 2
    assert result.truncated is True
    assert any("обрезан" in warning for warning in result.warnings)
    assert "материал был обрезан" in result.markdown


def test_conspect_survives_single_part_failure(
    settings: ConspectSettings, writer: VaultWriter
) -> None:
    ai = FakeAI(failures=(1,))
    summarizer = Summarizer(ai, settings, writer=writer)

    result = summarizer.conspect(_source())

    assert result.parts_failed == 1
    assert result.parts_used == result.parts_total - 1
    assert result.written is True
    assert any("без ответа модели" in warning for warning in result.warnings)


def test_conspect_ignores_part_without_data(settings: ConspectSettings, writer: VaultWriter) -> None:
    ai = FakeAI(part="нет данных")
    summarizer = Summarizer(ai, settings, writer=writer)

    with pytest.raises(ConspectError) as error:
        summarizer.conspect(_source())

    # Все части ответили «нет данных» — заметку писать нечем.
    assert error.value.code == "CONSPECT_AI_FAILED"


def test_conspect_detects_ai_error_text(settings: ConspectSettings, writer: VaultWriter) -> None:
    """`AiService` отдаёт ошибку обычным текстом — он не должен стать конспектом."""
    ai = FakeAI(part=MESSAGE_NOT_CONFIGURED)
    summarizer = Summarizer(ai, settings, writer=writer)

    with pytest.raises(ConspectError) as error:
        summarizer.conspect(_source())

    assert error.value.code == "CONSPECT_AI_FAILED"
    assert MESSAGE_NOT_CONFIGURED in error.value.message


def test_conspect_reduce_failure_keeps_parts(
    settings: ConspectSettings, writer: VaultWriter
) -> None:
    part_count = len(chunking.chunk_text(_long_text(), settings.chunk_chars, settings.chunk_overlap))
    ai = FakeAI(failures=(part_count + 1,))
    summarizer = Summarizer(ai, settings, writer=writer)

    result = summarizer.conspect(_source())

    assert "## Заметки по части 1" in result.markdown
    assert any("сводка не удалась" in warning for warning in result.warnings)


def test_conspect_preflight_blocks_before_model(
    settings: ConspectSettings, writer: VaultWriter
) -> None:
    ai = FakeAI()
    summarizer = Summarizer(ai, settings, writer=writer, preflight=lambda: "ИИ не настроен")

    with pytest.raises(ConspectError) as error:
        summarizer.conspect(_source())

    assert error.value.code == "CONSPECT_AI_UNAVAILABLE"
    assert ai.calls == []


def test_conspect_checks_vault_before_model(settings: ConspectSettings, tmp_path: Path) -> None:
    writer = VaultWriter(tmp_path / "нет-хранилища", folder="Конспекты")
    ai = FakeAI()
    summarizer = Summarizer(ai, settings, writer=writer)

    with pytest.raises(ConspectError) as error:
        summarizer.conspect(_source())

    assert error.value.code == "CONSPECT_VAULT_NOT_CONFIGURED"
    assert ai.calls == []


def test_conspect_dry_run_writes_nothing(settings: ConspectSettings, writer: VaultWriter) -> None:
    summarizer = Summarizer(FakeAI(), settings, writer=writer)

    result = summarizer.conspect(_source(), write=False)

    assert result.written is False
    assert result.relative_path is None
    assert "## Суть" in result.markdown
    assert writer.list_notes() == []


def test_conspect_empty_source_refused(settings: ConspectSettings, writer: VaultWriter) -> None:
    summarizer = Summarizer(FakeAI(), settings, writer=writer)

    with pytest.raises(ConspectError) as error:
        summarizer.conspect(SourceText(text="   ", title="пусто", origin="x", kind="text"))

    assert error.value.code == "CONSPECT_SOURCE_EMPTY"


def test_plan_parts_counts_and_truncation(settings: ConspectSettings) -> None:
    planned, truncated = plan_parts(_long_text(), settings)

    assert planned > 1
    assert truncated is False

    settings.max_chunks = 1
    _, truncated = plan_parts(_long_text(), settings)

    assert truncated is True


def test_module_exports_are_importable() -> None:
    """Пакет как точка входа: импорт `zere.core.conspect` не тянет лишнего."""
    import zere.core.conspect as package

    assert package.Summarizer is Summarizer
    assert vault.VaultWriter is VaultWriter


# ── CLI (длинные материалы) ─────────────────────────────────────────


def test_cli_parses_arguments() -> None:
    from zere.core.conspect.cli import _parse_args

    options = _parse_args(
        ["лекция.md", "--folder", "Книги", "--tags", "нейросети, обучение", "--max-chunks", "5"]
    )

    assert options["source"] == "лекция.md"
    assert options["folder"] == "Книги"
    assert options["tags"] == ["нейросети", "обучение"]
    assert options["max_chunks"] == 5


def test_cli_rejects_unknown_key() -> None:
    from zere.core.conspect.cli import _parse_args

    with pytest.raises(ConspectError) as error:
        _parse_args(["--что-то"])

    assert error.value.code == "CONSPECT_BAD_ARGS"


def test_cli_help_and_empty_run(capsys: pytest.CaptureFixture[str]) -> None:
    from zere.core.conspect.cli import main

    assert main(["--help"]) == 0
    assert "python -m zere.core.conspect" in capsys.readouterr().out

    assert main([]) == 1


def test_cli_lists_conspects_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI читает то же хранилище, что и чат: путь берётся из config/mcp.json."""
    from zere import paths
    from zere.core.conspect.cli import main

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    vault_root = tmp_path / "vault"
    (vault_root / "Конспекты" / "2026-10").mkdir(parents=True)
    (vault_root / "Конспекты" / "2026-10" / "Конспект-Лекция.md").write_text(
        '---\ntitle: "Конспект: Лекция"\n---\n\nтекст', encoding="utf-8"
    )
    (config_dir / "mcp.json").write_text(
        json.dumps({"servers": {"obsidian": {"env": {"SEEKSTONE_VAULT": str(vault_root)}}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "config_path", lambda: config_dir / "config.json")

    assert main(["--list"]) == 0
    output = capsys.readouterr().out

    assert "Конспект: Лекция" in output
    assert "2026-10" in output
