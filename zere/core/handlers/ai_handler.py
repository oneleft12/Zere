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

    _VOICE_INSTRUCTION = (
        "\n\nГОЛОСОВОЙ РЕЖИМ: ответ будет произнесён вслух. Максимум 1–2 коротких "
        "предложения. Без списков, кода, markdown и пояснений."
    )

    # Язык ответа добавляется к ЛЮБОМУ системному промпту (в том числе к
    # промпту активной личности): раньше правило было только в SystemPrompt.Zere,
    # а при включённой личности (по умолчанию Friendly) оно вообще не попадало
    # в запрос — малые модели уходили в английский/китайский.
    _LANGUAGE_RULE = (
        "\n\nЯЗЫК ОТВЕТА (главное правило):\n"
        "— отвечай только на русском языке;\n"
        "— не переключайся на английский или любой другой язык, даже если вопрос задан не по-русски или содержит иноязычные слова;\n"
        "— иноязычные слова допустимы только в именах программ, командах, путях и коде."
    )

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
            system_prompt += self._VOICE_INSTRUCTION
            if self._config is not None and self._config.llm_max_tokens > 0:
                max_tokens = self._config.llm_max_tokens

        # P1-2: system-промпт в prompt НЕ встраивается — он уходит отдельным
        # полем system в OllamaClient, иначе модель получала его дважды.
        prompt = (
            PromptBuilder()
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

    def _get_system_prompt(self) -> str:
        personality = self._plugin_manager.active_personality

        if personality is not None:
            style = personality.style
            style_name = style.name if isinstance(style, enum.Enum) else str(style)

            return (
                f"Ты — {self._ASSISTANT_NAME}.\n"
                "\n"
                f"{personality.system_prompt}\n"
                "\n"
                "Параметры генерации:\n"
                f"- Температура: {personality.temperature}\n"
                f"- Стиль: {style_name}"
                f"{self._LANGUAGE_RULE}"
            )

        return (
            f"Ты — {self._ASSISTANT_NAME}.\n"
            "Ты персональный AI-ассистент для Windows.\n"
            "Отвечай кратко и понятно на русском языке."
            f"{self._LANGUAGE_RULE}"
        )
