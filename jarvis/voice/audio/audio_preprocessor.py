"""Предобработка аудио для Whisper STT (порт JARVIS.Voice/Audio/AudioPreprocessor.cs).

Убирает шум, выравнивает громкость, фильтрует частоты.
NAudio (AudioFileReader/WaveFileWriter) заменён на stdlib wave + numpy.
"""

from __future__ import annotations

import math
import tempfile
import wave
from pathlib import Path

import numpy as np

# Аналог float.Epsilon в C# (наименьшее положительное значение float)
_FLOAT_EPSILON = 1.401298464324817e-45


def _read_all_float(path: Path) -> tuple[int, np.ndarray]:
    """Читает WAV в float-сэмплы (аналог AudioFileReader + ReadAllFloat)."""
    with wave.open(str(path), "rb") as reader:
        sample_rate = reader.getframerate()
        samp_width = reader.getsampwidth()
        n_channels = reader.getnchannels()
        raw = reader.readframes(reader.getnframes())

    if samp_width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif samp_width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif samp_width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif samp_width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (
            b[:, 0].astype(np.int32)
            | (b[:, 1].astype(np.int32) << 8)
            | (b[:, 2].astype(np.int32) << 16)
        )
        ints = np.where(ints >= 0x800000, ints - 0x1000000, ints)
        samples = ints.astype(np.float32) / 8388608.0
    else:
        raise ValueError(f"Неподдерживаемая битность WAV: {samp_width * 8} бит")

    # Стерео-сэмплы читаются interleaved (как ISampleProvider в NAudio)
    if n_channels > 1:
        samples = samples.reshape(-1)

    return sample_rate, samples


def _write_wav_16bit(path: Path, sample_rate: int, samples: np.ndarray) -> None:
    """Записывает float-сэмплы в 16-bit mono WAV (аналог WaveFileWriter.WriteSample)."""
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        clamped = np.clip(samples, -1.0, 1.0)
        # (short)(sample * 32767) в C# — усечение к нулю, как astype(np.int16)
        writer.writeframes((clamped * 32767.0).astype(np.int16).tobytes())


class AudioPreprocessor:
    """Статический класс: предобработка аудио для Whisper STT (порт AudioPreprocessor.cs)."""

    @staticmethod
    def process_for_whisper(input_wav_path: str) -> str:
        """Подготавливает WAV-файл для Whisper: ресемплинг → шумоподавление → нормализация."""
        try:
            input_path = Path(input_wav_path)
            if not input_path.exists():
                return input_wav_path

            # C#: Path.GetDirectoryName(inputWavPath) ?? Path.GetTempPath()
            output_dir = input_path.parent or Path(tempfile.gettempdir())
            output_path = output_dir / f"whisper_input_{input_path.name}"

            # Читаем все сэмплы как float (аналог AudioFileReader)
            input_rate, samples = _read_all_float(input_path)

            # Ресемплинг до 16 kHz (линейная интерполяция — достаточно для речи)
            if input_rate != 16000:
                samples = _resample(samples, input_rate, 16000)

            # Noise Gate
            _apply_noise_gate(samples, 16000, threshold_db=-40.0)

            # AGC
            _apply_agc(samples, target_level_db=-3.0, max_gain_db=30.0)

            # EQ: усиление полосы речи
            # (пропускаем — для in-memory Biquad нужна отдельная реализация)

            # Soft Limiter
            _apply_soft_limiter(samples, ceiling_db=-1.0)

            # Нормализация
            _normalize(samples, target_peak_db=-1.0)

            # Запись в 16-bit mono 16kHz
            _write_wav_16bit(output_path, 16000, samples)

            return str(output_path)
        except Exception as ex:  # noqa: BLE001 — дословно как в C#
            print(f"[AudioPreprocessor] Ошибка: {ex}")
            return input_wav_path


def _resample(input_samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Линейная интерполяция (дословный порт AudioPreprocessor.Resample)."""
    if from_rate == to_rate:
        return input_samples

    ratio = from_rate / to_rate
    output_length = int(len(input_samples) / ratio)
    output = np.zeros(output_length, dtype=np.float32)

    for i in range(output_length):
        pos = i * ratio
        idx = int(pos)
        frac = np.float32(pos - idx)

        if idx + 1 < len(input_samples):
            output[i] = input_samples[idx] * (np.float32(1.0) - frac) + input_samples[idx + 1] * frac
        else:
            output[i] = input_samples[idx]
    return output


def _apply_noise_gate(samples: np.ndarray, sample_rate: int, threshold_db: float) -> None:
    threshold = np.float32(10.0 ** (threshold_db / 20.0))
    attack_coeff = np.float32(math.exp(-1.0 / (0.001 * sample_rate)))
    release_coeff = np.float32(math.exp(-1.0 / (0.050 * sample_rate)))
    envelope = np.float32(0.0)
    gate_open = False

    for i in range(len(samples)):
        abs_val = abs(samples[i])
        coeff = attack_coeff if abs_val > envelope else release_coeff
        envelope = coeff * envelope + (np.float32(1.0) - coeff) * abs_val

        if envelope > threshold:
            gate_open = True
        elif envelope < threshold * np.float32(0.5):
            gate_open = False

        if not gate_open:
            samples[i] *= np.float32(0.01)


def _apply_agc(samples: np.ndarray, target_level_db: float, max_gain_db: float) -> None:
    target = np.float32(10.0 ** (target_level_db / 20.0))
    max_gain = np.float32(10.0 ** (max_gain_db / 20.0))
    gain = np.float32(1.0)
    envelope = np.float32(0.0)

    for i in range(len(samples)):
        abs_val = abs(samples[i])
        envelope = np.float32(0.999) * envelope + np.float32(0.001) * abs_val

        if envelope > np.float32(0.001):
            desired = min(target / envelope, max_gain)
            gain = np.float32(0.998) * gain + np.float32(0.002) * desired

        samples[i] *= gain


def _apply_soft_limiter(samples: np.ndarray, ceiling_db: float) -> None:
    ceiling = np.float32(10.0 ** (ceiling_db / 20.0))
    for i in range(len(samples)):
        x = samples[i]
        abs_val = abs(x)
        if abs_val > ceiling:
            sign = np.float32(1.0) if x > 0 else np.float32(-1.0)
            samples[i] = sign * np.float32(math.tanh(abs_val / ceiling * 2.0) * ceiling)


def _normalize(samples: np.ndarray, target_peak_db: float) -> None:
    target = np.float32(10.0 ** (target_peak_db / 20.0))
    peak = _FLOAT_EPSILON
    for i in range(len(samples)):
        abs_val = abs(float(samples[i]))
        if abs_val > peak:
            peak = abs_val
    if peak < _FLOAT_EPSILON:
        return
    gain = target / np.float32(peak)
    for i in range(len(samples)):
        samples[i] *= gain
