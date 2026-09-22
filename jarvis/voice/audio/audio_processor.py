"""Профессиональная DSP-цепочка обработки голоса (TTS)
(порт JARVIS.Voice/Audio/AudioProcessor.cs).

Делает звук «кинематографичным»: тёплый бас, чёткая подача, глубина.
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


class AudioProcessor:
    """Статический класс: DSP-обработка голоса TTS (порт AudioProcessor.cs)."""

    @staticmethod
    def process(input_wav_path: str) -> str:
        """Полная обработка WAV-файла: ресемплинг → EQ → компрессия → нормализация → лимитер."""
        try:
            input_path = Path(input_wav_path)
            if not input_path.exists():
                return input_wav_path

            # C#: Path.GetDirectoryName(inputWavPath) ?? Path.GetTempPath()
            output_dir = input_path.parent or Path(tempfile.gettempdir())
            output_path = output_dir / f"processed_{input_path.name}"

            input_rate, samples = _read_all_float(input_path)

            # Ресемплинг до 44100 Hz если нужно
            target_rate = 44100 if input_rate < 44100 else input_rate
            if input_rate != target_rate:
                samples = _resample(samples, input_rate, target_rate)

            # === Кинематографичная DSP-цепочка (баритон) ===

            # 1. HPF: убираем гул и комнатный румбл ниже 75 Гц
            _apply_high_pass(samples, target_rate, 75.0)

            # 2. Шумовой гейт: подавляет шипение/фон в паузах (до нормализации)
            _apply_noise_gate(samples, target_rate, threshold_db=-42.0, reduction_db=14.0)

            # 3. Чистка «эхо» и шума:
            #    - Срез боксовой резонансной составляющей (350 Гц -3 dB) — убирает «комнатность»
            #    - Десессер (6.5 кГц -2.5 dB) — убирает шипение/свист
            _apply_biquad_peak(samples, target_rate, 350.0, -3.0, 1.1)
            _apply_biquad_peak(samples, target_rate, 6500.0, -2.5, 1.6)

            # 4. Кинематографичный EQ:
            #    - Низкий бас (120 Гц +3.0 dB) — «бархатистость»
            #    - Тепло (250 Гц +1.5 dB) — наполненность
            #    - Присутствие (2.8 кГц +2.0 dB) — чёткая дикция
            #    - Воздух (9 кГц +0.5 dB) — лёгкость (снижено, меньше шипения)
            _apply_cinematic_eq(samples, target_rate)

            # 5. Мульти-компрессор: два слоя для «давления»
            #    - Мягкий: 3:1, -20 dBFS (выравнивает)
            #    - Жёсткий: 6:1, -12 dBFS (сжимает пики)
            _apply_compressor(samples, target_rate, threshold_db=-20.0, ratio=3.0)
            _apply_compressor(samples, target_rate, threshold_db=-12.0, ratio=6.0)

            # 6. Нормализация пика -1.5 dBFS (максимальная громкость)
            _normalize(samples, target_peak_db=-1.5)

            # 7. Мягкий лимитер -0.3 dBFS
            _apply_soft_limiter(samples, ceiling_db=-0.3)

            # 8. Гейт на выходе: добивает остаточный шип в тишине (после нормализации)
            _apply_noise_gate(samples, target_rate, threshold_db=-50.0, reduction_db=18.0)

            # Запись в WAV (WaveFormat(targetRate, 16, 1))
            _write_wav_16bit(output_path, target_rate, samples)

            return str(output_path)
        except Exception as ex:  # noqa: BLE001 — дословно как в C#
            print(f"[AudioProcessor] Ошибка обработки: {ex}")
            return input_wav_path


# ─── Утилиты ────────────────────────────────────────────────


def _resample(input_samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Линейная интерполяция (дословный порт AudioProcessor.Resample)."""
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


# ─── DSP-фильтры (in-memory) ────────────────────────────────


def _apply_high_pass(samples: np.ndarray, sample_rate: int, cutoff_hz: float) -> None:
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt = 1.0 / sample_rate
    a = np.float32(rc / (rc + dt))
    prev_in = np.float32(0.0)
    prev_out = np.float32(0.0)

    for i in range(len(samples)):
        sample_in = samples[i]
        out = a * (prev_out + sample_in - prev_in)
        prev_in = sample_in
        prev_out = out
        samples[i] = out


