"""Синтез позитивов локальным TTS (Silero v5, русский) с вариациями.

Зачем синтез: 100 живых записей дают правду о микрофоне и комнате, но модель
всё равно переобучится на 100 примерах. Синтез бесплатно даёт тысячи окон с
разными голосами, темпом и питчем — он «разбавляет» живой набор и не даёт
сети выучить одну манеру произнесения.

Голоса берутся из проектного сервиса (:class:`SileroManager`, каталог
``zere/voice/silero/``), с фолбэком на прямую загрузку ``v5_5_ru.pt`` из
``ZERE.Voice/Silero/``. Второй путь нужен для ``--device cuda`` (проектный
менеджер всегда работает на CPU) и когда проектный модуль недоступен.

Текст НЕ обрастает лишними словами: варианты — только регистр и пунктуация
вокруг самого слова. Фраза «эй, зере» научила бы модель опираться на «эй», и
детектор перестал бы ловить одиночное «зере»; а «зере, включи музыку»
приучила бы ждать продолжение.

Запуск:
    python -m tools.wake_word.synth_positives --count 3000
    python -m tools.wake_word.synth_positives --count 500 --device cuda
    python -m tools.wake_word.synth_positives --voices baya xenia --count 200
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from tools.wake_word import data as ww_data
from tools.wake_word.contract import SAMPLE_RATE

#: Куда пишутся синтезированные позитивы (ДО аугментации — аугментация на лету).
DEFAULT_OUT = Path("data") / ww_data.DATA_DIR_NAME / ww_data.POSITIVE_SYNTH_DIR

#: Частота синтеза Silero v5 (модель умеет 8/24/48 кГц; 24 — оптимально).
TTS_SAMPLE_RATE = 24000

#: Голоса v5_5_ru. Женские и мужской — чтобы детектор не зависел от тембра.
DEFAULT_VOICES: tuple[str, ...] = ("baya", "xenia", "kseniya", "aidar", "eugene")

#: Варианты написания слова: только регистр и пунктуация.
WORD_VARIANTS: tuple[str, ...] = ("зере", "Зере", "зере.", "Зере.")

#: Файл модели Silero и каталог относительно корня репозитория.
SILERO_MODEL_PATH = Path("ZERE.Voice") / "Silero" / "v5_5_ru.pt"


# ─── Границы вариаций ───────────────────────────────────────────


@dataclass
class VariationConfig:
    """Диапазоны вариаций синтеза (значения из спецификации)."""

    speed: tuple[float, float] = (0.8, 1.2)
    pitch: tuple[float, float] = (0.85, 1.15)
    gain_db: tuple[float, float] = (-12.0, 6.0)
    pause_before: tuple[float, float] = (0.0, 0.25)
    pause_after: tuple[float, float] = (0.0, 0.25)
    #: Вероятность подмешать тихий фон своей комнаты (если он уже собран).
    noise_prob: float = 0.35
    noise_snr_db: tuple[float, float] = (8.0, 30.0)


@dataclass
class SynthResult:
    """Итог синтеза."""

    saved: list[Path]
    failed: int = 0
    backend: str = ""

    def summary(self) -> str:
        return (
            f"синтезировано {len(self.saved)} файлов, сбоев {self.failed} "
            f"(движок: {self.backend})"
        )


# ─── Var ispeed: темп и питч одним приёмом ──────────────────────


def varispeed(samples: np.ndarray, factor: float) -> np.ndarray:
    """Меняет темп и питч ОДНИМ приёмом: «проигрывание с другой скоростью».

    Реализация — как описано в спецификации: меняем частоту дискретизации и
    ресемплим. ``factor > 1`` → длительность ×factor, питч ÷factor (ниже и
    медленнее); ``factor < 1`` → короче и выше.

    ВАЖНО: темп и питч здесь СВЯЗАНЫ — это одна и та же операция, а не два
    независимых рычага. Настоящий независимый сдвиг питча требует
    phase-vocoder (растяжение времени), а он тянет новые зависимости.
    Для wake word связка даже полезна: она покрывает и «быстро/высоко», и
    «медленно/низко», то есть реальные манеры речи.
    """
    if abs(factor - 1.0) < 1e-3 or samples.size == 0:
        return samples

    # Точность отношения: считаем от 1e6 «виртуальных герц», чтобы фактор
    # вроде 0.85 не превращался в округление 24000 → 20400 (это 0.85 ровно,
    # но 0.87 дало бы заметную ошибку на малых частотах).
    base = 1_000_000
    target = max(1, int(round(base * float(factor))))

    return ww_data.resample_audio(samples, base, target)


# ─── Движки синтеза ─────────────────────────────────────────────


def _project_root() -> Path:
    """Корень репозитория (``tools/wake_word/synth_positives.py`` → на два выше)."""
    return Path(__file__).resolve().parents[2]


def _ensure_import_path() -> None:
    """Добавляет корень репозитория в ``sys.path`` (запуск из любой папки).

    Без этого ``from zere.voice.silero...`` работает только когда текущий
    каталог — корень проекта. Скрипт должен запускаться и из другого места.
    """
    root = str(_project_root())

    if root not in sys.path:
        sys.path.insert(0, root)


class TtsUnavailable(RuntimeError):
    """Silero TTS недоступен (нет torch, нет модели, ошибка синтеза)."""


class ProjectSileroBackend:
    """Синтез через проектный :class:`SileroManager` (как в ZERE).

    Плюс: тот же код, что в асссистенте, — расхождений в звуке не будет.
    Минус: всегда CPU (менеджер сам переводит модель на CPU).
    """

    name = "проектный SileroManager"

    def __init__(self, voice: str) -> None:
        _ensure_import_path()

        try:
            from zere.voice.silero.silero_manager import SileroManager, SileroUnavailable
        except ImportError as error:
            raise TtsUnavailable(f"не импортируется zere.voice.silero: {error}") from error

        available, reason = SileroManager.availability()

        if not available:
            raise TtsUnavailable(reason)

        self._manager = SileroManager(voice=voice)
        self._unavailable = SileroUnavailable

    def waveform(self, text: str) -> tuple[np.ndarray, int]:
        """Синтез: ``(float32 моно, частота)``."""
        try:
            samples = self._manager.waveform(text)
        except self._unavailable as error:
            raise TtsUnavailable(str(error)) from error

        return np.asarray(samples, dtype="float32").reshape(-1), TTS_SAMPLE_RATE


class DirectSileroBackend:
    """Прямая загрузка ``v5_5_ru.pt`` через ``torch.package``.

    Фолбэк для случая, когда проектный модуль недоступен, и единственный путь
    для ``--device cuda``: загруженной модели можно сменить устройство.
    """

    name = "прямая загрузка v5_5_ru.pt"

    def __init__(self, voice: str, device: str = "cpu",
                 model_path: Path | None = None) -> None:
        try:
            import torch  # noqa: PLC0415
            import torch.package  # noqa: F401,PLC0415
        except ImportError as error:
            raise TtsUnavailable(f"не установлен torch: {error}") from error

        self._torch = torch
        self.voice = voice
        self.device = device
        self._model: Any = None

        candidate = Path(model_path) if model_path else _project_root() / SILERO_MODEL_PATH

        if not candidate.is_file():
            raise TtsUnavailable(
                f"нет файла модели Silero: {candidate}. Он (~145 МБ) качается "
                "автоматически при первом синтезе в ZERE "
                "(zere/voice/silero/silero_manager.py, ensure_model_file)."
            )

        self.model_path = candidate

    def _load(self) -> Any:
        """Лениво грузит модель и переносит её на нужное устройство."""
        if self._model is not None:
            return self._model

        torch = self._torch

        try:
            model = torch.package.PackageImporter(str(self.model_path)).load_pickle(
                "tts_models", "model"
            )
        except Exception as error:  # noqa: BLE001 — битый/недокачанный файл
            raise TtsUnavailable(
                f"не удалось загрузить модель Silero ({self.model_path.name}): {error}"
            ) from error

        if self.device == "cuda":
            if not torch.cuda.is_available():
                raise TtsUnavailable(
                    "--device cuda запрошен, но CUDA недоступна: перезапустите "
                    "с --device cpu"
                )

            model.to(torch.device("cuda"))
        else:
            model.to(torch.device("cpu"))
            try:
                torch.set_num_threads(max(1, min(8, (__import__("os").cpu_count() or 4))))
            except Exception:  # noqa: BLE001 — настройка не критична
                pass

        self._model = model

        return model

    def waveform(self, text: str) -> tuple[np.ndarray, int]:
        """Синтез: ``(float32 моно, частота)``."""
        model = self._load()

        try:
            audio = model.apply_tts(
                text=text, speaker=self.voice, sample_rate=TTS_SAMPLE_RATE
            )
        except Exception as error:  # noqa: BLE001 — ошибка инференса
            raise TtsUnavailable(
                f"синтез не удался (голос «{self.voice}»): {error}"
            ) from error

        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()

        return np.asarray(audio, dtype="float32").reshape(-1), TTS_SAMPLE_RATE


def make_backend(voice: str, device: str = "cpu",
                 model_path: Path | None = None) -> Any:
    """Выбирает движок синтеза: проектный сервис, иначе прямая загрузка.

    Порядок продиктован спецификацией (сначала проектный SileroManager), но
    при ``--device cuda`` проектный путь пропускается: он всё равно уедет на
    CPU, и флаг остался бы невыполненным обещанием.
    """
    problems: list[str] = []

    if device == "cpu":
        try:
            return ProjectSileroBackend(voice)
        except TtsUnavailable as error:
            problems.append(f"проектный SileroManager: {error}")

    try:
        return DirectSileroBackend(voice, device=device, model_path=model_path)
    except TtsUnavailable as error:
        problems.append(f"прямая загрузка: {error}")

    if device != "cpu":
        # Последняя попытка: синтез на CPU всё равно лучше, чем ничего.
        try:
            return DirectSileroBackend(voice, device="cpu", model_path=model_path)
        except TtsUnavailable as error:
            problems.append(f"CPU-фолбэк: {error}")

    raise TtsUnavailable(
        "Silero TTS недоступен.\n  " + "\n  ".join(problems) + "\n"
        "Что делать: установите torch и soundfile "
        "(python -m pip install torch soundfile), либо запустите ZERE один раз — "
        "модель v5_5_ru.pt скачается сама в ZERE.Voice/Silero/."
    )


# ─── Синтез одной вариации ──────────────────────────────────────


def make_variant(backend: Any, text: str, rng: np.random.Generator,
                 config: VariationConfig, noise: tuple[np.ndarray, int] | None = None,
                 target_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Синтезирует слово и применяет вариации: темп, питч, громкость, паузы."""
    samples, rate = backend.waveform(text)
    samples = ww_data.resample_audio(samples, rate, target_rate)

    # Темп и питч — две последовательные операции varispeed: вместе они дают
    # случайное растяжение и сдвиг тона (см. varispeed о связанности).
    samples = varispeed(samples, float(rng.uniform(*config.speed)))
    samples = varispeed(samples, 1.0 / float(rng.uniform(*config.pitch)))

    samples = ww_data.apply_gain(samples, float(rng.uniform(*config.gain_db)))

    if noise is not None and rng.random() < config.noise_prob:
        bed, bed_rate = noise
        bed = ww_data.resample_audio(bed, bed_rate, target_rate)
        samples = ww_data.add_noise(
            samples, bed, float(rng.uniform(*config.noise_snr_db))
        )

    # Паузы до и после слова: детектор должен видеть слово и по краям окна, а
    # не только «слово на цифровой тишине ровно по центру».
    before = int(rng.uniform(*config.pause_before) * target_rate)
    after = int(rng.uniform(*config.pause_after) * target_rate)

    padded = np.concatenate([
        np.zeros(before, dtype="float32"),
        samples,
        np.zeros(after, dtype="float32"),
    ])

    # Обрезаем только по внешним краям пауз, сохраняя их внутри: обучение само
    # позиционирует слово по его амплитудным границам.
    return np.clip(padded, -1.0, 1.0).astype("float32")


