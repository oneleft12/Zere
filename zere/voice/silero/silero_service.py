"""Адаптер Silero TTS под общий контракт TTS (PiperService).

Контракт сохранён 1:1 — VoiceManager и остальной код не замечают подмены
движка (маршрутизация живёт в VoiceManager и зависит только от `ttsEngine`):

    service.is_loaded           → bool   (движок готов; модель грузится лениво)
    service.current_voice       → str    (имя голоса Silero)
    service.initialize(voice)   → bool   (проверка окружения, БЕЗ загрузки модели)
    service.speak(text)         → str    (путь к WAV | "" — фолбэк на текст)
    service.set_voice(name)     → None
    service.set_inference_params(length_scale, sentence_silence)
    service.get_available_voices() → list[str]

Ленивость двойная: `initialize()` только проверяет наличие torch/soundfile
(importlib.find_spec — без импорта), а модель (~145 МБ) скачивается и попадает
в память при первом `speak()`. На старте ZERE Silero не ест ни секунды, ни
гигабайты RAM.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from zere import paths
from zere.core.logging.log_service import log_error
from zere.voice.silero.silero_manager import (
    DEFAULT_VOICE,
    SileroManager,
    SileroUnavailable,
    split_sentences,
    strip_emotions,
)


class SileroTtsService:
    """Сервис TTS на Silero v5 (общий контракт TTS)."""

    def __init__(self) -> None:
        # Папка вывода: ZERE.Voice/Silero (там же лежит сама модель).
        self._output_dir: Path = paths.silero_dir()
        self._current_voice = DEFAULT_VOICE
        self._manager = SileroManager(self._current_voice)

        # is_loaded — «движок доступен», а не «модель в RAM».
        self.is_loaded: bool = False

        # Параметры по умолчанию (паритет с VoiceConfig: 1.15 / 0.2).
        # Темп Silero не поддерживает — принимается ради общего контракта.
        self._length_scale = 1.15
        self._sentence_silence = 0.2

    @property
    def current_voice(self) -> str:
        return self._current_voice

    @property
    def manager(self) -> SileroManager:
        """Прямой доступ к менеджеру (панель/тесты/прогрев)."""
        return self._manager

    def initialize(self, voice_name: str | None = None) -> bool:
        """Проверяет окружение Silero и фиксирует голос.

        Модель НЕ загружается: её скачает и поднимет первый `speak()`.
        Отсутствие torch/Silero — не ошибка приложения: `is_loaded=False`,
        озвучка уходит в текстовый режим.
        """
        if voice_name:
            self._current_voice = voice_name

        self._manager.set_voice(self._current_voice)
        self._manager.set_inference_params(self._length_scale, self._sentence_silence)

        available, reason = SileroManager.availability()

        self.is_loaded = available

        # Голос мог быть неизвестным (старый профиль из конфига) —
        # менеджер уже подменил его дефолтным, синхронизируем отображаемое имя.
        self._current_voice = self._manager.current_voice

        if available:
            print(f"[Silero] {reason}. Голос: {self._current_voice}")
            self._cleanup_old_outputs()
        else:
            log_error("SileroTtsService", f"Silero недоступен: {reason}")
            print(f"[Silero] Движок недоступен: {reason}")

        return available

    def refresh(self) -> bool:
        """Перепроверяет окружение без загрузки модели (дешёвый find_spec).

        Зачем: torch можно поставить при работающем ZERE, и тогда озвучка
        начинает работать без перезапуска.
        """
        if self.is_loaded:
            return True

        available, reason = SileroManager.availability()
        self.is_loaded = available

        if available:
            print(f"[Silero] Движок стал доступен: {reason}. Голос: {self._current_voice}")
            self._cleanup_old_outputs()

        return available

    @property
    def unavailable_reason(self) -> str:
        """Почему движок недоступен (для панели/логов). Пусто, если доступен.

        Причину отдаём только при реальной проблеме: на успешной проверке
        `availability()` возвращает пояснение «Silero доступен…», и оно не
        должно попадать в 503 «Синтез речи недоступен».
        """
        if self.is_loaded:
            return ""

        available, reason = SileroManager.availability()

        return "" if available else reason

    @property
    def supports_speech_speed(self) -> bool:
        """Silero v5 не умеет менять темп речи (честная возможность панели)."""
        return False

    def set_inference_params(
        self,
        length_scale: float = 1.15,
        sentence_silence: float = 0.2,
    ) -> None:
        """Пауза после предложения (темп у Silero фиксирован)."""
        self._length_scale = length_scale
        self._sentence_silence = sentence_silence
        self._manager.set_inference_params(length_scale, sentence_silence)

    def speak(self, text: str) -> str:
        """Синтезирует текст в WAV-файл и возвращает путь.

        Пустая строка = синтез не удался: вызывающий код печатает текст
        (ROADMAP 1.1, «TTS не отвечает → текстовый вывод»).
        """
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
            # Модель скачивается и грузится здесь и только здесь (первый вызов).
            return self._manager.synthesize_sentences(text, output_file)
        except SileroUnavailable as ex:
            # Окружение отвалилось уже после initialize (например, битый файл).
            self.is_loaded = False
            log_error("SileroTtsService", str(ex))
            print(f"[Silero] Ошибка: {ex}")
            return ""
        except Exception as ex:  # noqa: BLE001 — озвучка не должна ронять цикл
            log_error("SileroTtsService", str(ex))
            print(f"[Silero] Ошибка синтеза: {ex}")
            return ""

    def set_voice(self, voice_name: str) -> None:
        """Смена голоса (модель НЕ перезагружается)."""
        if not voice_name:
            return

        self._current_voice = voice_name
        self._manager.set_voice(voice_name)
        self._current_voice = self._manager.current_voice

    def get_available_voices(self) -> list[str]:
        """Доступные голоса Silero."""
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
                    # Отдельный файл мог исчезнуть — уборка не критична.
                    pass
        except Exception:  # noqa: BLE001 — уборка не критична
            pass


__all__ = ["SileroTtsService"]
