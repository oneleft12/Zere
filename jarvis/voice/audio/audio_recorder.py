"""Запись с микрофона (порт JARVIS.Voice/Audio/AudioRecorder.cs).

NAudio (WaveInEvent + WaveFileWriter) заменён на sounddevice (запись PCM)
+ stdlib wave (запись WAV). Формат как в исходнике: 16 kHz, 16 бит, 1 канал.
"""

from __future__ import annotations

import os
import threading
import time
import wave
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd


class AudioRecorder:
    """Запись аудио с микрофона (порт AudioRecorder.cs)."""

    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None

    @staticmethod
    def _input_folder() -> Path:
        # Путь как в C#: Directory.GetCurrentDirectory()/voice/input
        folder = Path.cwd() / "voice" / "input"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def record(self, seconds: int = 5, sample_rate: int = 16000) -> str:
        """Запись аудио с микрофона.

        Использует 16 kHz mono (стандарт Whisper) с оптимальными настройками.
        """
        file = self._input_folder() / "record.wav"

        if file.exists():
            file.unlink()

        # Оптимальные настройки для Whisper STT: WaveFormat(sampleRate, 16, 1)
        # BufferMilliseconds=50 / NumberOfBuffers=3 — внутренняя буферизация
        # выполняется самим sounddevice; DeviceNumber=0 — микрофон по умолчанию
        # (sounddevice записывает с input-устройства по умолчанию).
        writer = wave.open(str(file), "wb")
        writer.setnchannels(1)
        writer.setsampwidth(2)  # 16 бит
        writer.setframerate(sample_rate)

        try:
            print(f"🎤 Слушаю {seconds} секунд...")

            data = sd.rec(
                int(seconds * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
            )
            sd.wait()

            # Аналог WaveFileWriter.Write + Flush на каждый буфер
            writer.writeframes(np.asarray(data).reshape(-1).tobytes())

            # Даём время на завершение записи (Task.Delay(200) в C#)
            time.sleep(0.2)
        finally:
            writer.close()

        # Проверяем качество записи
        if os.path.getsize(file) < 1000:  # Слишком маленький файл = проблема
            print("⚠️ Запись слишком тихая. Проверьте микрофон.")

        print("✅ Запись завершена.")

        return str(file)

    def record_with_vad(self, max_seconds: int = 10, silence_ms: int = 1500) -> str:
        """Запись с автоматическим определением конца речи (VAD-подобное).

        Записывает до тишины или максимального времени.
        """
        file = self._input_folder() / "record.wav"

        if file.exists():
            file.unlink()

        # WaveFormat(16000, 16, 1)
        writer = wave.open(str(file), "wb")
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)

        # Окно RMS как в C#: последние 8000 сэмплов
        recent_squared: deque[float] = deque(maxlen=8000)
        state_lock = threading.Lock()
        last_speech_time = datetime.now()
        has_speech = False

        def on_data(
            indata: np.ndarray,
            frames: int,
            time_info: object,
            status: object,
        ) -> None:
            nonlocal last_speech_time, has_speech

            # Конвертируем int16 байты в float samples (16-bit = 2 bytes)
            chunk = np.asarray(indata).reshape(-1)
            samples = chunk.astype(np.float32) / 32768.0

            # Вычисляем RMS (скользящее окно 8000 сэмплов)
            with state_lock:
                recent_squared.extend((samples * samples).tolist())
                window = np.fromiter(recent_squared, dtype=np.float64)
                rms = float(np.sqrt(np.mean(window))) if window.size else 0.0

                # Если RMS выше порога — есть речь
                if rms > 0.02:  # ~-34 dBFS
                    has_speech = True
                    last_speech_time = datetime.now()

            # Записываем в файл
            writer.writeframes(chunk.astype("<i2", copy=False).tobytes())

        stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="int16",
            callback=on_data,
        )

        try:
            print("🎤 Говорите... (авто-остановка при тишине)")

            stream.start()
            last_speech_time = datetime.now()

            start_time = datetime.now()
            while (datetime.now() - start_time).total_seconds() < max_seconds:
                time.sleep(0.1)

                # Если уже была речь и теперь тишина long enough
                with state_lock:
                    speech_seen = has_speech
                    last_speech = last_speech_time

                if speech_seen and (datetime.now() - last_speech).total_seconds() * 1000 > silence_ms:
                    print("🔇 Обнаружена тишина, останавливаю запись...")
                    break

            stream.stop()
            # Даём время на завершение записи
            time.sleep(0.2)
        finally:
            try:
                stream.close()
            except Exception:
                pass
            writer.close()

        with state_lock:
            speech_found = has_speech

        if not speech_found:
            print("⚠️ Речь не обнаружена. Проверьте микрофон.")
        else:
            print("✅ Запись завершена.")

        return str(file)

    def close(self) -> None:
        """Освобождение ресурсов (порт Dispose)."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def __enter__(self) -> "AudioRecorder":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
