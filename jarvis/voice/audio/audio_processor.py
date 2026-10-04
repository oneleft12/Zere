"""DSP-цепочка обработки голоса (TTS)
(порт JARVIS.Voice/Audio/AudioProcessor.cs).

Делает звук плотнее и «кинематографичнее», но без артефактов: один мягкий
компрессор вместо каскада, без шумовых гейтов и без апсемплинга.
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
        """HPF → корректирующий EQ → EQ → компрессия → нормализация → лимитер.

        Ресемплинга здесь нет намеренно: piper отдаёт 22050 Гц, а прежний
        апсемпл 22050→44100 линейной интерполяцией (без анти-imaging фильтра)
        добавлял зеркальную копию спектра выше 11 кГц — это и был
        «металлический» призвук. Частота сохраняется как есть, ресемплинг
        отдан аудио-движку ОС.
        """
        try:
            input_path = Path(input_wav_path)
            if not input_path.exists():
                return input_wav_path

            # C#: Path.GetDirectoryName(inputWavPath) ?? Path.GetTempPath()
            output_dir = input_path.parent or Path(tempfile.gettempdir())
            output_path = output_dir / f"processed_{input_path.name}"

            sample_rate, samples = _read_all_float(input_path)

            # === DSP-цепочка (баритон, без артефактов) ===

            # 1. HPF: убираем гул и комнатный румбл ниже 75 Гц
            _apply_high_pass(samples, sample_rate, 75.0)

            # 2. Чистка «эхо» и шума:
            #    - Срез боксовой резонансной составляющей (350 Гц -3 dB) — убирает «комнатность»
            #    - Десессер (6.5 кГц -2.5 dB) — убирает шипение/свист
            _apply_biquad_peak(samples, sample_rate, 350.0, -3.0, 1.1)
            _apply_biquad_peak(samples, sample_rate, 6500.0, -2.5, 1.6)

            # 3. Кинематографичный EQ (умеренный: без «бочки» и без шипения)
            _apply_cinematic_eq(samples, sample_rate)

            # 4. ОДИН мягкий компрессор 2.5:1 @ -18 dBFS.
            #    Атака 20 мс (было 3 мс): на 3 мс усиление успевало промодулироваться
            #    внутри периода голоса (~8 мс), что и давало металлическую грязь.
            #    Раньше здесь стояли ДВА компрессора подряд (3:1 и 6:1) — это была
            #    та самая «перекомпрессия».
            _apply_compressor(
                samples, sample_rate, threshold_db=-18.0, ratio=2.5,
                attack_ms=20.0, release_ms=250.0,
            )

            # 5. Нормализация пика -3 dBFS: запас по динамике вместо «стены» на -1.5
            _normalize(samples, target_peak_db=-3.0)

            # 6. Мягкий лимитер -0.5 dBFS
            _apply_soft_limiter(samples, ceiling_db=-0.5)

            # Запись в WAV на исходной частоте (без ресемплинга)
            _write_wav_16bit(output_path, sample_rate, samples)

            return str(output_path)
        except Exception as ex:  # noqa: BLE001 — дословно как в C#
            print(f"[AudioProcessor] Ошибка обработки: {ex}")
            return input_wav_path


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
    # Кинематографичный EQ: 4 полосы (гейны умеренные — громкость даёт
    # нормализация, а не подъём полос)
    bands = (
        (120.0, 2.0, 1.0),   # Низкий бас — «бархатистость»
        (250.0, 1.0, 1.2),   # Тепло — наполненность голоса
        (2800.0, 1.5, 1.4),  # Присутствие — чёткая дикция
        (9000.0, 0.5, 0.8),  # Воздух — лёгкость (умеренно, без шипения)
    )

    for hz, gain_db, q in bands:
        _apply_biquad_peak(samples, sample_rate, hz, gain_db, q)


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
    samples: np.ndarray, sample_rate: int, threshold_db: float, ratio: float,
    attack_ms: float, release_ms: float,
) -> None:
    """Один мягкий компрессор с медленной атакой: выравнивает громкость фразы,
    но не трогает форму волны внутри периода голоса (иначе — «металл»)."""
    threshold = 10.0 ** (threshold_db / 20.0)
    attack_coeff = math.exp(-1.0 / (attack_ms / 1000.0 * sample_rate))
    release_coeff = math.exp(-1.0 / (release_ms / 1000.0 * sample_rate))
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
