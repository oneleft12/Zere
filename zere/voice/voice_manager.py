"""Оркестратор STT (GigaAM/Whisper) + TTS (ChatTTS/Silero) (порт ZERE.Voice/VoiceManager.cs).

Отмена (CancellationToken в C#) → threading.Event.
"""

from __future__ import annotations

import os
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from zere.core.logging.log_service import log_error
from zere.voice.audio.audio_player import AudioPlayer
from zere.voice.audio.audio_processor import DEFAULT_SAMPLE_RATE, AudioProcessor
from zere.voice.audio.audio_recorder import AudioRecorder
from zere.voice.audio.csharp_speaker import CSharpSpeaker
from zere.voice.chattts.chattts_service import ChatTtsService
from zere.voice.sherpa.gigaam_service import GigaamService
from zere.voice.silero.silero_service import SileroTtsService
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
        self._chattts = ChatTtsService()
        self._silero = SileroTtsService()
        # Вызывался ли initialize(): в режиме `--panel` голос не инициализируют,
        # и перепроверять доступность TTS там не нужно (503 остаётся честным).
        self._tts_initialized = False
        self.config = VoiceConfig()  # Config { get; } — публичный атрибут
        self._wake_word_detector: WakeWordDetector | None = None
        # Семафор записи: панель и консоль не должны писать микрофон
        # одновременно (анализ F4).
        self._record_lock = threading.Lock()

        # Профили голоса ChatTTS под стиль личности (паритет с C#, где раньше
        # были голоса Piper): имя профиля → детерминированный голос ChatTTS.
        self._personality_voices: dict[str, str] = {
            "Friendly": "zere-warm",
            "Formal": "zere-strict",
            "Sarcastic": "zere-ironic",
            "Professional": "zere-business",
            "Casual": "zere-casual",
        }

        # Голоса Silero под тот же стиль (у Silero голоса именованные, поэтому
        # это реальные голоса движка, а не зёрна).
        self._silero_voices: dict[str, str] = {
            "Friendly": "baya",
            "Formal": "xenia",
            "Sarcastic": "aidar",
            "Professional": "eugene",
            "Casual": "kseniya",
        }

    @property
    def tts_engine(self) -> str:
        """Активный движок синтеза из config.json (в Python: chattts | silero).

        «pocket» — движок C#-редакции (клонирование голоса); здесь он
        означает ChatTTS, как и до появления выбора движка.
        """
        engine = (self.config.tts_engine or "chattts").strip().lower()

        return "silero" if engine == "silero" else "chattts"

    @property
    def _active_tts(self) -> Any:
        """Сервис активного TTS-движка (ChatTTS или Silero)."""
        return self._silero if self.tts_engine == "silero" else self._chattts

    @property
    def supports_speech_speed(self) -> bool:
        """Умеет ли активный движок менять темп речи (Silero v5 — нет)."""
        return bool(getattr(self._active_tts, "supports_speech_speed", True))

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
        """Доступен ли TTS активного движка (ChatTTS или Silero).

        После инициализации состояние перепроверяется на каждый запрос: движок
        можно поставить при работающем ZERE, и тогда озвучка начинает работать
        без перезапуска (дешёвая проверка `importlib.find_spec`, без загрузки
        модели). До initialize (режим `--panel`) состояние не переспрашивается —
        панель обязана честно отдавать 503, пока голос не инициализирован.
        """
        tts = self._active_tts

        if self._tts_initialized:
            return tts.refresh()

        return tts.is_loaded

    @property
    def tts_unavailable_reason(self) -> str:
        """Причина недоступности TTS для панели (пусто, если доступен)."""
        return self._active_tts.unavailable_reason

    def initialize(self, personality_style: str | None = None) -> bool:
        """Инициализирует TTS активного движка, подбирая голос под стиль.

        Модель здесь НЕ загружается: initialize только проверяет окружение, а
        веса ChatTTS / файл модели Silero поднимаются при первом speak()
        (ленивая загрузка — старт ZERE не платит за неё временем и памятью).
        """
        tts = self._active_tts

        if self.tts_engine == "silero":
            # У Silero голоса именованные: профиль личности → голос движка.
            # Неизвестное имя (например, профиль ChatTTS из конфига) движок
            # сам подменит дефолтным.
            voice_name = (
                self._silero_voices.get(personality_style)
                if personality_style is not None
                else None
            )
        else:
            voice_name = self.config.chattts_voice

            if personality_style is not None and personality_style in self._personality_voices:
                voice_name = self._personality_voices[personality_style]

        # Параметры инференса (темп, пауза после предложения) — до инициализации:
        # у ChatTTS они уходят в каждый запрос, перезапуск не нужен.
        tts.set_inference_params(
            self.config.speech_speed, self.config.sentence_silence
        )

        tts_ready = tts.initialize(voice_name)
        # С этого момента доступность TTS перепроверяется на каждый запрос:
        # движок могли поставить уже после старта (см. is_tts_available).
        self._tts_initialized = True

        if tts_ready:
            print(f"[Voice] TTS готов ({self.tts_engine}). Голос: {tts.current_voice}")
        else:
            print("[Voice] TTS недоступен. Только текстовый режим.")

        return tts_ready

    def set_personality_voice(self, style: str) -> None:
        """Меняет голос активного движка под стиль личности (SetPersonalityVoice)."""
        voice = (
            self._silero_voices.get(style)
            if self.tts_engine == "silero"
            else self._personality_voices.get(style)
        )

        if voice is not None:
            self._active_tts.set_voice(voice)
            print(f"[Voice] Голос изменён на: {voice} (стиль: {style})")

    def set_voice(self, voice_name: str) -> None:
        """Прямая смена голоса (контракт спецификации; в C# — SetVoice движка)."""
        self._active_tts.set_voice(voice_name)

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
        зеркало отката TTS-движков (§5 плана STT-исследования).
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
        """Озвучивает текст активным движком (ChatTTS/Silero, порт SpeakAsync);
        без TTS или при ошибке синтеза — печатает текст в консоль (fallback
        «TTS не отвечает → текстовый вывод», ROADMAP 1.1).
        """
        tts = self._active_tts

        if not tts.is_loaded:
            print(f"[ZERE] {text}")
            return

        started = time.monotonic()

        try:
            wav_file = tts.speak(text)
        except Exception as ex:  # noqa: BLE001
            log_error("VoiceManager", f"speak: {ex}")
            print(f"[ZERE] {text}")
            return

        if not wav_file:
            # Синтез не удался (нет ChatTTS/ошибка инференса) — текстовый вывод
            print(f"[ZERE] {text}")
            return

        # Этап 0 (метрики): готовность первого аудиофайла (синтез) —
        # дальше DSP + воспроизведение.
        synth_ms = int((time.monotonic() - started) * 1000)
        print(f"[Perf] TTS synth={synth_ms} мс ({self.tts_engine})")

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
            # страховка по пикам. Ресемплинг здесь обязателен: ChatTTS отдаёт
            # 24000 Гц, и если отдать их как есть, sounddevice/PortAudio будет
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

    def speak_background(self, text: str) -> None:
        """Озвучивает текст фоном, не блокируя вызывающий поток.

        Нужно панели: ответ клиенту уже отдан (SSE-событие `done`), поэтому
        синтез и воспроизведение не должны держать HTTP-соединение. Новая
        реплика обрывает предыдущую — как `StopSpeaking` перед `SpeakAsync`
        в C#-редакции. Поток демон: выход из ZERE не ждёт конца озвучки.
        """
        self.stop_speaking()

        threading.Thread(
            target=self._speak_quietly,
            args=(text,),
            daemon=True,
        ).start()

    def _speak_quietly(self, text: str) -> None:
        """`speak()` для фонового потока: сбой озвучки не должен всплывать."""
        try:
            self.speak(text)
        except Exception as ex:  # noqa: BLE001 — фоновая озвучка не роняет процесс
            log_error("VoiceManager", f"speak_background: {ex}")

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
        self._chattts.close()
        self._silero.close()
        if self._wake_word_detector is not None:
            self._wake_word_detector.close()

    def __enter__(self) -> "VoiceManager":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
