"""DSP-цепочка обработки голоса (TTS)
(порт JARVIS.Voice/Audio/AudioProcessor.cs).

Ровно столько обработки, сколько нужно для качественного звука: качественный
sinc-ресемплинг до частоты устройства, чистка низа/шипения, умеренный EQ и
страховка по пикам. **Компрессора здесь нет**: 2.5:1 при пороге −18 dBFS плюс
нормализация всего файла «зажимали» динамику речи — на слух это и есть
«очень компрессированный звук» (см. §13 отчёта VOICE_PERF_STABILITY_ANALYSIS).

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

# Частота по умолчанию для ресемплинга: нативная частота большинства звуковых
# устройств. Панель играет через sounddevice (PortAudio), а он при несовпадении
# частот ресемплит своим слабым ресемплером — источник «металла» на выходе.
DEFAULT_SAMPLE_RATE = 44100

# Длина sinc-ядра (качество/скорость) и параметр Kaiser-окна.
_RESAMPLE_TAPS = 64
_KAISER_BETA = 8.0


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
    def process(input_wav_path: str, target_sample_rate: int = DEFAULT_SAMPLE_RATE) -> str:
        """Ресемплинг → HPF → корректирующий EQ → EQ → страховка по пикам → лимитер.

        Про ресемплинг. Piper отдаёт 22050 Гц, а у звуковых устройств нативная
        частота обычно 44100/48000. Если отдать 22050 как есть, конвертировать
        будет аудио-движок (PortAudio/WASAPI) — своим слабым ресемплером, и это
        даёт «металлический» призвук на выходе. Прежний апсемпл линейной
        интерполяцией давал тот же артефакт, только в файле (зеркальная копия
        спектра выше 11 кГц).

        Поэтому ресемплим сами — оконным sinc-фильтром (Kaiser, с
        анти-алиасингом). Замер: энергия выше 11 кГц −54 дБ против −51 дБ
        у «сырых» 22050 и −28 дБ у линейной интерполяции.
        """
        try:
            input_path = Path(input_wav_path)
            if not input_path.exists():
                return input_wav_path

            # C#: Path.GetDirectoryName(inputWavPath) ?? Path.GetTempPath()
            output_dir = input_path.parent or Path(tempfile.gettempdir())
            output_path = output_dir / f"processed_{input_path.name}"

            sample_rate, samples = _read_all_float(input_path)

            # Ресемплинг ДО фильтров: DSP считается уже на частоте устройства,
            # чтобы биквады работали на своих целевых частотах.
            if target_sample_rate > 0 and target_sample_rate != sample_rate:
                samples = _resample_sinc(samples, sample_rate, target_sample_rate)
                sample_rate = target_sample_rate

            # === DSP-цепочка (баритон, без артефактов и без компрессии) ===

            # 1. HPF: убираем гул и комнатный румбл ниже 75 Гц
            _apply_high_pass(samples, sample_rate, 75.0)

            # 2. Чистка «эхо» и шума:
            #    - Срез боксовой резонансной составляющей (350 Гц -3 dB) — убирает «комнатность»
            #    - Десессер (6.5 кГц -2.5 dB) — убирает шипение/свист
            _apply_biquad_peak(samples, sample_rate, 350.0, -3.0, 1.1)
            _apply_biquad_peak(samples, sample_rate, 6500.0, -2.5, 1.6)

            # 3. Кинематографичный EQ (умеренный: без «бочки» и без шипения)
            _apply_cinematic_eq(samples, sample_rate)

            # 3.5. Мягкий ФНЧ 8 кГц: у Piper выше 6 кГц заметная шумовая
            #      составляющая — на слух это «шипит/свистит/металл». Ниже
            #      6 кГц полка почти не тронута (разборчивость цела), а 8-11 кГц
            #      гасятся на 3–7 дБ.
            _apply_low_pass(samples, sample_rate, 8000.0)

            # 4. Компрессора больше нет. Было 2.5:1 при пороге −18 dBFS (то есть
            #    выше порога оказывалась почти вся речь) плюс нормализация всего
            #    файла — динамика «зажималась», и озвучка звучала перекомпресси-
            #    рованной. TTS-движок и так отдаёт выровненный по громкости голос.

            # 5. Страховка по пикам: только ослабление, тихое не поднимаем —
            #    иначе это снова было бы выравнивание громкости (компрессия).
            _attenuate_peak(samples, ceiling_db=-1.0)

            # 6. Мягкий лимитер -0.5 dBFS
            _apply_soft_limiter(samples, ceiling_db=-0.5)

            # Запись в WAV на частоте устройства (sample_rate после ресемплинга)
            _write_wav_16bit(output_path, sample_rate, samples)

            return str(output_path)
        except Exception as ex:  # noqa: BLE001 — дословно как в C#
            print(f"[AudioProcessor] Ошибка обработки: {ex}")
            return input_wav_path


# ─── Ресемплинг ─────────────────────────────────────────────


def _bessel_i0(x: float) -> float:
    """Модифицированная функция Бесселя первого рода нулевого порядка (окно Kaiser)."""
    total = 1.0
    term = 1.0
    half_x = x / 2.0

    for k in range(1, 64):
        term *= (half_x / k) * (half_x / k)
        total += term

        if term < total * 1e-16:
            break

    return total


def _kaiser_window(taps: int, beta: float) -> np.ndarray:
    """Kaiser-окно длиной taps (как в C#-версии)."""
    i0_beta = _bessel_i0(beta)
    k = np.arange(taps)
    t = 2.0 * k / (taps - 1) - 1.0
    return np.array(
        [_bessel_i0(beta * math.sqrt(max(0.0, 1.0 - v * v))) / i0_beta for v in t],
        dtype=np.float64,
    )


def _resample_sinc(input_samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Качественный ресемплинг оконным sinc-фильтром (Kaiser).

    В отличие от линейной интерполяции (была здесь раньше) sinc давит
    зеркальные составляющие: при апсемпле 22050→44100 линейная интерполяция
    добавляла копию спектра выше 11 кГц (энергия −28 дБ от основного
    диапазона — слышимый «металл»), sinc-ядро с анти-алиасингом даёт −54 дБ.

    cutoff = min(1, to/from) — при апсемпле 1 (анти-алиасинг не нужен),
    при даунсемпле — относительная частота Найквиста нового диапазона.
    """
    if len(input_samples) == 0 or from_rate <= 0 or to_rate <= 0 or from_rate == to_rate:
        return input_samples

    ratio = to_rate / from_rate
    output_length = int(math.floor(len(input_samples) * ratio))

    if output_length <= 0:
        return input_samples

    taps = _RESAMPLE_TAPS
    half = taps // 2
    cutoff = min(1.0, ratio)
    window = _kaiser_window(taps, _KAISER_BETA)
    output = np.zeros(output_length, dtype=np.float32)

    for i in range(output_length):
        pos = i / ratio                      # позиция во входном сигнале
        start = int(math.floor(pos)) - half
        idx = np.arange(start, start + taps)
        frac = pos - idx

        # sinc с окном; в нуле — предел 1
        s = np.where(np.abs(frac * cutoff) < 1e-9, 1.0, np.sinc(frac * cutoff)) * window

        valid = (idx >= 0) & (idx < len(input_samples))

        if not np.any(valid):
            continue

        norm = s[valid].sum()
        # Нормировка на сумму весов: края сигнала иначе «проседают».
        output[i] = np.dot(input_samples[idx[valid]], s[valid]) / norm if norm != 0 else 0.0

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


def _apply_low_pass(
    samples: np.ndarray, sample_rate: int, cutoff_hz: float, q: float = 0.707
) -> None:
    """Мягкий ФНЧ 2-го порядка (RBJ, Баттерворт): режет шипение и «металл».

    АЧФ (fc = 8 кГц): 3 кГц −0.05 дБ, 6 кГц −1.0 дБ, 8 кГц −3.0 дБ,
    11 кГц −6.4 дБ. То есть присутствие и разборчивость не страдают, а
    шумовая составляющая Piper выше 6 кГц (её и слышно как шип/свист)
    уходит вниз.
    """
    w0 = 2.0 * math.pi * cutoff_hz / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * q)

    a0 = 1.0 + alpha
    b0 = ((1.0 - cos_w0) / 2.0) / a0
    b1 = (1.0 - cos_w0) / a0
    b2 = b0
    a1 = (-2.0 * cos_w0) / a0
    a2 = (1.0 - alpha) / a0

    x1 = x2 = y1 = y2 = 0.0

    for i in range(len(samples)):
        x = float(samples[i])
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        x1 = x
        y2 = y1
        y1 = y
        samples[i] = np.float32(y)


def _attenuate_peak(samples: np.ndarray, ceiling_db: float) -> None:
    """Ослабляет файл, если пик выше потолка; тихое не поднимает.

    Заменяет прежнюю нормализацию «пик в −3 dBFS»: та поднимала громкость
    всего файла и вместе с компрессором выравнивала динамику на слух.
    Здесь только страховка от клиппинга — динамика голоса остаётся как в TTS.
    """
    ceiling = np.float32(10.0 ** (ceiling_db / 20.0))
    peak = _FLOAT_EPSILON

    for i in range(len(samples)):
        abs_val = abs(float(samples[i]))
        if abs_val > peak:
            peak = abs_val

    if peak <= ceiling:
        return

    gain = ceiling / np.float32(peak)

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