def load_noise_pool(data_dir: Path, limit: int = 20) -> tuple[np.ndarray, int] | None:
    """Готовит фоновый шум из уже собранных негативов (если они есть).

    Своя комната важнее чужого датасета: микрофон и акустика те же, что будут
    при работе детектора.
    """
    for category in (ww_data.NEGATIVE_ROOM_DIR, ww_data.NEGATIVE_NOISE_DIR):
        files = list(ww_data.iter_audio_files(data_dir / category))[:limit]

        for path in files:
            try:
                samples, rate = ww_data.read_wav(path)
            except ValueError:
                continue

            if samples.size:
                return samples, rate

    return None


# ─── Основной цикл ──────────────────────────────────────────────


def synthesize(count: int, out_dir: Path, word: str, voices: Sequence[str],
               device: str, seed: int, config: VariationConfig,
               data_dir: Path, model_path: Path | None = None,
               target_rate: int = SAMPLE_RATE) -> SynthResult:
    """Синтезирует ``count`` вариаций слова и сохраняет их в ``out_dir``.

    Сбои отдельных фраз не роняют процесс: голос может не поддержать редкий
    текст, а 3000 фраз — это долго, и терять прогресс из-за одной ошибки
    нельзя. Но если не вышло НИ ОДНОЙ фразы, это уже ошибка окружения — о ней
    сообщаем честно.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    result = SynthResult(saved=[])

    noise = load_noise_pool(data_dir)
    backend: Any = None
    backend_index = 0
    voices = list(voices) or list(DEFAULT_VOICES)

    if noise is not None:
        print("Фоновый шум для подмешивания: найден в негативах")

    started = time.monotonic()

    for index in range(count):
        voice = voices[index % len(voices)]
        text = WORD_VARIANTS[index % len(WORD_VARIANTS)]

        if backend is None:
            backend = make_backend(voice, device, model_path)
            result.backend = backend.name
            print(f"Движок синтеза: {backend.name} (голос «{voice}»)")

        try:
            samples = make_variant(backend, text, rng, config, noise, target_rate)
        except TtsUnavailable as error:
            result.failed += 1

            # Пробуем сменить голос: часть голосов может отсутствовать в
            # конкретной сборке модели, и терять из-за этого весь прогон глупо.
            backend_index += 1

            if backend_index >= len(voices):
                if not result.saved:
                    raise

                print(f"\nПрекращаю: {error}", file=sys.stderr)
                break

            backend = None
            continue

        target = out_dir / f"tts_{voice}_{index:05d}.wav"
        ww_data.write_wav(target, samples, target_rate)
        result.saved.append(target)

        if (index + 1) % 50 == 0 or index + 1 == count:
            elapsed = time.monotonic() - started
            rate = (index + 1) / max(1e-6, elapsed)
            remaining = (count - index - 1) / max(1e-6, rate)
            print(
                f"  {index + 1}/{count}  ({rate:.1f} фраз/с, "
                f"осталось ~{remaining / 60:.1f} мин)"
            )

    return result


# ─── CLI ────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Аргументы командной строки синтеза."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.wake_word.synth_positives",
        description="Синтез позитивов слова-триггера локальным Silero TTS.",
    )
    parser.add_argument("--count", type=int, default=3000,
                        help="сколько вариаций синтезировать (по умолчанию 3000)")
    parser.add_argument("--word", default="зере", help="слово-триггер")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                        help="устройство синтеза (по умолчанию cpu)")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="куда сохранять (data/wakeword/positive_synth)")
    parser.add_argument("--data-dir", default=None,
                        help="корень корпуса (для подмешивания своего шума)")
    parser.add_argument("--voices", nargs="+", default=list(DEFAULT_VOICES),
                        help="голоса Silero (baya xenia kseniya aidar eugene)")
    parser.add_argument("--model", default=None,
                        help="путь к v5_5_ru.pt (по умолчанию ZERE.Voice/Silero)")
    parser.add_argument("--seed", type=int, default=0, help="зерно вариаций")
    parser.add_argument("--speed-range", nargs=2, type=float, default=[0.8, 1.2],
                        metavar=("MIN", "MAX"), help="диапазон темпа")
    parser.add_argument("--pitch-range", nargs=2, type=float, default=[0.85, 1.15],
                        metavar=("MIN", "MAX"), help="диапазон питча (связан с темпом)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа ``python -m tools.wake_word.synth_positives``."""
    args = build_parser().parse_args(argv)

    if args.count <= 0:
        print("Ошибка: --count должен быть больше нуля", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    data_dir = Path(args.data_dir) if args.data_dir else out_dir.parent

    config = VariationConfig(
        speed=(min(args.speed_range), max(args.speed_range)),
        pitch=(min(args.pitch_range), max(args.pitch_range)),
    )

    print(f"Слово: «{args.word}».  Вариаций: {args.count}.  Куда: {out_dir}")
    print(f"Голоса: {', '.join(args.voices)}")
    print(
        f"Темп {config.speed[0]}–{config.speed[1]}, "
        f"питч {config.pitch[0]}–{config.pitch[1]} "
        "(темп и питч связаны: один приём «проиграть быстрее/медленнее»)"
    )
    print()

    try:
        result = synthesize(
            count=args.count,
            out_dir=out_dir,
            word=args.word,
            voices=args.voices,
            device=args.device,
            seed=args.seed,
            config=config,
            data_dir=data_dir,
            model_path=Path(args.model) if args.model else None,
        )
    except TtsUnavailable as error:
        print(f"\nОшибка: {error}", file=sys.stderr)
        print(
            "\nСинтез не выполнен. Живые записи всё равно работают: "
            "python -m tools.wake_word.record_positives --count 100",
            file=sys.stderr,
        )
        return 3
    except ModuleNotFoundError as error:
        print(
            f"\nОшибка: не хватает модуля ({error.name}). "
            "Для синтеза нужны torch и soundfile: python -m pip install torch soundfile",
            file=sys.stderr,
        )
        return 3

    print()
    print(f"Итог: {result.summary()}")
    print(f"Папка: {out_dir.resolve()}")

    if not result.saved:
        print("Ни одного файла не сохранено — проверьте модель и голоса.", file=sys.stderr)
        return 1

    print(
        "Дальше: python -m tools.wake_word.build_negatives --split, затем "
        "python -m tools.wake_word.train --device cuda"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
