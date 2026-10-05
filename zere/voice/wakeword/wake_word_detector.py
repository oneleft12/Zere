"""Детектор ключевого слова «Зере» (порт ZERE.Voice/WakeWord/WakeWordDetector.cs).

Использует непрерывную запись с круговым буфером и энергетический VAD.
Отправляет аудио в Whisper ТОЛЬКО при обнаружении речи — без лишних вызовов.
Сопоставление нечёткое (Levenshtein) — ловит «зера», «зерэ», «зире».
Отмена (CancellationToken в C#) — threading.Event.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime

from zere.voice.audio.continuous_audio_recorder import ContinuousAudioRecorder
from zere.voice.voice_config import VoiceConfig
from zere.voice.whisper.whisper_service import WhisperService


class WakeWordDetector:
    """Детектор ключевого слова «Зере» (порт WakeWordDetector.cs)."""

    # Ядра для нечёткого сравнения (расстояние Левенштейна).
    # Имя короткое, поэтому «зере/зера/зире» перекрывают искажения Whisper,
    # а порог по длине слова (см. _is_wake_word) держит ложные срабатывания
    # низкими: слово короче 4 букв в сравнение не попадает.
    FUZZY_CORES: tuple[str, ...] = (
        "зере", "зера", "зерэ", "зире", "zere",
    )

    # Настройки
    PRE_SPEECH_BUFFER_SECONDS = 1.5  # Буфер до начала речи
    MIN_SPEECH_SECONDS = 0.5         # Минимальная длительность речи
    MAX_SEGMENT_SECONDS = 9.0        # Макс. окно извлечения (буфер 10 сек)
    SCAN_INTERVAL_MS = 400           # Интервал проверки энергии

    # Таймаут транскрибации wake-сегмента (короткий, ≤9 с аудио): 15 с
    # достаточно даже на слабом CPU, зависание не блокирует петлю.
    WAKE_TRANSCRIBE_TIMEOUT_S = 15

    def __init__(self, config: VoiceConfig, whisper: WhisperService | None = None) -> None:
        """whisper — общий сервис STT (анализ S3): одна модель на процесс
        вместо второй копии в каждом новом детекторе; если не передан —
        создаётся свой (тогда детектор владеет им и освобождает в close()).
        """
        self._recorder = ContinuousAudioRecorder()
        self._whisper = whisper if whisper is not None else WhisperService()
        self._owns_whisper = whisper is None
        self._config = config

        # Точные варианты (проверка подстрокой)
        self._wake_word_variants: list[str] = [
            config.wake_word.lower(),
            "зере",
            "зера",
            "зерэ",
            "зире",
            "zere",
        ]

    @property
    def recorder(self) -> ContinuousAudioRecorder:
        """Получает ссылку на рекордер для записи команды после wake word."""
        return self._recorder

    @staticmethod
    def _is_cancelled(cancel_event: threading.Event | None) -> bool:
        """Аналог ct.IsCancellationRequested."""
        return cancel_event is not None and cancel_event.is_set()

    @staticmethod
    def _wait(seconds: float, cancel_event: threading.Event | None) -> bool:
        """Аналог await Task.Delay(..., ct): ждём либо до отмены.

        Возвращает True, если отмена сработала.
        """
        if cancel_event is None:
            time.sleep(seconds)
            return False
        return cancel_event.wait(seconds)

    def wait_for_wake_word(self, cancel_event: threading.Event | None = None) -> str:
        """Ожидает произнесения ключевого слова.
        Непрерывно записывает аудио, определяет речь по энергии,
        и отправляет в Whisper только сегменты с речью.
        Возвращает текст, если обнаружено, иначе "".
        """
        # Запускаем непрерывную запись (если уже идёт — не перезапускаем,
        # чтобы не терять калибровку VAD на каждом цикле)
        self._recorder.start_continuous_recording(buffer_seconds=10)

        completed = False

        try:
            while not self._is_cancelled(cancel_event):
                # Ждём появления речи
                while not self._recorder.is_speech_detected:
                    if self._is_cancelled(cancel_event) or self._wait(
                        self.SCAN_INTERVAL_MS / 1000.0, cancel_event
                    ):
                        break  # отмена (в C# — OperationCanceledException)

                if self._is_cancelled(cancel_event):
                    break

                # Речь обнаружена — ждём окончания (тишина после речи)
                speech_start_time = datetime.now()
                last_speech_time = datetime.now()

                while not self._is_cancelled(cancel_event):
                    if self._wait(0.2, cancel_event):
                        break

                    if self._recorder.is_speech_detected:
                        last_speech_time = datetime.now()

                    silence_duration = (datetime.now() - last_speech_time).total_seconds() * 1000
                    speech_duration = (datetime.now() - speech_start_time).total_seconds()

                    # Пауза окончания речи — из конфига (было жёсткие 1200 мс,
                    # анализ S4: каждый цикл платил 1.2 с сверху).
                    if (
                        silence_duration > self._config.wake_silence_ms
                        and speech_duration >= self.MIN_SPEECH_SECONDS
                    ):
                        break

                    # Слишком длинная речь (>8 сек) — берём всё что есть в буфере
                    if speech_duration > 8:
                        break

                if self._is_cancelled(cancel_event):
                    break

                # Извлекаем сегмент: буфер до речи + вся речь + хвост.
                # ВАЖНО: окно = вся речь + буфер, ограничено только размером
                # кольцевого буфера (9 сек) — «Джарвис» в начале длинной речи
                # больше не обрезается.
                total_seconds = (
                    (datetime.now() - speech_start_time).total_seconds()
                    + self.PRE_SPEECH_BUFFER_SECONDS
                )
                total_seconds = min(total_seconds, self.MAX_SEGMENT_SECONDS)

                # Сохраняем во временный файл
                wav_file = self._recorder.save_recent_audio(total_seconds)

                if not wav_file or not os.path.exists(wav_file):
                    continue

                # Проверяем размер — слишком маленький = проблема
                if os.path.getsize(wav_file) < 2000:
                    self._try_delete(wav_file)
                    continue

                # Распознаём речь (wake-сегмент короткий — таймаут 15 с,
                # fast-режим greedy-декодирования)
                text = self._whisper.transcribe(
                    wav_file,
                    timeout_s=self.WAKE_TRANSCRIBE_TIMEOUT_S,
                    fast=True,
                )

                # Удаляем временный файл
                self._try_delete(wav_file)

                if not text or not text.strip():
                    continue

                # Проверяем наличие ключевого слова (сначала точно, потом нечётко)
                if self._is_wake_word(text):
                    print(f'🔔 Обнаружено: "{text.strip()}"')
                    completed = True
                    return text

                # Отладочный вывод: что реально распознал Whisper
                print(f'💤 Распознано: "{text.strip()}" (не ключевое слово)')
        except Exception as ex:  # noqa: BLE001 — дословно как в C#
            print(f"⚠️ Ошибка детектора: {ex}")
        finally:
            # Останавливаем запись только если не нашли wake word:
            # при успехе рекордер продолжает работать для записи команды
            # (и не нужна повторная калибровка VAD на следующем цикле)
            if not completed:
                self._recorder.stop_continuous_recording()

        return ""

    def _is_wake_word(self, text: str) -> bool:
        """Проверяет текст на ключевое слово: точное совпадение подстроки,
        затем нечёткое сравнение по словам (расстояние Левенштейна ≤ 1–2).
        """
        norm = text.lower().replace("ё", "е")

        # 1) Точная проверка подстрокой
        for variant in self._wake_word_variants:
            if variant in norm:
                return True

        # 2) Нечёткое сравнение по словам (ловит «зера», «зерэ», «зире»)
        # C#: Regex.Split(norm, @"[^\p{L}]+") — split по не-буквам;
        # в Python [^\W\d_] эквивалент \p{L} (буква Unicode).
        words = re.split(r"[^\W\d_]+", norm)

        for word in words:
            if len(word) < 4 or len(word) > 12:
                continue

            for core in self.FUZZY_CORES:
                if abs(len(word) - len(core)) > 2:
                    continue

                # Порог зависит от длины: короткие слова — строже (меньше ложных срабатываний)
                max_distance = 2 if len(word) >= 6 else 1

                if self._levenshtein(word, core) <= max_distance:
                    return True

        return False

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        """Расстояние Левенштейна (оптимизированная матрица)."""
        prev = list(range(len(b) + 1))
        curr = [0] * (len(b) + 1)

        for i in range(1, len(a) + 1):
            curr[0] = i

            for j in range(1, len(b) + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)

            prev, curr = curr, prev

        return prev[len(b)]

    @staticmethod
    def _try_delete(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    def close(self) -> None:
        """Освобождение ресурсов (порт Dispose).

        Общий Whisper (передан снаружи) принадлежит VoiceManager —
        освобождаем только собственный экземпляр (анализ S3).
        """
        self._recorder.close()
        if self._owns_whisper and hasattr(self._whisper, "close"):
            self._whisper.close()

    def __enter__(self) -> "WakeWordDetector":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
