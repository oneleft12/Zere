"""Модель слова-триггера: frontend (log-mel) + крошечная CNN + экспорт в ONNX.

ЗАМОРОЖЕННЫЙ КОНТРАКТ (его читают рантаймы обеих редакций):

* вход ``audio`` — float32, форма ``(batch, 16000)``, значения в [-1, 1];
* выход ``score`` — float32, форма ``(batch, 1)``, сигмоида-вероятность слова;
* окно ровно 1.0 с при 16 кГц, шаг рантайма 40 мс (640 сэмплов) — сам шаг
  живёт в рантайме, в графе окно фиксированное.

Frontend живёт ВНУТРИ графа (STFT → мел → лог → пер-оконная нормализация),
поэтому C#-редакции не нужно повторять математику: она получает вероятность
прямо из сырого аудио.

Почему STFT — это ``Conv1d`` с явной матрицей базиса ДПФ, а не
``torch.stft``/``torch.fft.rfft``: FFT-операторы экспортируются в ONNX как
``DFT``/``STFT``, поддержка которых в onnxruntime различается по версиям и
провайдерам (на CPUExecutionProvider старых сборок оператора просто нет).
Свёртка с базисом ДПФ — это обычный ``Conv``, он есть везде и считается
быстро (для кадра 256 точек это дешевле общего FFT).

Почему базис — буфер, а не обучаемый вес: это математическая константа, её
нельзя портить градиентом. ``requires_grad=False`` + буфер = константа в
графе (initializer), которую видно при разборе ONNX.

Проверка корректности: :func:`reference_features` считает те же признаки
через numpy-FFT (независимая реализация) — на ней стоит :mod:`self_test`.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

# Контракт (константы аудио/признаков и манифест) живёт в torch-свободном
# модуле contract.py и переэкспортируется отсюда: сборочные скрипты, которым
# torch не нужен, импортируют contract напрямую, а прежние импорты вида
# ``from tools.wake_word.model import SAMPLE_RATE`` продолжают работать.
from tools.wake_word.contract import (
    DEFAULT_COOLDOWN_MS,
    DEFAULT_MIN_CONSECUTIVE,
    DEFAULT_THRESHOLD,
    FMAX,
    FMIN,
    HOP_LENGTH,
    HOP_SAMPLES,
    INPUT_NAME,
    LOG_EPS,
    N_FFT,
    N_FRAMES,
    N_MELS,
    NORM_EPS,
    ONNX_OPSET,
    OUTPUT_NAME,
    SAMPLE_RATE,
    WINDOW_SAMPLES,
    WIN_LENGTH,
    Manifest,
    utc_now_iso,
    word_slug,
)

# ─── Мел-шкала Slaney (как librosa htk=False, norm='slaney') ────


def hz_to_mel(freqs: torch.Tensor) -> torch.Tensor:
    """Герцы → мел по Слэйни (librosa ``htk=False``).

    До 1 кГц шкала линейна, выше — логарифмическая. Это не «мел HTK»:
    librosa по умолчанию использует именно вариант Слэйни, и расхождение с
    HTK-формулой на 8 кГц заметное, поэтому формула выписана явно.
    """
    f_sp = 200.0 / 3.0
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp  # 15.0
    logstep = math.log(6.4) / 27.0

    linear = freqs / f_sp
    log_part = min_log_mel + torch.log(freqs / min_log_hz) / logstep

    return torch.where(freqs >= min_log_hz, log_part, linear)


def mel_to_hz(mels: torch.Tensor) -> torch.Tensor:
    """Мел → герцы по Слэйни (обратная к :func:`hz_to_mel`)."""
    f_sp = 200.0 / 3.0
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = math.log(6.4) / 27.0

    linear = f_sp * mels
    log_part = min_log_hz * torch.exp(logstep * (mels - min_log_mel))

    return torch.where(mels >= min_log_mel, log_part, linear)


def mel_filterbank(sample_rate: int = SAMPLE_RATE, n_fft: int = N_FFT,
                   n_mels: int = N_MELS, fmin: float = FMIN,
                   fmax: float = FMAX) -> torch.Tensor:
    """Треугольные мел-фильтры ``(n_mels, 1 + n_fft // 2)`` как в librosa.

    Повторяет ``librosa.filters.mel(..., htk=False, norm='slaney')``:
    треугольники в мел-пространстве, затем area-нормировка ``2 / (f[i+2] -
    f[i])``. Нормировка важна: без неё высокие фильтры (широкие в герцах)
    дают завышенную энергию и перекосут обучение в ВЧ-шум.
    """
    mel_points = torch.linspace(
        float(hz_to_mel(torch.tensor(fmin))),
        float(hz_to_mel(torch.tensor(fmax))),
        n_mels + 2,
    )
    hz_points = mel_to_hz(mel_points)

    fft_freqs = torch.linspace(0.0, sample_rate / 2.0, 1 + n_fft // 2)

    # ramps[i, j] = hz_points[i] - fft_freqs[j] — расстояния «опора минус бина».
    ramps = hz_points.unsqueeze(1) - fft_freqs.unsqueeze(0)

    fdiff = hz_points[1:] - hz_points[:-1]
    weights = torch.zeros(n_mels, fft_freqs.numel())

    for index in range(n_mels):
        lower = -ramps[index] / fdiff[index]
        upper = ramps[index + 2] / fdiff[index + 1]
        weights[index] = torch.clamp(torch.minimum(lower, upper), min=0.0)

    enorm = 2.0 / (hz_points[2:n_mels + 2] - hz_points[:n_mels])
    weights = weights * enorm.unsqueeze(1)

    return weights


def dft_basis(n_fft: int = N_FFT, win_length: int = WIN_LENGTH) -> torch.Tensor:
    """Матрица базиса ДПФ, свёрнутая с окном Ханна: ``(2 * (n_fft//2+1), 1, win)``.

    Каналы идут как «сначала все real (129), потом все imag (129)» — так их
    потом дешевле разрезать. Окно Ханна периодическое (``periodic=True``):
    именно его использует librosa по умолчанию, и непериодическое окно дало бы
    систематическую ошибку на краях кадра.
    """
    sample_index = torch.arange(win_length, dtype=torch.float64)
    bin_index = torch.arange(n_fft // 2 + 1, dtype=torch.float64).unsqueeze(1)

    angle = 2.0 * math.pi * bin_index * sample_index.unsqueeze(0) / n_fft
    window = torch.hann_window(win_length, periodic=True, dtype=torch.float64)

    real = torch.cos(angle) * window
    # X[k] = Σ x[n]·e^{-j2πkn/N} = Σ x·cos − j·Σ x·sin, поэтому мнимая часть
    # базиса берётся со знаком минус.
    imag = -torch.sin(angle) * window

    stacked = torch.stack([real, imag], dim=0).reshape(2 * (n_fft // 2 + 1), win_length)

    return stacked.unsqueeze(1).to(torch.float32)


# ─── Frontend ───────────────────────────────────────────────────


class LogMelFrontend(nn.Module):
    """Сырое аудио ``(B, 16000)`` → нормированный log-mel ``(B, 1, 40, 99)``.

    Шаги (все внутри графа): Conv1d-ДПФ → мощность → мел-фильтры → ln(x+1e-6)
    → пер-оконная нормализация по всем 40×99 значениям окна.

    Нормализация обязательна: абсолютная громкость микрофона у всех разная
    (и меняется от «близко» к «далеко»), а решению нужна форма спектра, а не
    уровень. После нормализации окно тишины и окно громкой речи отличаются
    только структурой.
    """

    def __init__(self, n_fft: int = N_FFT, win_length: int = WIN_LENGTH,
                 hop_length: int = HOP_LENGTH, n_mels: int = N_MELS,
                 sample_rate: int = SAMPLE_RATE) -> None:
        super().__init__()

        self.n_fft = n_fft
        self.win_length = win_length
        self.hop_length = hop_length
        self.n_mels = n_mels
        self.sample_rate = sample_rate
        self.n_freqs = n_fft // 2 + 1

        basis = dft_basis(n_fft, win_length)
        mel = mel_filterbank(sample_rate, n_fft, n_mels)

        # Буферы, а не параметры: это константы, они попадают в ONNX как
        # initializer и не могут быть испорчены оптимизатором.
        self.register_buffer("dft_weight", basis, persistent=True)
        self.register_buffer("mel_basis", mel, persistent=True)

    def stft_power(self, audio: torch.Tensor) -> torch.Tensor:
        """Мощность спектра ``(B, 129, T)`` через свёртку с базисом ДПФ."""
        frames = audio.unsqueeze(1)  # (B, 1, N)

        spectrum = F.conv1d(frames, self.dft_weight, stride=self.hop_length)

        real = spectrum[:, :self.n_freqs, :]
        imag = spectrum[:, self.n_freqs:, :]

        return real * real + imag * imag

    def forward(self, audio: torch.Tensor) -> torch.Tensor:
        """Аудио → признаки ``(B, 1, n_mels, T)``, готовые для Conv2d."""
        if audio.dim() != 2:
            raise ValueError(
                f"ожидается аудио формы (batch, samples), получено {tuple(audio.shape)}"
            )

        power = self.stft_power(audio)  # (B, 129, T)

        # (n_mels, 129) @ (B, 129, T) → (B, n_mels, T)
        mel_power = torch.matmul(self.mel_basis, power)

        log_mel = torch.log(mel_power + LOG_EPS)

        # Пер-оконная нормализация: среднее и std по ВСЕМ 40×99 значениям
        # одного окна, независимо для каждого элемента батча.
        mean = log_mel.mean(dim=(1, 2), keepdim=True)
        std = log_mel.std(dim=(1, 2), keepdim=True, unbiased=False)
        normalized = (log_mel - mean) / (std + NORM_EPS)

        return normalized.unsqueeze(1)


# ─── Классификатор ──────────────────────────────────────────────


class WakeWordNet(nn.Module):
    """Frontend + CNN «аудио → вероятность слова».

    Архитектура намеренно простая (никакого внимания/RNN): ~55 тыс.
    параметров, чтобы модель считалась за единицы миллисекунд на CPU и
    помещалась в < 1 МБ ONNX. Для одного слова этого достаточно — задача
    слишком узкая, чтобы выигрывать от сложной модели, а задержка и размер
    тут важнее.

    Схема: Conv(1→32,3×3)+BN+ReLU → MaxPool2×2 → Conv(32→64)+BN+ReLU →
    MaxPool2×2 → Conv(64→64)+BN+ReLU → AdaptiveAvgPool → Linear(64→32)+ReLU+
    Dropout(0.1) → Linear(32→1)+Sigmoid.

    Выход — sigmoid, а не логит: контракт требует вероятность в [0, 1], а
    рантайм не должен помнить про сигмоиду. Обучение при этом считает
    BCEWithLogitsLoss по логитам (:meth:`forward_logits`), чтобы не терять
    численную устойчивость.
    """

    def __init__(self, n_mels: int = N_MELS, dropout: float = 0.1) -> None:
        super().__init__()

        self.frontend = LogMelFrontend(n_mels=n_mels)

        self.features = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),

            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),

            nn.Conv2d(64, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )

        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64, 32),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
        )

        #: Аугментация признаков (SpecAugment) — ставится из train.py
        #: (:class:`tools.wake_word.data.SpecAugment`). Живёт отдельным
        #: атрибутом, а не подмодулем: в ONNX она не должна попасть ни при
        #: каком раскладе, и вызывается ТОЛЬКО в режиме обучения.
        self.spec_augmenter: Any = None

    def forward_logits(self, audio: torch.Tensor) -> torch.Tensor:
        """Логиты ``(B, 1)`` — для BCEWithLogitsLoss (устойчивее сигмоиды)."""
        features = self.frontend(audio)

        if self.training and self.spec_augmenter is not None:
            features = self.spec_augmenter(features)

        return self.head(self.features(features))

    def forward(self, audio: torch.Tensor) -> torch.Tensor:
        """Вероятность ``(B, 1)`` — ровно то, что отдаёт ONNX."""
        return torch.sigmoid(self.forward_logits(audio))

    @property
    def parameter_count(self) -> int:
        """Число обучаемых параметров (для лога обучения)."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


# ─── Независимая проверка frontend ──────────────────────────────


def reference_features(audio: Any, n_mels: int = N_MELS) -> Any:
    """Те же log-mel признаки, но через numpy-FFT — независимая реализация.

    Нужна, чтобы поймать ошибку в матрице базиса ДПФ: если считать признаки
    тем же ``Conv1d``, тест проверял бы код сам собой. Здесь STFT делается
    через ``numpy.fft.rfft``, а мел-фильтры берутся из :func:`mel_filterbank`
    (она общая — но базис ДПФ проверяется по-настоящему независимо).

    Возвращает ``(n_mels, n_frames)`` нормированных значений.
    """
    import numpy as np  # noqa: PLC0415 — numpy нужен только тут

    signal = np.asarray(audio, dtype="float64").reshape(-1)

    window = np.hanning(WIN_LENGTH + 1)[:WIN_LENGTH]  # периодическое окно Ханна
    n_frames = 1 + (signal.size - WIN_LENGTH) // HOP_LENGTH

    frames = np.stack([
        signal[i * HOP_LENGTH: i * HOP_LENGTH + WIN_LENGTH] * window
        for i in range(n_frames)
    ])

    spectrum = np.fft.rfft(frames, n=N_FFT, axis=1)  # (T, 129)
    power = (spectrum.real ** 2 + spectrum.imag ** 2).T  # (129, T)

    mel = mel_filterbank(n_mels=n_mels).numpy().astype("float64")
    log_mel = np.log(mel @ power + LOG_EPS)

    mean = log_mel.mean()
    std = log_mel.std()  # population std = torch unbiased=False

    return (log_mel - mean) / (std + NORM_EPS)


# ─── Экспорт в ONNX ─────────────────────────────────────────────


class OnnxExportUnavailable(RuntimeError):
    """Экспорт в ONNX невозможен: не установлен пакет ``onnx``.

    ``onnx`` и ``onnxruntime`` — РАЗНЫЕ пакеты, и это регулярно путает:
    ``onnxruntime`` умеет только исполнять готовую модель, а для самой
    сериализации графа ``torch.onnx.export`` нужен ``onnx``. В рантайме он не
    нужен вовсе, поэтому требовать его заранее нельзя — но при экспорте
    отсутствие ``onnx`` обязано говорить об этом прямо, а не падать
    внутренней ошибкой ``torch`` вида ``Module onnx is not installed!``.
    """


#: Подсказка для пользователя — одинаковый текст в обоих местах проверки.
_ONNX_INSTALL_HINT = (
    "для экспорта модели в ONNX нужен пакет onnx (это НЕ onnxruntime —\n"
    "onnxruntime только исполняет готовую модель, а onnx сериализует граф).\n"
    "  Установка: python -m pip install onnx\n"
    "  В рантайме onnx не нужен: достаточно onnxruntime.\n"
    "  Если экспорт не нужен прямо сейчас, обучите без него: train.py --no-export"
)


def _require_onnx_package() -> None:
    """Проверяет наличие ``onnx`` ДО вызова экспорта (понятная ошибка)."""
    try:
        import onnx  # noqa: F401,PLC0415
    except ImportError as error:
        raise OnnxExportUnavailable(_ONNX_INSTALL_HINT) from error


def export_onnx(model: WakeWordNet, path: str | Path,
                opset: int = ONNX_OPSET) -> Path:
    """Экспортирует модель в ONNX: ``audio (B,16000) → score (B,1)``.

    Модель переводится в ``eval()``: BatchNorm должен использовать накопленную
    статистику, а Dropout и SpecAugment — выключиться. Иначе в графе остались
    бы случайные маски, и вероятность «дрожала» бы от запуска к запуску.

    Ось 0 объявлена динамической (батч), ось 1 фиксирована (окно 16000).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Проверяем заранее: сам torch падает невнятно, а иногда и после того, как
    # уже потратил время на трассировку модели.
    _require_onnx_package()

    was_training = model.training
    model.eval()

    # Экспорт всегда на CPU: dummy-вход создаётся здесь, и на CUDA-модели
    # torch падал на несовпадении устройств («weight is on cuda:0, different
    # from other tensors on cpu»). Сам ONNX-граф от устройства не зависит,
    # а CPU-экспорт воспроизводим; после экспорта модель возвращается.
    model_device = next(model.parameters()).device

    if model_device.type != "cpu":
        model.to("cpu")

    dummy = torch.zeros(1, WINDOW_SAMPLES, dtype=torch.float32)

    try:
        try:
            torch.onnx.export(
                model,
                (dummy,),
                str(target),
                input_names=[INPUT_NAME],
                output_names=[OUTPUT_NAME],
                dynamic_axes={INPUT_NAME: {0: "batch"}, OUTPUT_NAME: {0: "batch"}},
                opset_version=opset,
                do_constant_folding=True,
                dynamo=False,
            )
        except TypeError:
            # Старые/новые сборки torch по-разному принимают dynamo: если
            # аргумента нет — экспортируем традиционным путём.
            torch.onnx.export(
                model,
                (dummy,),
                str(target),
                input_names=[INPUT_NAME],
                output_names=[OUTPUT_NAME],
                dynamic_axes={INPUT_NAME: {0: "batch"}, OUTPUT_NAME: {0: "batch"}},
                opset_version=opset,
                do_constant_folding=True,
            )
    except Exception as error:  # noqa: BLE001 — уточняем причину по тексту
        # Вторая линия обороны: torch может сообщить об отсутствии onnx и
        # другим путём (OnnxExporterError с текстом «Module onnx is not
        # installed!»), например если пакет сломан, а не отсутствует.
        if "onnx is not installed" in str(error).lower():
            raise OnnxExportUnavailable(_ONNX_INSTALL_HINT) from error

        raise
    finally:
        if model_device.type != "cpu":
            model.to(model_device)

        if was_training:
            model.train()

    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"ONNX-модель не появилась по пути {target}")

    return target


def verify_onnx_parity(model: WakeWordNet, onnx_path: str | Path,
                       tolerance: float = 1e-3, seed: int = 0) -> float:
    """Сверяет torch и onnxruntime на случайном входе; возвращает max abs diff.

    Обязательный self-test контракта: граф содержит свой DSP, и если экспорт
    «поплыл» (например, потерялась нормализация или окно), рантайм молча
    выдавал бы мусорные вероятности. Допуск 1e-3 — на порядок выше реального
    расхождения (~1e-6) и ловит именно структурные ошибки.
    """
    import numpy as np  # noqa: PLC0415
    import onnxruntime as ort  # noqa: PLC0415

    rng = np.random.default_rng(seed)
    audio = rng.uniform(-1.0, 1.0, size=(2, WINDOW_SAMPLES)).astype("float32")

    model.eval()

    # Вход идёт на устройство модели: на CUDA-модели пара «вход на CPU,
    # веса на GPU» роняла проверку паритета после экспорта.
    model_device = next(model.parameters()).device

    with torch.no_grad():
        torch_out = model(torch.from_numpy(audio).to(model_device)).detach().cpu().numpy()

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    onnx_out = session.run([OUTPUT_NAME], {INPUT_NAME: audio})[0]

    diff = float(np.max(np.abs(torch_out - onnx_out)))

    if diff >= tolerance:
        raise AssertionError(
            f"torch и onnxruntime расходятся на {diff:.6g} (допуск {tolerance}): "
            "экспорт ONNX потерял часть frontend"
        )

    if not np.all((onnx_out >= 0.0) & (onnx_out <= 1.0)):
        raise AssertionError("score вне [0, 1] — в графе нет сигмоиды")

    return diff


__all__ = [
    "DEFAULT_COOLDOWN_MS",
    "DEFAULT_MIN_CONSECUTIVE",
    "DEFAULT_THRESHOLD",
    "FMAX",
    "FMIN",
    "HOP_LENGTH",
    "HOP_SAMPLES",
    "INPUT_NAME",
    "LOG_EPS",
    "LogMelFrontend",
    "Manifest",
    "N_FFT",
    "N_FRAMES",
    "N_MELS",
    "NORM_EPS",
    "ONNX_OPSET",
    "OUTPUT_NAME",
    "OnnxExportUnavailable",
    "SAMPLE_RATE",
    "WINDOW_SAMPLES",
    "WIN_LENGTH",
    "WakeWordNet",
    "dft_basis",
    "export_onnx",
    "hz_to_mel",
    "mel_filterbank",
    "mel_to_hz",
    "reference_features",
    "utc_now_iso",
    "verify_onnx_parity",
    "word_slug",
]
