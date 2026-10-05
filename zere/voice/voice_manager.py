"""Оркестратор STT (GigaAM/Whisper) + TTS (Piper) (порт ZERE.Voice/VoiceManager.cs).

Отмена (CancellationToken в C#) → threading.Event.
"""

from __future__ import annotations

import os
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from zere.core.logging.log_service import log_error
from zere.voice.audio.audio_player import AudioPlayer
from zere.voice.audio.audio_processor import DEFAULT_SAMPLE_RATE, AudioProcessor
from zere.voice.audio.audio_recorder import AudioRecorder
from zere.voice.audio.csharp_speaker import CSharpSpeaker
from zere.voice.piper.piper_service import PiperService
from zere.voice.sherpa.gigaam_service import GigaamService
from zere.voice.voice_config import VoiceConfig
from zere.voice.wakeword.wake_word_detector import WakeWordDetector
from zere.voice.whisper.whisper_service import WhisperService


def output_sample_rate() -> int:
    """Частота устройства вывода по умолчанию — под неё ресемплится озвучка.

    Берётся `default_samplerate` устройства вывода sounddevice (44100 у
    большинства USB-гарнитур, 48000 у HDMI/NVIDIA). Если узнать не удалось,
    используется DEFAULT_SAMPLE_RATE (44100): она заведомо лучше, чем отдать
    22050 Гц, которые PortAudio потом конвертирует сам своим слабым
    ресемплером — это и давало «металлический» призвук на выходе.
    """
    try:
        import sounddevice as sd

        device = sd.default.device[1]

        if device is None or device < 0:
            return DEFAULT_SAMPLE_RATE

        rate = int(sd.query_devices(device)["default_samplerate"])

        return rate if rate > 0 else DEFAULT_SAMPLE_RATE
    except Exception:  # noqa: BLE001 — нет устройства/PortAudio: дефолт надёжнее
        return DEFAULT_SAMPLE_RATE


def _remove_quietly(path: str) -> None:
    """Удаляет временный WAV, молча глотая «нет файла»."""
    if not path:
        return

    try:
        os.remove(path)
    except OSError:
        pass


