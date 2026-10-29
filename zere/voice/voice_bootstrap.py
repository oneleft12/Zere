"""Старт голосовой подсистемы ZERE: отдельная политика «что поднимать».

Модуль вынесен из `main.py` намеренно: условия старта — это поведение, которое
ломается незаметно (регрессия: при `voiceEnabled=false` панель отвечала 503
«Синтез речи недоступен: Silero доступен (ленивая загрузка…)»), поэтому его
проверяют тесты, а не глазами в консоли.
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = ["bootstrap_voice"]


def bootstrap_voice(
    voice_manager: Any,
    *,
    voice_enabled: bool,
    personality_style: str | None = None,
    start_stt_preload: Callable[[], None] | None = None,
) -> bool:
    """Инициализирует голосовой менеджер; STT греет только при голосовом выводе.

    Доступность TTS проверяется ВСЕГДА, даже когда голосовой вывод выключен:
    панель умеет тестировать синтез («Озвучить» на экране «Голос»), а
    `VoiceManager.initialize()` только проверяет окружение и не грузит модель —
    веса поднимаются при первом синтезе. Без этого панель отвечала 503
    «Синтез речи недоступен: Silero доступен (ленивая загрузка…)»: движок
    установлен, а кнопка теста не работает.

    Предзагрузка STT остаётся привязана к `voice_enabled`: она качает модель
    (GigaAM ~163 МБ) и нужна только голосовому вводу.

    Возвращает результат `initialize()` — готов ли TTS к синтезу.
    """
    tts_ready = voice_manager.initialize(personality_style)

    if voice_enabled and start_stt_preload is not None:
        start_stt_preload()

    return tts_ready
