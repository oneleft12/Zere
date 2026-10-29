"""Настройка language: язык ответа ассистента (ru|en), а не только подпись.

Проверяется то, что раньше было декоративным: `config.language` читался,
печатался при старте и больше нигде не участвовал — ассистент всегда отвечал
по-русски, даже если в настройках выбран английский.
"""

from __future__ import annotations

from zere.core.ai.prompt_builder import PromptBuilder
from zere.core.configuration.zere_config import ZereConfig
from zere.core.handlers.ai_handler import AIHandler


class FakeAI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float | None]] = []

    def generate(self, prompt: str, system_prompt: str, temperature=None) -> str:
        self.calls.append((prompt, system_prompt, temperature))
        return "ok"


class FakeContext:
    def build_memory(self) -> str:
        return "любит пиццу"

    def build_history(self) -> str:
        return "Вы: привет"


class NoPersonality:
    active_personality = None


def _handle(language: str) -> tuple[str, str]:
    fake = FakeAI()
    config = ZereConfig(language=language)
    handler = AIHandler(fake, FakeContext(), NoPersonality(), config=config)  # type: ignore[arg-type]
    handler.handle("привет")
    prompt, system_prompt, _ = fake.calls[0]
    return prompt, system_prompt


def test_russian_by_default() -> None:
    prompt, system_prompt = _handle("ru")

    assert "ЯЗЫК ОТВЕТА" in system_prompt
    assert "только на русском языке" in system_prompt
    assert "=== ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ ===" in prompt


def test_english_changes_rule_and_prompt_labels() -> None:
    prompt, system_prompt = _handle("en")

    assert "ANSWER LANGUAGE" in system_prompt
    assert "answer only in English" in system_prompt
    assert "Answer briefly and clearly in English." in system_prompt
    # Русские заголовки блоков тянули ответ обратно в русский.
    assert "=== USER MEMORY ===" in prompt
    assert "=== USER MESSAGE ===" in prompt
    assert "ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ" not in prompt


def test_unknown_language_falls_back_to_russian() -> None:
    _, system_prompt = _handle("de")

    assert "ЯЗЫК ОТВЕТА" in system_prompt
    assert "ANSWER LANGUAGE" not in system_prompt


def test_prompt_builder_defaults_to_russian() -> None:
    prompt = PromptBuilder().memory("факт").user_message("привет").build()

    assert "=== ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ ===" in prompt
    assert "=== ОТВЕТ АССИСТЕНТА ===" in prompt


def test_prompt_builder_language_is_independent() -> None:
    prompt = PromptBuilder(language="en").history("hi").user_message("hello").build()

    assert "=== LAST DIALOG ===" in prompt
    assert "=== USER MESSAGE ===" in prompt
    assert "=== ASSISTANT ANSWER ===" in prompt


def test_config_roundtrip_keeps_language(tmp_path, monkeypatch) -> None:
    """language сохраняется в config.json и читается обратно (паритет с панелью)."""
    from zere import paths

    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path)
    ZereConfig(language="en").save()

    assert ZereConfig.load().language == "en"
