"""Тесты обработчика конспектора: разбор фраз, потолок чата, ответы.

Главное, что здесь проверяется, — обработчик **не отбирает команды** у
остальных: конвейер спрашивает `can_handle` на каждом сообщении, и жадный
разбор фразы сломал бы привычные команды. Второе — на любой сбой (нет
модели, нет файла, нет хранилища, исключение) приходит короткий русский
ответ, а не исключение наружу: этот текст читает пользователь и озвучка.

Модель фейковая (`FakeAI`), хранилище — временный каталог: сеть и живой
Ollama тестам не нужны. Запуск: `pytest tests/test_conspect_handler.py -q`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fake_http import FakeResponse, FakeSession
from zere.core.conspect.config import ConspectSettings
from zere.core.conspect.vault import VaultWriter
from zere.core.handlers.conspect_handler import ConspectHandler

SUMMARY = "## Суть\nПро нейросети.\n## Ключевые тезисы\n- раз\n- два"
PART = "- тезис по части"

#: Фразы, которые конспектор трогать не должен.
FOREIGN_PHRASES = (
    "привет",
    "открой браузер",
    "заметки найди покупки",
    "заметки создай Идеи.md: текст",
    "какие процессы запущены",
    "громкость 30",
    "конспекты заметок",
    "прочитай файл лекция.md",
)


class FakeAI:
    """Фейковая модель: заметки на промпт части, конспект на промпт сводки."""

    def __init__(self, *, status: object = None, boom: bool = False) -> None:
        self.status_state = status
        self.boom = boom
        self.calls = 0

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.calls += 1

        if self.boom:
            raise RuntimeError("Ollama недоступна")

        return SUMMARY if "Собери из них один конспект" in prompt else PART

    def status(self) -> object:
        return self.status_state


@pytest.fixture()
def settings() -> ConspectSettings:
    return ConspectSettings(chunk_chars=300, chunk_overlap=50, tags=("конспект",))


@pytest.fixture()
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "Конспекты").mkdir(parents=True)

    return root


@pytest.fixture()
def handler(vault_root: Path, settings: ConspectSettings) -> ConspectHandler:
    writer = VaultWriter(vault_root, folder="Конспекты")

    return ConspectHandler(FakeAI(), settings, writer=writer)


# ── Разбор фраз ─────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase", FOREIGN_PHRASES)
def test_foreign_commands_are_not_stolen(handler: ConspectHandler, phrase: str) -> None:
    assert handler.can_handle(phrase) is False


@pytest.mark.parametrize(
    "phrase",
    [
        "законспектируй https://example.com/article",
        "законспектируй lecture.md",
        "законспектируй C:\\Лекции\\лекция.md",
        "законспектируй, пожалуйста, lecture.md",
        "сделай конспект из lecture.md",
        "конспект файла lecture.md",
        "конспект: https://example.com",
        "законспектируй",
        "конспекты",
    ],
)
def test_conspect_phrases_are_recognized(handler: ConspectHandler, phrase: str) -> None:
    assert handler.can_handle(phrase) is True


def test_handler_disabled_does_nothing(settings: ConspectSettings, vault_root: Path) -> None:
    settings.enabled = False
    handler = ConspectHandler(FakeAI(), settings, writer=VaultWriter(vault_root))

    assert handler.can_handle("законспектируй lecture.md") is False
    assert handler.handle("законспектируй lecture.md") is None


def test_handler_explains_usage_without_source(handler: ConspectHandler) -> None:
    answer = handler.handle("законспектируй")

    assert "Скажите" in answer
    assert "конспекты" in answer


def test_handler_does_not_understand_short_noise(handler: ConspectHandler) -> None:
    answer = handler.handle("законспектируй бла бла")

    assert "Не понял" in answer


# ── Работа с хранилищем ─────────────────────────────────────────────


def test_handler_lists_empty_vault(handler: ConspectHandler) -> None:
    answer = handler.handle("конспекты")

    assert "Конспектов пока нет" in answer
    assert "Конспекты" in answer


def test_handler_lists_saved_conspects(handler: ConspectHandler, vault_root: Path) -> None:
    writer = VaultWriter(vault_root, folder="Конспекты")
    writer.write(
        "Конспекты/2026-10/Конспект-Лекция.md",
        '---\ntitle: "Конспект: Лекция"\ntags:\n  - конспект\n---\n\n# Конспект: Лекция\n',
        title="Конспект: Лекция",
    )
    # Чужая заметка без frontmatter: показываем имя файла, а не пустоту.
    writer.write("Конспекты/2026-10/Заметка.md", "просто текст")

    answer = handler.handle("конспекты")

    assert "Конспект: Лекция" in answer
    assert "Конспекты/2026-10/Конспект-Лекция.md" in answer
    assert "Заметка" in answer


def test_handler_conspects_local_file(handler: ConspectHandler, tmp_path: Path) -> None:
    lecture = tmp_path / "лекция.md"
    lecture.write_text("Нейросети и обучение. " * 40, encoding="utf-8")

    answer = handler.handle(f"законспектируй {lecture}")

    assert "Готово" in answer
    assert "Конспекты/" in answer
    assert list(Path(handler.writer.root).rglob("*.md"))


def test_handler_conspects_inline_text(handler: ConspectHandler) -> None:
    material = "Длинный текст про нейросети. " * 20

    answer = handler.handle(f"законспектируй: {material}")

    assert "Готово" in answer
    notes = list(Path(handler.writer.root).rglob("*.md"))
    assert notes
    assert notes[0].read_text(encoding="utf-8").startswith("---\n")


def test_handler_reports_missing_file(handler: ConspectHandler, tmp_path: Path) -> None:
    answer = handler.handle(f"законспектируй {tmp_path / 'нет-такого.md'}")

    assert "Файл не найден" in answer


def test_handler_uses_fake_http_for_url(settings: ConspectSettings, vault_root: Path) -> None:
    session = FakeSession().route(
        "GET",
        "example.com/article",
        FakeResponse(200, text="<html><title>Статья</title><body><p>Текст статьи про LoRA.</p></body></html>"),
    )
    handler = ConspectHandler(
        FakeAI(), settings, writer=VaultWriter(vault_root, folder="Конспекты"), session=session
    )

    answer = handler.handle("законспектируй https://example.com/article")

    assert "Готово" in answer
    assert Path(handler.writer.root).rglob("*.md")


# ── Потолок чата и сбои ─────────────────────────────────────────────


def test_handler_refuses_long_material_with_cli_hint(
    settings: ConspectSettings, vault_root: Path
) -> None:
    settings.interactive_max_chars = 1000
    handler = ConspectHandler(FakeAI(), settings, writer=VaultWriter(vault_root, folder="Конспекты"))

    answer = handler.handle("законспектируй: " + "Очень длинный материал. " * 200)

    assert "Материал большой" in answer
    assert "python -m zere.core.conspect" in answer
    assert not list(Path(handler.writer.root).rglob("*.md"))


def test_handler_stops_when_ai_not_configured(settings: ConspectSettings, vault_root: Path) -> None:
    ai = FakeAI(status={"ready": False, "message": "Подключите API-ключ или локальную модель"})
    handler = ConspectHandler(ai, settings, writer=VaultWriter(vault_root, folder="Конспекты"))

    answer = handler.handle("законспектируй: " + "Текст про нейросети. " * 30)

    assert "Подключите API-ключ" in answer
    assert ai.calls == 0


def test_handler_survives_model_exception(settings: ConspectSettings, vault_root: Path) -> None:
    handler = ConspectHandler(
        FakeAI(boom=True), settings, writer=VaultWriter(vault_root, folder="Конспекты")
    )

    answer = handler.handle("законспектируй: " + "Текст про нейросети. " * 30)

    # Сбой модели объясняется причиной, а не трассировкой и не исключением.
    assert "Модель не дала ни одного ответа" in answer
    assert "Ollama недоступна" in answer


def test_handler_requires_vault(tmp_path: Path, settings: ConspectSettings) -> None:
    handler = ConspectHandler(
        FakeAI(), settings, writer=VaultWriter(tmp_path / "нет-хранилища", folder="Конспекты")
    )

    answer = handler.handle("законспектируй: " + "Текст про нейросети. " * 30)

    assert "Хранилище Obsidian не найдено" in answer
