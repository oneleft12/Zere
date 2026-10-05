"""Непрерывная запись с круговым буфером и VAD
(порт ZERE.Voice/Audio/ContinuousAudioRecorder.cs).

WaveInEvent (NAudio) заменён на sounddevice.InputStream; событие
RecordingStopped в Python отсутствует — состояние is_recording
снимается явно в stop_continuous_recording()/close().
"""

from __future__ import annotations

import math
import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

from zere.voice.audio.audio_device import input_options


class ContinuousAudioRecorder:
    """Непрерывный записывающий устройство с круговым буфером и VAD.

    Не пересоздаёт входной поток — одна запись на весь сеанс.
    Адаптивный VAD: первый 2 сек замеряет шум, затем порог = шум × 2.5.
    """

    RMS_WINDOW_MS = 400  # Окно RMS 400ms

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Круговой буфер: хранит float сэмплы (16kHz mono)
        self._ring_buffer: np.ndarray = np.zeros(0, dtype=np.float32)
        self._write_pos = 0
        self._total_samples_written = 0
        self._buffer_capacity = 0
        self._sample_rate = 16000

        # VAD — адаптивный порог
        self._noise_floor = 0.005           # Уровень шума (среднее за калибровку)
        self._speech_threshold = 0.010      # Порог = средний шум × 2
        self._calib_sum = 0.0               # Сумма RMS для среднего при калибровке
        self._calib_count = 0               # Количество замеров при калибровке
        self._is_speech = False
        self._calibrated = False
        self._speech_start_time = datetime.min
        self._last_speech_time = datetime.min

        # Быстрый RMS — инкрементальный расчёт без пересканирования буфера
        self._rms_sum = 0.0
        self._rms_window_samples = 0
        self._rms_window_start = datetime.now()

        # Состояние
        self._is_recording = False
        self._disposed = False

        self._stream: sd.InputStream | None = None
        self.last_rms: float = 0.0  # LastRms { get; private set; }

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_speech_detected(self) -> bool:
        return self._is_speech

    def start_continuous_recording(self, buffer_seconds: int = 10, sample_rate: int = 16000) -> None:
        """Запуск непрерывной записи в круговой буфер."""
        with self._lock:
            if self._is_recording:
                return

            self._buffer_capacity = sample_rate * buffer_seconds
            self._ring_buffer = np.zeros(self._buffer_capacity, dtype=np.float32)
            self._write_pos = 0
            self._total_samples_written = 0
            self._sample_rate = sample_rate
            self._is_speech = False
            self._calibrated = False
            self._noise_floor = 0.005
            self._speech_threshold = 0.010
            self._calib_sum = 0.0
            self._calib_count = 0

            # Сброс окна RMS
            self._rms_sum = 0.0
            self._rms_window_samples = 0
            self._rms_window_start = datetime.now()

            # WaveFormat(sampleRate, 16, 1); BufferMilliseconds=50, NumberOfBuffers=3,
            # DeviceNumber=0 — внутреннюю буферизацию выполняет sounddevice.
            # Устройство — WASAPI-аналог микрофона по умолчанию с системным
            # ресемплером (16 кГц на WASAPI без auto_convert даёт -9997),
            # иначе — устройство по умолчанию (MME).
            self._stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                callback=self._on_data_available,
                **input_options(sample_rate, channels=1, dtype="int16"),
            )
            self._stream.start()
            self._is_recording = True

    def stop_continuous_recording(self) -> None:
        """Остановка непрерывной записи."""
        with self._lock:
            if not self._is_recording or self._stream is None:
                return

            try:
                self._stream.stop()
            except Exception:
                pass

            self._is_recording = False

    def extract_recent_audio(self, seconds: float) -> np.ndarray:
        """Извлекает последние N секунд аудио из кругового буфера."""
        with self._lock:
            if self._ring_buffer.size == 0 or self._total_samples_written == 0:
                return np.zeros(0, dtype=np.float32)

            sample_rate = self._sample_rate or 16000
            samples_to_extract = min(
                int(sample_rate * seconds),
                min(self._total_samples_written, self._buffer_capacity),
            )

            result = np.empty(samples_to_extract, dtype=np.float32)
            read_pos = (self._write_pos - samples_to_extract + self._buffer_capacity) % self._buffer_capacity

            first = min(samples_to_extract, self._buffer_capacity - read_pos)
            result[:first] = self._ring_buffer[read_pos:read_pos + first]
            if first < samples_to_extract:
                result[first:] = self._ring_buffer[: samples_to_extract - first]

            return result

    def extract_recent_audio_bytes(self, seconds: float) -> bytes:
        """Извлекает аудио как bytes (16-bit PCM) для WAV."""
        samples = self.extract_recent_audio(seconds)
        if samples.size == 0:
            return b""

        clamped = np.clip(samples, -1.0, 1.0)
        # (short)(clamped * 32767) в C# — усечение к нулю, как astype(np.int16)
        sample16 = (clamped * np.float32(32767.0)).astype(np.int16)
        return sample16.astype(np.dtype("<i2"), copy=False).tobytes()

    def save_recent_audio(self, seconds: float, file_path: str | None = None) -> str:
        """Сохраняет последние N секунд аудио в WAV-файл."""
        data_bytes = self.extract_recent_audio_bytes(seconds)
        if not data_bytes:
            return ""

        sample_rate = self._sample_rate or 16000

        if file_path is None:
            # C#: Directory.GetCurrentDirectory()/voice/input/wake_{ts}.wav
            file_path = str(
                Path.cwd() / "voice" / "input" / f"wake_{datetime.now():%Y%m%d_%H%M%S}.wav"
            )

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # WaveFormat(sampleRate, 16, 1)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(data_bytes)

        return file_path

    def set_threshold(self, threshold: float) -> None:
        """Ручная установка порога (перезаписывает адаптивный)."""
        self._speech_threshold = threshold
        self._calibrated = True  # Блокирует адаптивную подстройку

    # ─── Callback потока ────────────────────────────────────

    def _on_data_available(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        if self._disposed or not self._is_recording:
            return

        # Конвертируем int16 → float (BitConverter.ToInt16(buffer, i*2) / 32768f)
        samples = np.asarray(indata).reshape(-1).astype(np.float32) / 32768.0
        sample_count = len(samples)
        now = datetime.now()

        with self._lock:
            # Пишем в круговой буфер + считаем инкрементальный RMS
            written = 0
            while written < sample_count:
                chunk = samples[written:]
                space = self._buffer_capacity - self._write_pos
                take = min(len(chunk), space)
                self._ring_buffer[self._write_pos:self._write_pos + take] = chunk[:take]
                self._write_pos = (self._write_pos + take) % self._buffer_capacity
                written += take

            self._total_samples_written += sample_count

            # Инкрементальный RMS
            self._rms_sum += float(np.dot(samples, samples))
            self._rms_window_samples += sample_count

        # Проверяем окно RMS каждые ~400ms
        elapsed_ms = (now - self._rms_window_start).total_seconds() * 1000
        if elapsed_ms < self.RMS_WINDOW_MS:
            return

        with self._lock:
            rms = (
                float(math.sqrt(self._rms_sum / self._rms_window_samples))
                if self._rms_window_samples > 0
                else 0.0
            )
            self._rms_sum = 0.0
            self._rms_window_samples = 0
            self._rms_window_start = now

        self.last_rms = rms

        # === Адаптивная калибровка (первые 2 сек — замер шума) ===
        if not self._calibrated and self._total_samples_written < 32000:  # 2 сек при 16kHz
            self._calib_sum += rms
            self._calib_count += 1

            # После 2 сек устанавливаем порог по СРЕДНЕМУ шуму комнаты.
            # Максимум ломался на случайном всплеске → порог непроходимо высоким.
            if self._total_samples_written >= 30000:
                mean_noise = (self._calib_sum / self._calib_count) if self._calib_count > 0 else 0.005
                self._noise_floor = mean_noise
                self._speech_threshold = min(max(mean_noise * 2.0, 0.005), 0.04)
                self._calibrated = True
            return  # Ещё калибруемся — не триггерим

        # === VAD логика ===
        if rms > self._speech_threshold:
            if not self._is_speech:
                self._is_speech = True
                self._speech_start_time = now
            self._last_speech_time = now
        elif self._is_speech and (now - self._last_speech_time).total_seconds() * 1000 > 1500:
            self._is_speech = False

    # ─── Освобождение ───────────────────────────────────────

    def close(self) -> None:
        """Освобождение ресурсов (порт Dispose)."""
        if self._disposed:
            return
        self._disposed = True

        with self._lock:
            self._is_recording = False

            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass

                self._stream = None

    def __enter__(self) -> "ContinuousAudioRecorder":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
