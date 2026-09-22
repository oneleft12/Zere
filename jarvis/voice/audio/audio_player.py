"""Воспроизведение WAV (порт JARVIS.Voice/Audio/AudioPlayer.cs).

NAudio (WaveOutEvent + AudioFileReader) заменён на sounddevice (PCM) +
stdlib wave (чтение WAV).
"""

from __future__ import annotations

import os
import threading
import wave

import numpy as np
import sounddevice as sd


class AudioPlayer:
    """Воспроизведение WAV-файла с регулировкой громкости (порт AudioPlayer.cs)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cleaning_up = False
        self._is_playing = False

    @property
    def is_playing(self) -> bool:
        """Идёт ли воспроизведение (аналог AudioPlayer.IsPlaying)."""
        return self._is_playing

    def play(self, wav_file: str, volume: float = 1.0) -> None:
        """Воспроизводит WAV-файл и блокируется до конца воспроизведения."""
        if not os.path.exists(wav_file):
            print(f"[AudioPlayer] Файл не найден: {wav_file}")
            return

        # Ensure any previous playback is cleaned up before starting new instance.
        self._cleanup()

        try:
            with wave.open(wav_file, "rb") as reader:
                sample_rate = reader.getframerate()
                channels = reader.getnchannels()
                samp_width = reader.getsampwidth()
                raw = reader.readframes(reader.getnframes())

            # Читаем сэмплы как PCM (Аналог AudioFileReader c Volume)
            if samp_width == 2:
                data = np.frombuffer(raw, dtype="<i2").astype(np.float32)
            elif samp_width == 4:
                data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
            elif samp_width == 1:
                data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            elif samp_width == 3:
                # 24-bit → float
                b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
                ints = (
                    b[:, 0].astype(np.int32)
                    | (b[:, 1].astype(np.int32) << 8)
                    | (b[:, 2].astype(np.int32) << 16)
                )
                ints = np.where(ints >= 0x800000, ints - 0x1000000, ints)
                data = ints.astype(np.float32) / 8388608.0
            else:
                raise ValueError(f"Неподдерживаемая битность WAV: {samp_width * 8} бит")

            # Volume (аналог AudioFileReader.Volume) — и обратно в int16 для sounddevice
            if volume != 1.0:
                data = data * float(volume)
            data = np.clip(data, -1.0, 1.0)

            if samp_width == 2:
                out = (data * 32767.0).astype(np.int16)
            else:
                # Воспроизводим как float32 — sounddevice принимает [-1..1]
                out = data.astype(np.float32)

            if channels > 1:
                out = out.reshape(-1, channels)

            self._is_playing = True
            sd.play(out, samplerate=sample_rate)

            while self._is_playing:
                # Ожидание конца (аналог цикла while (IsPlaying) + PlaybackStopped)
                sd.wait()
                # PlaybackStopped: IsPlaying = false; Cleanup()
                self._is_playing = False

            self._cleanup()
        except Exception as ex:  # noqa: BLE001 — дословно как в C#
            print(f"[AudioPlayer] Ошибка воспроизведения: {ex}")
            self._cleanup()

    def stop(self) -> None:
        """Останавливает воспроизведение (порт AudioPlayer.Stop)."""
        try:
            sd.stop()
        except Exception:
            pass
        self._is_playing = False
        self._cleanup()

    def _cleanup(self) -> None:
        with self._lock:
            if self._cleaning_up:
                return

            self._cleaning_up = True

            try:
                # У NAudio здесь Dispose'ились _output/_reader;
                # sounddevice освобождает устройство через sd.stop()/sd.close().
                self._is_playing = False
            finally:
                self._cleaning_up = False

    def close(self) -> None:
        """Освобождение ресурсов (порт Dispose)."""
        self.stop()

    def __enter__(self) -> "AudioPlayer":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
