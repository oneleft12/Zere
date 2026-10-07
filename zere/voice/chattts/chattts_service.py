"""Адаптер ChatTTS под контракт PiperService (замена Piper без правок вызывающих).

Контракт сохранён 1:1 — VoiceManager и остальные модули не замечают подмены:

    service.is_loaded           → bool   (движок готов; модель грузится лениво)
    service.current_voice       → str    (профиль голоса)
    service.initialize(voice)   → bool   (проверка окружения, БЕЗ загрузки модели)
    service.speak(text)         → str    (путь к WAV | "" — фолбэк на текст)
    service.set_voice(name)     → None
    service.set_inference_params(length_scale, sentence_silence)
    service.get_available_voices() → list[str]

Ленивость двойная: `initialize()` только проверяет наличие библиотек
(importlib.find_spec — без импорта), а сама модель попадает в память при первом
`speak()`. На старте ZERE ChatTTS не ест ни секунды, ни гигабайты RAM.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from zere import paths
from zere.core.logging.log_service import log_error
from zere.voice.chattts.chattts_manager import (
    DEFAULT_VOICE,
    ChatTTSManager,
    ChatTtsUnavailable,
    split_sentences,
    strip_emotions,
)


class ChatTtsService:
    """Сервис TTS на ChatTTS (порт PiperService с сохранением контракта)."""

    def __init__(self) -> None:
        # Папка вывода: ZERE.Voice/ChatTts (аналог ZERE.Voice/Piper).
        self._output_dir: Path = paths.chattts_dir()
        self._current_voice = DEFAULT_VOICE
        self._manager = ChatTTSManager(self._current_voice)

        # IsLoaded { get; private set; } — «движок доступен», а не «модель в RAM»
        self.is_loaded: bool = False

        # Параметры по умолчанию (паритет с VoiceConfig: 1.15 / 0.2).
        self._length_scale = 1.15
        self._sentence_silence = 0.2

    @property
    def current_voice(self) -> str:
        return self._current_voice

    @property
    def manager(self) -> ChatTTSManager:
        """Прямой доступ к менеджеру (панель/тесты/прогрев)."""
        return self._manager

    def initialize(self, voice_name: str | None = None) -> bool:
        """Проверяет окружение ChatTTS и фиксирует профиль голоса.

        Модель НЕ загружается: это делает первый `speak()` (ленивая загрузка).
        Отсутствие ChatTTS — не ошибка приложения: `is_loaded=False`, озвучка
        уходит в текстовый режим (то же поведение, что у Piper без piper.exe).
        """
        if voice_name:
            self._current_voice = voice_name

        self._manager.set_voice(self._current_voice)
        self._manager.set_inference_params(self._length_scale, self._sentence_silence)

        available, reason = ChatTTSManager.availability()

        self.is_loaded = available

        if available:
            print(f"[ChatTTS] {reason}. Профиль голоса: {self._current_voice}")
            self._cleanup_old_outputs()
        else:
            log_error("ChatTtsService", f"ChatTTS недоступен: {reason}")
            print(f"[ChatTTS] Движок недоступен: {reason}")

        return available

    def refresh(self) -> bool:
        """Перепроверяет окружение без загрузки модели (дешёвый find_spec).

        Зачем: ChatTTS можно поставить (или удалить) при работающем ZERE —
        например, через панель «Проверка зависимостей». Состояние, снятое на
        старте, устаревает, и панель отвечала 503 «Синтез речи недоступен»
        до перезапуска. Перепроверка снимает это требование.
        """
        if self.is_loaded:
            return True

        available, reason = ChatTTSManager.availability()
        self.is_loaded = available

        if available:
            print(f"[ChatTTS] Движок стал доступен: {reason}. Профиль: {self._current_voice}")
            self._cleanup_old_outputs()

        return available

    @property
    def unavailable_reason(self) -> str:
        """Почему движок недоступен (для панели/логов). Пусто, если доступен."""
        if self.is_loaded:
            return ""

        _available, reason = ChatTTSManager.availability()

        return reason

    def set_inference_params(
        self,
        length_scale: float = 1.15,
        sentence_silence: float = 0.2,
    ) -> None:
        """Темп речи и пауза после предложения (паритет SetInferenceParams)."""
        self._length_scale = length_scale
        self._sentence_silence = sentence_silence
        self._manager.set_inference_params(length_scale, sentence_silence)

    def speak(self, text: str) -> str:
        """Синтезирует текст в WAV-файл и возвращает путь (порт SpeakAsync).

        Пустая строка = синтез не удался: вызывающий код печатает текст
        (ROADMAP 1.1, «TTS не отвечает → текстовый вывод»).
        """
        # Убираем эмодзи, смайлики и «ролевые» пометки — TTS не должен их читать
        text = strip_emotions(text)

        if not text or text.isspace():
            return ""

        # Движок мог появиться уже после старта: перепроверяем перед отказом.
        if not self.refresh():
            return ""

        if not split_sentences(text):
            return ""

        output_file = str(
            self._output_dir / f"output_{datetime.now():%Y%m%d_%H%M%S_%f}.wav"
        )

        try:
            # Модель грузится здесь и только здесь (первый вызов — ленивый).
            return self._manager.synthesize_sentences(text, output_file)
        except ChatTtsUnavailable as ex:
            # Библиотека отвалилась уже после initialize (например, сломан torch).
            self.is_loaded = False
            log_error("ChatTtsService", str(ex))
            print(f"[ChatTTS] Ошибка: {ex}")
            return ""
        except Exception as ex:  # noqa: BLE001 — озвучка не должна ронять цикл
            log_error("ChatTtsService", str(ex))
            print(f"[ChatTTS] Ошибка синтеза: {ex}")
            return ""

    def set_voice(self, voice_name: str) -> None:
        """Смена профиля голоса (порт SetVoice): модель НЕ перезагружается."""
        if not voice_name:
            return

        self._current_voice = voice_name
        self._manager.set_voice(voice_name)

    def get_available_voices(self) -> list[str]:
        """Доступные профили голоса (порт GetAvailableVoices)."""
        return self._manager.available_voices()

    @staticmethod
    def strip_emotions(text: str) -> str:
        """Порт PiperService.strip_emotions (оставлен для совместимости)."""
        return strip_emotions(text)

    def close(self) -> None:
        """Освобождение ресурсов (порт Dispose)."""
        self._manager.close()

    def _cleanup_old_outputs(self) -> None:
        """Удаляет output_*.wav старше часа (порт CleanupOldOutputs)."""
        try:
            cutoff = datetime.now().timestamp() - 3600

            for file_path in self._output_dir.glob("output_*.wav"):
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                except OSError:
                    # Ignore individual file deletion failures during cleanup
                    pass
        except Exception:  # noqa: BLE001 — уборка не критична
            pass


__all__ = ["ChatTtsService"]