def _apply_cinematic_eq(samples: np.ndarray, sample_rate: int) -> None:
    # Кинематографичный EQ: 4 полосы для глубокого баритона
    bands = (
        (120.0, 3.0, 1.0),   # Низкий бас — «бархатистость»
        (250.0, 1.5, 1.2),   # Тепло — наполненность голоса
        (2800.0, 2.0, 1.4),  # Присутствие — чёткая дикция
        (9000.0, 0.5, 0.8),  # Воздух — лёгкость (умеренно, без шипения)
    )

    for hz, gain_db, q in bands:
        _apply_biquad_peak(samples, sample_rate, hz, gain_db, q)


def _apply_noise_gate(
    samples: np.ndarray, sample_rate: int, threshold_db: float, reduction_db: float
) -> None:
    """Шумовой гейт с плавной атакой/спадом — подавляет фон в паузах без щелчков."""
    threshold = 10.0 ** (threshold_db / 20.0)
    closed_gain = 10.0 ** (-reduction_db / 20.0)

    # Огибающая: быстрая атака 3ms, медленный спад 120ms (не режет хвосты слов)
    env_attack = math.exp(-1.0 / (0.003 * sample_rate))
    env_release = math.exp(-1.0 / (0.120 * sample_rate))
    # Плавность гейта: открытие 5ms, закрытие 80ms (без щелчков)
    open_coeff = math.exp(-1.0 / (0.005 * sample_rate))
    close_coeff = math.exp(-1.0 / (0.080 * sample_rate))

    envelope = 0.0
    gain = 1.0

    for i in range(len(samples)):
        abs_val = abs(float(samples[i]))
        env_coeff = env_attack if abs_val > envelope else env_release
        envelope = env_coeff * envelope + (1.0 - env_coeff) * abs_val

        target_gain = 1.0 if envelope >= threshold else closed_gain
        coeff = open_coeff if target_gain > gain else close_coeff
        gain = coeff * gain + (1.0 - coeff) * target_gain

        samples[i] = np.float32(samples[i] * gain)


def _apply_biquad_peak(
    samples: np.ndarray, sample_rate: int, center_hz: float, gain_db: float, q: float
) -> None:
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * center_hz / sample_rate
    sin_w0 = math.sin(w0)
    cos_w0 = math.cos(w0)
    alpha = sin_w0 / (2.0 * q)

    b0 = (1.0 + alpha * a) / (1.0 + alpha / a)
    b1 = (-2.0 * cos_w0) / (1.0 + alpha / a)
    b2 = (1.0 - alpha * a) / (1.0 + alpha / a)
    a1 = (-2.0 * cos_w0) / (1.0 + alpha / a)
    a2 = (1.0 - alpha / a) / (1.0 + alpha / a)

    x1 = x2 = y1 = y2 = 0.0

    for i in range(len(samples)):
        x = float(samples[i])
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        x1 = x
        y2 = y1
        y1 = y
        samples[i] = np.float32(y)


def _apply_compressor(
    samples: np.ndarray, sample_rate: int, threshold_db: float, ratio: float
) -> None:
    threshold = 10.0 ** (threshold_db / 20.0)
    attack_coeff = math.exp(-1.0 / (0.003 * sample_rate))   # Быстрый attack 3ms
    release_coeff = math.exp(-1.0 / (0.250 * sample_rate))  # Медленный release 250ms — сохраняет хвост слов
    envelope = 0.0

    for i in range(len(samples)):
        x = float(samples[i])
        abs_val = abs(x)

        coeff = attack_coeff if abs_val > envelope else release_coeff
        envelope = coeff * envelope + (1.0 - coeff) * abs_val

        if envelope > threshold:
            gain = threshold + (envelope - threshold) / ratio
            applied = gain / envelope if envelope > 0 else 1.0
            samples[i] = np.float32(x * max(applied, 0.1))


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


def _apply_soft_limiter(samples: np.ndarray, ceiling_db: float) -> None:
    ceiling = np.float32(10.0 ** (ceiling_db / 20.0))
    for i in range(len(samples)):
        x = samples[i]
        abs_val = abs(x)
        if abs_val > ceiling:
            sign = np.float32(1.0) if x > 0 else np.float32(-1.0)
            samples[i] = sign * np.float32(math.tanh(abs_val / ceiling * 2.0) * ceiling)
