"""Оркестратор STT (Whisper) + TTS (Piper) (порт JARVIS.Voice/VoiceManager.cs).

Отмена (CancellationToken в C#) → threading.Event.
"""

from __future__ import annotations

import os
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

from jarvis.voice.audio.audio_player import AudioPlayer
from jarvis.voice.audio.audio_processor import AudioProcessor
from jarvis.voice.audio.audio_recorder import AudioRecorder
from jarvis.voice.piper.piper_service import PiperService
from jarvis.voice.voice_config import VoiceConfig
from jarvis.voice.wakeword.wake_word_detector import WakeWordDetector
from jarvis.voice.whisper.whisper_service import WhisperService


class VoiceManager:
    """Оркестратор голосового ввода/вывода (порт VoiceManager.cs, IDisposable → close())."""

    def __init__(self) -> None:
        self._recorder = AudioRecorder()
        self._player = AudioPlayer()
        self._whisper = WhisperService()
        self._piper = PiperService()
        self.config = VoiceConfig()  # Config { get; } — публичный атрибут
        self._wake_word_detector: WakeWordDetector | None = None

        self._personality_voices: dict[str, str] = {
            "Friendly": "ru_RU-ruslan-medium",
            "Formal": "ru_RU-dmitri-medium",
            "Sarcastic": "ru_RU-ruslan-medium",
            "Professional": "ru_RU-dmitri-medium",
            "Casual": "ru_RU-ruslan-medium",
        }

    @property
    def is_voice_available(self) -> bool:
        """Доступен ли STT (Whisper)."""
        return self._whisper.is_installed()

    @property
    def is_tts_available(self) -> bool:
        """Доступен ли TTS (Piper)."""
        return self._piper.is_loaded

    def initialize(self, personality_style: str | None = None) -> bool:
        """Инициализирует TTS, подбирая голос под стиль личности (порт Initialize)."""
        voice_name = self.config.piper_voice

        if personality_style is not None and personality_style in self._personality_voices:
            voice_name = self._personality_voices[personality_style]

        tts_ready = self._piper.initialize(voice_name)

        if tts_ready:
            print(f"[Voice] TTS готов. Голос: {self._piper.current_voice}")
        else:
            print("[Voice] TTS недоступен. Только текстовый режим.")

        return tts_ready

    def set_personality_voice(self, style: str) -> None:
        """Меняет голос Piper под стиль личности (порт SetPersonalityVoice)."""
        voice = self._personality_voices.get(style)
        if voice is not None:
            self._piper.set_voice(voice)
            print(f"[Voice] Голос изменён на: {voice} (стиль: {style})")

    def set_voice(self, voice_name: str) -> None:
        """Прямая смена голоса Piper (контракт спецификации; в C# — PiperService.SetVoice)."""
        self._piper.set_voice(voice_name)

    def listen(self) -> str:
        """Записывает речь с микрофона и распознаёт её (порт ListenAsync)."""
        if not self._whisper.is_installed():
            print("[Voice] Whisper не установлен.")
            return ""

        wav = self._recorder.record()

        print("Распознаю речь...")

        return self._whisper.transcribe(wav)

    def speak(self, text: str) -> None:
        """Озвучивает текст через Piper (порт SpeakAsync); без TTS — печатает в консоль."""
        if not self._piper.is_loaded:
            print(f"[JARVIS] {text}")
            return

        wav_file = self._piper.speak(text)

        if wav_file:
            file_to_play = wav_file

            # Профессиональная DSP-обработка: EQ, компрессия, нормализация
            if self.config.audio_processing:
                file_to_play = AudioProcessor.process(wav_file)

            self._player.play(file_to_play, self.config.volume)

            # Удаляем обработанный файл (если он отличается от оригинального)
            try:
                if file_to_play != wav_file:
                    os.remove(file_to_play)
            except OSError:
                pass
            try:
                os.remove(wav_file)
            except OSError:
                pass

    def stop_speaking(self) -> None:
        """Останавливает воспроизведение (порт StopSpeaking)."""
        self._player.stop()

    # ─── Wake Word ──────────────────────────────────────────

    def enable_wake_word(self) -> WakeWordDetector:
        """Включает режим wake word и возвращает детектор."""
        if self._wake_word_detector is not None:
            self._wake_word_detector.close()
        self._wake_word_detector = WakeWordDetector(self.config)
        return self._wake_word_detector

    def wait_for_wake_word(self, cancel_event: threading.Event | None = None) -> bool:
        """Ожидает произнесения ключевого слова.
        Возвращает True если обнаружено, False если отмена.
        """
        if self._wake_word_detector is None:
            return False

        result = self._wake_word_detector.wait_for_wake_word(cancel_event)
        return bool(result)

    def listen_command(self) -> str:
        """Слушает голосовую команду после wake word (порт ListenCommandAsync).
        Использует тот же ContinuousAudioRecorder что и детектор — без пересоздания.
        Ждёт речи, записывает, останавливается при тишине.
        """
        if not self._whisper.is_installed():
            print("[Voice] Whisper не установлен.")
            return ""

        # Используем рекордер из детектора (непрерывная запись)
        recorder = self._wake_word_detector.recorder if self._wake_word_detector is not None else None

        if recorder is None or not recorder.is_recording:
            # Fallback: используем обычный рекордер
            wav = self._recorder.record_with_vad(max_seconds=10, silence_ms=1500)

            if not wav or not os.path.exists(wav):
                return ""

            if os.path.getsize(wav) < 2000:  # FileInfo.Length < 2000
                try:
                    os.remove(wav)
                except OSError:
                    pass
                return ""

            print("🧠 Распознаю команду...")
            result = self._whisper.transcribe(wav)
            try:
                os.remove(wav)
            except OSError:
                pass
            return result

        # Ждём начала речи
        wait_start = datetime.now()
        while (
            not recorder.is_speech_detected
            and (datetime.now() - wait_start).total_seconds() < 8
        ):
            time.sleep(0.2)

        if not recorder.is_speech_detected:
            print("⚠️ Речь не обнаружена.")
            return ""

        # Речь обнаружена — ждём окончания
        last_speech_time = datetime.now()
        speech_start = datetime.now()

        while (
            (datetime.now() - last_speech_time).total_seconds() * 1000 < 1500
            and (datetime.now() - speech_start).total_seconds() < 10
        ):
            time.sleep(0.2)

            if recorder.is_speech_detected:
                last_speech_time = datetime.now()

        # Извлекаем аудио с буфером до речи
        total_seconds = (datetime.now() - speech_start).total_seconds() + 1.5
        total_seconds = min(total_seconds, 12.0)

        audio_bytes = recorder.extract_recent_audio_bytes(total_seconds)

        if len(audio_bytes) < 2000:
            print("⚠️ Запись слишком короткая.")
            return ""

        # Сохраняем во временный файл
        # C#: Path.Combine(Directory.GetCurrentDirectory(), "voice", "input", "cmd_{ts}.wav")
        cmd_file = (
            Path.cwd()
            / "voice"
            / "input"
            / f"cmd_{datetime.now():%Y%m%d_%H%M%S}.wav"
        )
        cmd_file.parent.mkdir(parents=True, exist_ok=True)

        sample_rate = 16000
        # new WaveFormat(sampleRate, 16, 1)
        with wave.open(str(cmd_file), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(audio_bytes)

        print("🧠 Распознаю команду...")

        cmd_result = self._whisper.transcribe(str(cmd_file))

        try:
            os.remove(cmd_file)
        except OSError:
            pass

        return cmd_result

    # ─── Освобождение ───────────────────────────────────────

    def close(self) -> None:
        """Освобождение ресурсов (порт Dispose)."""
        self._recorder.close()
        self._player.close()
        if self._wake_word_detector is not None:
            self._wake_word_detector.close()

    def __enter__(self) -> "VoiceManager":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
