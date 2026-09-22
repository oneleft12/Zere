"""Порт JARVIS.Core/Handlers/AIHandler.cs."""

from __future__ import annotations

import enum

from jarvis.ai.ollama_client import OllamaClient
from jarvis.core.ai.context_builder import ContextBuilder
from jarvis.core.ai.prompt_builder import PromptBuilder
from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.core.plugins.plugin_manager import PluginManager


class AIHandler(IJarvisHandler):
    _ASSISTANT_NAME = "JARVIS"  # private const string AssistantName = "JARVIS"

    def __init__(self, ai: OllamaClient, context: ContextBuilder, plugin_manager: PluginManager) -> None:
        self._ai = ai
        self._context = context
        self._plugin_manager = plugin_manager

    def can_handle(self, message: str) -> bool:
        return True

    def handle(self, message: str) -> str:
        personality = self._plugin_manager.active_personality
        system_prompt = self._get_system_prompt()

        prompt = (
            PromptBuilder()
            .system_prompt(system_prompt)
            .memory(self._context.build_memory())
            .history(self._context.build_history())
            .user_message(message)
            .build()
        )

        temperature = personality.temperature if personality is not None else None

        return self._ai.generate(prompt, system_prompt, temperature)

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
            )

        return (
            f"Ты — {self._ASSISTANT_NAME}.\n"
            "Ты персональный AI-ассистент для Windows.\n"
            "Отвечай кратко и понятно на русском языке."
        )
