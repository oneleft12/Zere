"""Порт ZERE.Core/Handlers/AIHandler.cs."""

from __future__ import annotations

import enum
from typing import Optional

from zere.ai.ollama_client import OllamaClient
from zere.core.ai.context_builder import ContextBuilder
from zere.core.ai.prompt_builder import PromptBuilder
from zere.core.configuration.zere_config import ZereConfig
from zere.core.context.runtime_context import RuntimeContext
from zere.core.handlers.i_zere_handler import IZereHandler
from zere.core.plugins.plugin_manager import PluginManager


class AIHandler(IZereHandler):
    _ASSISTANT_NAME = "ZERE"  # private const string AssistantName = "ZERE"

    _VOICE_INSTRUCTIONS = {
        "ru": (
            "\n\nГОЛОСОВОЙ РЕЖИМ: ответ будет произнесён вслух. Максимум 1–2 коротких "
            "предложения. Без списков, кода, markdown и пояснений."
        ),
        "en": (
            "\n\nVOICE MODE: the answer will be spoken aloud. At most 1–2 short "
            "sentences. No lists, code, markdown or explanations."
        ),
    }

    # Язык ответа добавляется к ЛЮБОМУ системному промпту (в том числе к
    # промпту активной личности): раньше правило было только в SystemPrompt.Zere,
    # а при включённой личности (по умолчанию Friendly) оно вообще не попадало
    # в запрос — малые модели уходили в английский/китайский.
    #: Язык ответа — из config/config.json (ключ language, ru|en). Раньше
    #: настройка ни на что не влияла: правило было жёстко русским, а смена
    #: языка в панели не меняла ни ответ, ни промпт.
    _LANGUAGE_RULES = {
        "ru": (
            "\n\nЯЗЫК ОТВЕТА (главное правило):\n"
            "— отвечай только на русском языке;\n"
            "— не переключайся на английский или любой другой язык, даже если вопрос задан не по-русски или содержит иноязычные слова;\n"
            "— иноязычные слова допустимы только в именах программ, командах, путях и коде."
        ),
        "en": (
            "\n\nANSWER LANGUAGE (main rule):\n"
            "— answer only in English;\n"
            "— do not switch to Russian or any other language, even if the question "
            "is in another language or contains foreign words;\n"
            "— foreign words are allowed only in program names, commands, paths and code."
        ),
    }

    def __init__(
        self,
        ai: OllamaClient,
        context: ContextBuilder,
        plugin_manager: PluginManager,
        runtime: Optional[RuntimeContext] = None,
        config: Optional[ZereConfig] = None,
    ) -> None:
        self._ai = ai
        self._context = context
        self._plugin_manager = plugin_manager
        self._runtime = runtime
        self._config = config

    def can_handle(self, message: str) -> bool:
        return True

    def handle(self, message: str) -> str:
        personality = self._plugin_manager.active_personality
        system_prompt = self._get_system_prompt()

        # Этап 1 (анализ S5): голосовой режим → короткий ответ и жёсткий
        # лимит токенов, иначе TTS проговаривает простыни десятки секунд.
        max_tokens: Optional[int] = None
        if self._runtime is not None and self._runtime.voice_mode:
            system_prompt += self._VOICE_INSTRUCTIONS[self._language()]
            if self._config is not None and self._config.llm_max_tokens > 0:
                max_tokens = self._config.llm_max_tokens

        # P1-2: system-промпт в prompt НЕ встраивается — он уходит отдельным
        # полем system в OllamaClient, иначе модель получала его дважды.
        prompt = (
            PromptBuilder(language=self._language())
            .memory(self._context.build_memory())
            .history(self._context.build_history())
            .user_message(message)
            .build()
        )

        temperature = personality.temperature if personality is not None else None

        # Важно для тестов (_FakeAI): без голосового лимита вызов остаётся
        # трёхпозиционным, как и раньше.
        if max_tokens is None:
            return self._ai.generate(prompt, system_prompt, temperature)

        return self._ai.generate(prompt, system_prompt, temperature, max_tokens=max_tokens)

    def _language(self) -> str:
        """Язык ответа из конфига (ru|en); всё незнакомое — русский."""
        if self._config is None:
            return "ru"

        value = str(getattr(self._config, "language", "ru")).lower()
        return value if value in self._LANGUAGE_RULES else "ru"

    def _get_system_prompt(self) -> str:
        personality = self._plugin_manager.active_personality
        language = self._language()
        rule = self._LANGUAGE_RULES[language]

        intro = (
            f"Ты — {self._ASSISTANT_NAME}."
            if language == "ru"
            else f"You are {self._ASSISTANT_NAME}."
        )

        if personality is not None:
            style = personality.style
            style_name = style.name if isinstance(style, enum.Enum) else str(style)

            return (
                intro + "\n"
                "\n"
                f"{personality.system_prompt}\n"
                "\n"
                "Параметры генерации:\n"
                f"- Температура: {personality.temperature}\n"
                f"- Стиль: {style_name}"
                f"{rule}"
            )

        base = (
            "Ты персональный AI-ассистент для Windows.\n"
            "Отвечай кратко и понятно на русском языке."
            if language == "ru"
            else "You are a personal AI assistant for Windows.\n"
            "Answer briefly and clearly in English."
        )

        return intro + "\n" + base + rule