class VoiceManager:
    """Оркестратор голосового ввода/вывода (порт VoiceManager.cs, IDisposable → close())."""

    def __init__(self) -> None:
        self._recorder = AudioRecorder()
        self._player = AudioPlayer()
        # Озвучка на C#: DSP + вывод звука делает ZERE.Speaker (NAudio/WASAPI),
        # Python остаётся фолбэком (sounddevice).
        self._speaker = CSharpSpeaker()
        self._speaker_fallback_logged = False
        self._whisper = WhisperService()
        self._gigaam = GigaamService()
        self._piper = PiperService()
        self.config = VoiceConfig()  # Config { get; } — публичный атрибут
        self._wake_word_detector: WakeWordDetector | None = None
        # Семафор записи: панель и консоль не должны писать микрофон
        # одновременно (анализ F4).
        self._record_lock = threading.Lock()

        self._personality_voices: dict[str, str] = {
            "Friendly": "ru_RU-ruslan-medium",
            "Formal": "ru_RU-dmitri-medium",
            "Sarcastic": "ru_RU-ruslan-medium",
            "Professional": "ru_RU-dmitri-medium",
            "Casual": "ru_RU-ruslan-medium",
        }

    @property
    def _active_stt(self):
        """Активный STT-движок (роутинг gigaam→whisper, §5 отчёта STT).

        GigaAM, если он выбран (sttEngine) и модель готова; иначе Whisper,
        если тот есть; иначе GigaAm. Ленивая проверка на каждый вызов —
        после завершения скачивания модели выбор переключается сам.
        Wake word детектор намеренно остаётся на Whisper (§5.3 отчёта).
        """
        if self.config.stt_engine.lower() == "gigaam" and self._gigaam.is_installed():
            return self._gigaam

        if self._whisper.is_installed():
            return self._whisper

        return self._gigaam

    @property
    def is_voice_available(self) -> bool:
        """Доступен ли STT (GigaAM или Whisper)."""
        return self._active_stt.is_installed()

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

    def preload_stt(self) -> None:
        """Предзагрузка активного STT-движка в фоне при старте (ROADMAP 1.3):
        первый вызов распознавания не ждёт загрузки модели. Для GigaAM при
        отсутствии модели здесь же выполняется разовое скачивание
        (163 МБ, SHA-256) — зеркало PreloadStt в C#.
        """
        try:
            if self.config.stt_engine.lower() == "gigaam":
                # Предпочитаемый движок: скачиваем/греем GigaAM; если он не
                # поднялся — подстраховываемся Whisper, чтобы голос работал.
                if not self._gigaam.preload() and self._whisper.is_installed():
                    self._whisper.preload()
            else:
                self._whisper.preload()

            active = self._active_stt
            print(
                f"[Voice] STT активен: {active.current_model} "
                f"(запрошен движок: {self.config.stt_engine})."
            )
        except Exception as ex:  # noqa: BLE001 — предзагрузка не должна ронять старт
            log_error("VoiceManager", f"Предзагрузка STT: {ex}")

    def _transcribe_stt(self, wav_file: str, timeout_s: int | None = None) -> str:
        """Распознавание через активный STT-движок с откатом на Whisper.

        Сбой GigaAM (например, битый файл модели) уводит на Whisper —
        зеркало отката pocket→piper (§5 плана STT-исследования).
        """
        engine = self._active_stt

        try:
            return engine.transcribe(wav_file, timeout_s=timeout_s)
        except Exception as ex:  # noqa: BLE001
            if engine is self._gigaam and self._whisper.is_installed():
                log_error("VoiceManager", f"STT gigaam сбой: {ex} — откат на Whisper")
                print(f"[Voice] STT (gigaam) сбой: {ex} — откат на Whisper.")
                return self._whisper.transcribe(wav_file, timeout_s=timeout_s)
            raise

    def listen(self) -> str:
        """Записывает речь с микрофона и распознаёт её (порт ListenAsync)."""
        if not self._active_stt.is_installed():
            print("[Voice] STT не установлен (нет ни GigaAM, ни Whisper).")
            return ""

        # Семафор записи + защита от сбоя микрофона (анализы F4/F1)
        with self._record_lock:
            try:
                wav = self._recorder.record()
            except Exception as ex:  # noqa: BLE001
                log_error("VoiceManager", f"listen(record): {ex}")
                print(f"[Voice] Ошибка записи: {ex}. Переключаюсь на текстовый ввод.")
                return ""

        if not wav or not os.path.exists(wav):
            return ""

        print("Распознаю речь...")

        try:
            return self._transcribe_stt(wav)
        except Exception as ex:  # noqa: BLE001 — fallback: текстовый ввод
            log_error("VoiceManager", f"listen: {ex}")
            print(f"[Voice] Ошибка распознавания: {ex}")
            return ""
        finally:
            try:
                os.remove(wav)
            except OSError:
                pass

    def speak(self, text: str) -> None:
        """Озвучивает текст через Piper (порт SpeakAsync); без TTS или при ошибке
        синтеза — печатает текст в консоль (fallback «Piper не отвечает →
        текстовый вывод», ROADMAP 1.1).
        """
        if not self._piper.is_loaded:
            print(f"[ZERE] {text}")
            return

        started = time.monotonic()

        try:
            wav_file = self._piper.speak(text)
        except Exception as ex:  # noqa: BLE001
            log_error("VoiceManager", f"speak: {ex}")
            print(f"[ZERE] {text}")
            return

        if not wav_file:
            # Синтез не удался (после reconnect в PiperService) — текстовый вывод
            print(f"[ZERE] {text}")
            return

        # Этап 0 (метрики): готовность первого аудиофайла (синтез) —
        # дальше DSP + воспроизведение.
        synth_ms = int((time.monotonic() - started) * 1000)
        print(f"[Perf] TTS synth={synth_ms} мс (piper)")

        # Озвучка на C# (ZERE.Speaker): DSP и вывод звука — NAudio/WASAPI.
        # Если хелпер не собран или упал — озвучиваем сами (sounddevice).
        if self._speaker.available():
            speak_ms = int((time.monotonic() - started) * 1000)

            if self._speaker.speak(
                wav_file,
                volume=self.config.volume,
                process=self.config.audio_processing,
                rate=output_sample_rate(),
            ):
                print(
                    f"[Perf] озвучка C# (ZERE.Speaker)="
                    f"{int((time.monotonic() - started) * 1000) - speak_ms} мс"
                )
                _remove_quietly(wav_file)
                return

            if not self._speaker_fallback_logged:
                log_error(
                    "VoiceManager",
                    "C#-озвучка не сработала — озвучиваю через Python (sounddevice)",
                )
                self._speaker_fallback_logged = True

        file_to_play = wav_file

        try:
            # Профессиональная DSP-обработка: ресемплинг под устройство, EQ,
            # страховка по пикам. Ресемплинг здесь обязателен: piper отдаёт
            # 22050 Гц, и если отдать их как есть, sounddevice/PortAudio будет
            # конвертировать сам — своим слабым ресемплером, что и даёт
            # «металлический» призвук на выходе.
            if self.config.audio_processing:
                file_to_play = AudioProcessor.process(wav_file, output_sample_rate())

            self._player.play(file_to_play, self.config.volume)
        except Exception as ex:  # noqa: BLE001 — воспроизведение не должно «резать» вывод
            log_error("VoiceManager", f"play: {ex}")
            print(f"[ZERE] {text}")
        finally:
            # Удаляем обработанный файл (если он отличается от оригинального)
            _remove_quietly(file_to_play if file_to_play != wav_file else "")
            _remove_quietly(wav_file)

    def stop_speaking(self) -> None:
        """Останавливает воспроизведение (порт StopSpeaking).

        Гасим оба тракта: C#-хелпер (если озвучивал он) и Python-плеер.
        """
        self._speaker.stop()
        self._player.stop()

    # ─── Wake Word ──────────────────────────────────────────

    def enable_wake_word(self) -> WakeWordDetector:
        """Включает режим wake word и возвращает детектор.

        Детектор ОДИН на сессию (анализ S3): раньше новый создавался на
        каждом цикле — это означало повторную калибровку VAD и повторную
        загрузку модели Whisper на каждую команду.
        """
        if self._wake_word_detector is None:
            self._wake_word_detector = WakeWordDetector(self.config, whisper=self._whisper)
        return self._wake_word_detector

    def disable_wake_word(self) -> None:
        """Выключает wake word: останавливает непрерывную запись и
        освобождает детектор при выходе из голосового режима
        (общий Whisper не трогается).
        """
        if self._wake_word_detector is None:
            return

        try:
            self._wake_word_detector.recorder.stop_continuous_recording()
        except Exception:  # noqa: BLE001 — рекордер уже остановлен
            pass

        self._wake_word_detector.close()
        self._wake_word_detector = None

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
        if not self._active_stt.is_installed():
            print("[Voice] STT не установлен (нет ни GigaAM, ни Whisper).")
            return ""

        # Используем рекордер из детектора (непрерывная запись)
        recorder = self._wake_word_detector.recorder if self._wake_word_detector is not None else None

        if recorder is None or not recorder.is_recording:
            # Fallback: используем обычный рекордер (семафор записи — F4;
            # пауза тишины — из конфига, было 1500 мс, анализ S4)
            with self._record_lock:
                try:
                    wav = self._recorder.record_with_vad(
                        max_seconds=10, silence_ms=self.config.command_silence_ms
                    )
                except Exception as ex:  # noqa: BLE001 — анализ F1
                    log_error("VoiceManager", f"listen_command(record): {ex}")
                    print(f"[Voice] Ошибка записи: {ex}")
                    return ""

            if not wav or not os.path.exists(wav):
                return ""

            if os.path.getsize(wav) < 2000:  # FileInfo.Length < 2000
                try:
                    os.remove(wav)
                except OSError:
                    pass
                return ""

            print("🧠 Распознаю команду...")
            try:
                result = self._transcribe_stt(wav)
            except Exception as ex:  # noqa: BLE001 — fallback: текстовый ввод
                log_error("VoiceManager", f"listen_command: {ex}")
                result = ""
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

        # Речь обнаружена — ждём окончания (пауза тишины — из конфига,
        # было жёсткие 1500 мс, анализ S4)
        last_speech_time = datetime.now()
        speech_start = datetime.now()
        command_silence_ms = self.config.command_silence_ms

        while (
            (datetime.now() - last_speech_time).total_seconds() * 1000 < command_silence_ms
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

        # Сохраняем во временный файл (уникальное имя — панель и консоль
        # могут записывать одновременно, анализ F4)
        # C#: Path.Combine(Directory.GetCurrentDirectory(), "voice", "input", "cmd_{ts}_{guid}.wav")
        cmd_file = (
            Path.cwd()
            / "voice"
            / "input"
            / f"cmd_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex}.wav"
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

        try:
            cmd_result = self._transcribe_stt(str(cmd_file))
        except Exception as ex:  # noqa: BLE001 — fallback: текстовый ввод
            log_error("VoiceManager", f"listen_command: {ex}")
            cmd_result = ""

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
        self._speaker.close()
        if self._wake_word_detector is not None:
            self._wake_word_detector.close()

    def __enter__(self) -> "VoiceManager":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
