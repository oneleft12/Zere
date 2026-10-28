"""Реестр датасета: чтение WAV, разбиение, аугментации на лету.

Ключевая идея — НЕ грузить корпус в оперативную память. Негативов бывают
десятки часов (MUSAN, своя комната, YouTube), и загрузка их в RAM съела бы
гигабайты. Поэтому корпус индексируется (путь + категория + длительность), а
сэмпл читается с диска в момент обучения.

Чтение WAV — стандартная библиотека (``wave``), чтобы не тянуть лишних
зависимостей; ``soundfile`` подключается как фолбэк для форматов, которые
stdlib не понимает (float32-WAV, 24-бит, «mp3, переименованный в wav»).

Модуль СОЗНАТЕЛЬНО не импортирует torch на уровне модуля: ``build_negatives``
и ``record_positives`` пользуются только чтением/записью и разбиением, и
должны работать в окружении без torch. Torch подтягивается внутри
``__getitem__``.

Аугментации применяются на каждом обращении к сэмплу (on-the-fly), а не
один раз при подготовке: так эпохи не повторяются, и маленький живой набор
записей «размножается» до тысяч разных окон.

Детерминированное разбиение: ключ группы хешируется SHA-1 (НЕ встроенным
``hash()`` — он солится случайным зерном на каждый запуск, и разбиение
менялось бы от запуска к запуску, а тест «утекал» бы в обучение).
"""

from __future__ import annotations

import hashlib
import json
import math
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np

from tools.wake_word.contract import SAMPLE_RATE, WINDOW_SAMPLES

# ─── Раскладка data/wakeword/ ───────────────────────────────────

DATA_DIR_NAME = "wakeword"

POSITIVE_DIR = "positive"
POSITIVE_SYNTH_DIR = "positive_synth"
NEGATIVE_SPEECH_DIR = "negative_speech"
NEGATIVE_NOISE_DIR = "negative_noise"
NEGATIVE_ROOM_DIR = "negative_room"
NEGATIVE_HARD_DIR = "negative_hard"
IMPULSE_DIR = "impulse"

#: Каталоги-источники негативов (любой из них — фон, где слова нет).
NEGATIVE_DIRS: tuple[str, ...] = (
    NEGATIVE_SPEECH_DIR,
    NEGATIVE_NOISE_DIR,
    NEGATIVE_ROOM_DIR,
    NEGATIVE_HARD_DIR,
)

#: Разбиения, на которые делится корпус.
SPLIT_NAMES: tuple[str, ...] = ("train", "val", "test")

#: Доли разбиения: test/val — held-out, на них меряется качество.
SPLIT_FRACTIONS: dict[str, float] = {"train": 0.8, "val": 0.1, "test": 0.1}

SUPPORTED_SUFFIXES: tuple[str, ...] = (".wav", ".flac", ".ogg", ".mp3", ".m4a")

SPLITS_FILENAME = "splits.json"


# ─── Файловая система ───────────────────────────────────────────


def data_dir(project_root: str | Path) -> Path:
    """Папка корпуса: ``<проект>/data/wakeword``."""
    return Path(project_root) / "data" / DATA_DIR_NAME


def ensure_data_dirs(root: str | Path) -> list[Path]:
    """Создаёт все каталоги корпуса (идемпотентно) и возвращает их список."""
    created: list[Path] = []

    for name in (
        POSITIVE_DIR,
        POSITIVE_SYNTH_DIR,
        NEGATIVE_SPEECH_DIR,
        NEGATIVE_NOISE_DIR,
        NEGATIVE_ROOM_DIR,
        NEGATIVE_HARD_DIR,
        IMPULSE_DIR,
    ):
        target = Path(root) / name
        target.mkdir(parents=True, exist_ok=True)
        created.append(target)

    return created


def iter_audio_files(path: str | Path, recursive: bool = True) -> Iterator[Path]:
    """Все аудиофайлы в каталоге (по возрастанию пути — порядок стабилен)."""
    base = Path(path)

    if base.is_file():
        yield base
        return

    if not base.is_dir():
        return

    pattern = "**/*" if recursive else "*"
    candidates = sorted(p for p in base.glob(pattern) if p.is_file())

    for candidate in candidates:
        if candidate.suffix.lower() in SUPPORTED_SUFFIXES:
            yield candidate


# ─── Чтение и запись WAV ────────────────────────────────────────

_PCM_DTYPES: dict[int, str] = {
    1: "int8",
    2: "int16",
    4: "int32",
}


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Читает WAV → ``(float32 моно в [-1, 1], sample_rate)``.

    Сначала пробуем stdlib ``wave`` (16/32-бит PCM — то, что пишут и наши
    скрипты, и звуковые редакторы). Если файл нестандартный (float32,
    сжатие, mp3 с расширением .wav), отдаём его ``soundfile``; если и его
    нет — понятная ошибка вместо тихой подмены данных.
    """
    target = Path(path)

    try:
        return _read_wav_stdlib(target)
    except (wave.Error, EOFError, ValueError) as stdlib_error:
        try:
            return _read_wav_soundfile(target)
        except ImportError as import_error:
            raise ValueError(
                f"не удалось прочитать «{target.name}» стандартной библиотекой "
                f"({stdlib_error}); для этого формата нужен soundfile: "
                "pip install soundfile"
            ) from import_error
        except Exception as soundfile_error:  # noqa: BLE001
            raise ValueError(
                f"не удалось прочитать «{target.name}»: {soundfile_error}"
            ) from soundfile_error


def _read_wav_stdlib(path: Path) -> tuple[np.ndarray, int]:
    """Чтение PCM-WAV через stdlib ``wave`` (8/16/24/32 бита)."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if width not in (1, 2, 4):
        raise ValueError(f"неподдерживаемая разрядность PCM: {width * 8} бит")

    if width == 4 and _looks_like_float_wav(path):
        # Формат 3 (IEEE float) stdlib не различает, а int32-интерпретация
        # дала бы мусор — уходим на soundfile.
        raise ValueError("float32-WAV требует soundfile")

    dtype = np.dtype(_PCM_DTYPES[width]).newbyteorder("<")
    samples = np.frombuffer(frames, dtype=dtype).astype("float32")

    if width == 1:
        # 8-битный PCM беззнаковый (0..255), центр — 128.
        samples = (samples - 128.0) / 128.0
    else:
        samples = samples / float(2 ** (width * 8 - 1))

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    return np.ascontiguousarray(samples, dtype="float32"), int(rate)


def _looks_like_float_wav(path: Path) -> bool:
    """Есть ли в fmt-чанке код формата 3 (IEEE float) — без сторонних библиотек."""
    try:
        with path.open("rb") as handle:
            header = handle.read(64)

        position = header.find(b"fmt ")

        if position < 0 or position + 10 > len(header):
            return False

        return int.from_bytes(header[position + 8: position + 10], "little") == 3
    except OSError:
        return False


def _read_wav_soundfile(path: Path) -> tuple[np.ndarray, int]:
    """Фолбэк через soundfile (если установлен)."""
    import soundfile as sf  # noqa: PLC0415

    samples, rate = sf.read(str(path), dtype="float32", always_2d=True)

    return np.ascontiguousarray(samples.mean(axis=1), dtype="float32"), int(rate)


def write_wav(path: str | Path, samples: Any, sample_rate: int = SAMPLE_RATE,
              subtype: str = "PCM_16") -> Path:
    """Пишет моно WAV 16-бит через stdlib ``wave`` (без зависимостей).

    Клиппинг обязателен: усиление при аугментации легко выводит сигнал за
    [-1, 1], а 16-битная запись «заворачивает» переполнение в противоположный
    знак — это щелчок и мусор в обучении.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    signal = np.asarray(samples, dtype="float32").reshape(-1)

    if signal.size and np.max(np.abs(signal)) > 1.0:
        signal = np.clip(signal, -1.0, 1.0)

    if subtype != "PCM_16":
        raise ValueError(f"поддерживается только PCM_16, запрошено {subtype!r}")

    pcm = (signal * 32767.0).astype("<i2")

    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())

    return target


def wav_duration_s(path: str | Path) -> float:
    """Длительность WAV в секундах — БЕЗ чтения сэмплов (только заголовок).

    Нужна для отчёта «сколько часов негативов»: читать 3.5 часа аудио ради
    числа было бы расточительно, а заголовок даёт точную длину сразу.
    """
    target = Path(path)

    try:
        with wave.open(str(target), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()

        return frames / float(rate) if rate else 0.0
    except (wave.Error, OSError, EOFError):
        try:
            import soundfile as sf  # noqa: PLC0415

            info = sf.info(str(target))
            return float(info.frames) / float(info.samplerate or 1)
        except Exception:  # noqa: BLE001 — битый файл: считаем нулевым
            return 0.0


def total_hours(paths: Iterable[str | Path]) -> float:
    """Суммарная длительность файлов в часах."""
    return sum(wav_duration_s(path) for path in paths) / 3600.0


#: Порог «тишины» для поиска границ слова: −40 дБ от пика файла.
SILENCE_FLOOR_DB = -40.0


def word_bounds(samples: Any, floor_db: float = SILENCE_FLOOR_DB) -> tuple[int, int]:
    """Границы слова в файле: первый и последний сэмпл выше порога тишины.

    Зачем это нужно для позиционирования: синтез кладёт паузы до и после
    слова, а живые записи легко содержат полсекунды тишины. Если считать
    «концом слова» конец ФАЙЛА, слово окажется в окне раньше задуманного, и
    детектор будет срабатывать с задержкой (или не срабатывать). Границы
    считаются по амплитуде, поэтому паузы перестают влиять на позицию.
    """
    import numpy as np  # noqa: PLC0415

    signal = np.asarray(samples, dtype="float32").reshape(-1)

    if signal.size == 0:
        return 0, 0

    peak = float(np.max(np.abs(signal)))

    if peak <= 0.0:
        return 0, signal.size

    floor = peak * (10.0 ** (floor_db / 20.0))
    above = np.flatnonzero(np.abs(signal) > floor)

    if above.size == 0:
        return 0, signal.size

    return int(above[0]), int(above[-1]) + 1


def tight_word(samples: Any, margin: int = 160,
               floor_db: float = SILENCE_FLOOR_DB) -> np.ndarray:
    """Обрезает тишину вокруг слова, оставляя небольшой запас.

    Запас (10 мс) нужен, чтобы не срезать начало/конец согласной: у «зере»
    первый звук звонкий, и резкая обрезка превращает его в щелчок.
    """
    import numpy as np  # noqa: PLC0415

    signal = np.asarray(samples, dtype="float32").reshape(-1)
    start, stop = word_bounds(signal, floor_db)

    if stop <= start:
        return signal

    return signal[max(0, start - margin): min(signal.size, stop + margin)]


# ─── Ресемплинг ─────────────────────────────────────────────────

def resample_audio(samples: Any, source_rate: int, target_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Ресемплинг через FFT: без зависимостей и с антиалиасингом.

    Линейная интерполяция при понижении частоты заворачивает высокие частоты
    в речевой диапазон (алиасинг) и портит признаки. Усечение спектра даёт
    корректный фильтр нижних частот «бесплатно»: у numpy FFT уже есть.

    Сигнал короткий (1 с и меньше), так что цена FFT-пути незаметна.
    """
    signal = np.asarray(samples, dtype="float32").reshape(-1)

    if source_rate == target_rate or signal.size == 0:
        return signal.astype("float32", copy=False)

    if source_rate <= 0 or target_rate <= 0:
        raise ValueError(f"некорректная частота дискретизации: {source_rate} → {target_rate}")

    target_length = max(1, int(round(signal.size * target_rate / source_rate)))

    spectrum = np.fft.rfft(signal.astype("float64"))
    target_bins = target_length // 2 + 1

    if target_bins <= spectrum.size:
        # Понижение: обрезаем ВЧ и удваиваем энергию Найквиста (её numpy
        # хранит в одном бине, а полная мощность требует двух).
        trimmed = spectrum[:target_bins].copy()

        if target_length % 2 == 0 and trimmed.size:
            trimmed[-1] = trimmed[-1].real

        result = np.fft.irfft(trimmed, n=target_length)
    else:
        # Повышение: дополняем нулями (интерполяция через sinc).
        padded = np.zeros(target_bins, dtype="complex128")
        padded[: spectrum.size] = spectrum

        if target_length % 2 == 0 and padded.size:
            padded[-1] = padded[-1].real

        result = np.fft.irfft(padded, n=target_length)

    return np.ascontiguousarray(result * (target_length / signal.size), dtype="float32")


def window_starts(total: int, window: int, hop: int) -> range:
    """Позиции окон длиной ``window`` с шагом ``hop`` в сигнале длиной ``total``."""
    if total < window:
        return range(0)

    return range(0, total - window + 1, hop)


def split_windows(samples: Any, window: int = WINDOW_SAMPLES,
                  hop: int = WINDOW_SAMPLES) -> np.ndarray:
    """Нарезает непрерывный сигнал на окна ``(n, window)``.

    Используется для негативов: они считаются непрерывным аудио, и FA/час
    честно нормируется на длительность, а не на число файлов.
    """
    signal = np.asarray(samples, dtype="float32").reshape(-1)

    if signal.size < window:
        padded = np.zeros(window, dtype="float32")
        padded[: signal.size] = signal
        return padded[None, :]

    starts = list(window_starts(signal.size, window, hop))
    return np.stack([signal[start: start + window] for start in starts])


# ─── Индекс корпуса ─────────────────────────────────────────────


@dataclass(frozen=True)
class IndexedAudio:
    """Один файл корпуса в индексе (содержимое читается по требованию).

    ``path`` — абсолютный (по нему читаем), ``key`` — путь ОТНОСИТЕЛЬНО корня
    корпуса с прямыми слэшами (он попадает в ``splits.json``). Разделять их
    обязательно: абсолютные пути сделали бы разбиение непереносимым между
    машинами (``C:\\...`` против ``/tmp/...``), а сравнение с относительными
    ключами в :func:`dataset_for_split` не находило бы ни одного файла —
    обучение падало бы на пустом датасете.
    """

    path: Path
    category: str
    group: str
    key: str


@dataclass
class CorpusIndex:
    """Индекс корпуса: только пути и категории, без сэмплов в памяти."""

    positives: list[IndexedAudio] = field(default_factory=list)
    negatives: list[IndexedAudio] = field(default_factory=list)
    impulses: list[IndexedAudio] = field(default_factory=list)

    @property
    def positive_count(self) -> int:
        return len(self.positives)

    @property
    def negative_count(self) -> int:
        return len(self.negatives)

    def summary(self) -> str:
        """Короткая человекочитаемая сводка корпуса."""
        by_category: dict[str, int] = {}

        for item in self.positives + self.negatives + self.impulses:
            by_category[item.category] = by_category.get(item.category, 0) + 1

        parts = [f"{name}={count}" for name, count in sorted(by_category.items())]
        return ", ".join(parts) if parts else "пусто"


def group_key(path: Path, root: Path) -> str:
    """Ключ группы для разбиения (записи одной сессии не разъезжаются).

    Группа — «каталог + имя без хвостового номера»: ``positive/zere_0007.wav``
    и ``positive/zere_0008.wav`` попадают в одну группу. Иначе 5 живых
    записей, попавшие 4 в train и 1 в test, дали бы красивый, но лживый
    recall — модель слышала ту же сессию записи при обучении.
    """
    stem = path.stem

    while stem and (stem[-1].isdigit() or stem[-1] in "_-."):
        stem = stem[:-1]

    folder = path.parent.name if path.parent != root else ""

    return f"{folder}/{stem or path.stem}"


def index_group(root: str | Path, category: str, path: str | Path) -> str:
    """Ключ группы ровно так, как его считают :func:`build_index` и :func:`build_splits`.

    Единая точка правды: если тест или отчёт пересчитает группу «по-своему»
    (например, от другого корня), группы разъедутся, и проверка изоляции
    train/val/test начнёт врать — либо пропуская утечку, либо выдумывая её.
    """
    base = Path(root)

    return group_key(Path(path), base / category)


def _split_group_tuple(category: str, key: str, group: str) -> tuple[str, str]:
    """(категория, группа) для разбиения — единая формула, без дублей.

    Позитивы группируются по сессии записи (``group``), негативы — по самому
    файлу (``key``). Любая проверка, посчитавшая это «по-своему», либо
    пропустит утечку train↔test, либо придумает её.
    """
    return (category, group if _is_positive_category(category) else key)


def split_group_of(root: str | Path, member: str) -> tuple[str, str]:
    """Ключ группы разбиения для файла из ``splits.json`` (категория, группа).

    Нужен проверкам: ``self_test`` обязан считать группы ровно так же, как
    :func:`build_splits`, иначе тест проверяет выдуманное им самим разбиение.
    """
    base = Path(root)
    category = member.split("/", 1)[0]

    return _split_group_tuple(
        category, member, index_group(base, category, base / member)
    )


def build_index(root: str | Path, recursive: bool = True) -> CorpusIndex:
    """Сканирует ``data/wakeword`` и строит индекс категорий."""
    base = Path(root)
    index = CorpusIndex()

    for category, bucket in (
        (POSITIVE_DIR, index.positives),
        (POSITIVE_SYNTH_DIR, index.positives),
        (IMPULSE_DIR, index.impulses),
    ):
        for path in iter_audio_files(base / category, recursive):
            bucket.append(
                IndexedAudio(path, category, index_group(base, category, path),
                             _relative_key(base, path))
            )

    for category in NEGATIVE_DIRS:
        for path in iter_audio_files(base / category, recursive):
            index.negatives.append(
                IndexedAudio(path, category, index_group(base, category, path),
                             _relative_key(base, path))
            )

    return index


# ─── Детерминированное разбиение ────────────────────────────────


def _split_of(key: str, seed: int, fractions: dict[str, float]) -> str:
    """Стабильное разбиение по ключу группы.

    SHA-1 от ``seed:key`` — детерминированно на любой машине и в любом
    процессе. Встроенный ``hash()`` для этого не годится: он солится при
    старте интерпретатора (PYTHONHASHSEED), и разбиение менялось бы от
    запуска к запуску.
    """
    digest = hashlib.sha1(f"{seed}:{key}".encode("utf-8")).hexdigest()
    fraction = int(digest[:8], 16) / float(0xFFFFFFFF)

    cumulative = 0.0

    for name in SPLIT_NAMES:
        cumulative += fractions.get(name, 0.0)

        if fraction < cumulative:
            return name

    return SPLIT_NAMES[-1]


class SplitError(ValueError):
    """Разбиение собрать не удалось так, чтобы метрики что-то значили.

    Отдельный тип, потому что это НЕ «нет данных» и не внутренняя ошибка:
    данных достаточно, но их раскладка не даёт покрыть все три разбиения.
    Раньше в такой ситуации val/test оставались без позитивов, recall выходил
    нулевым, и это выглядело как «модель не обучилась» — то есть проблема
    искалась не там, где она была.
    """


def _is_positive_category(category: str) -> bool:
    """Относится ли категория к позитивам (живые записи или синтез)."""
    return category in (POSITIVE_DIR, POSITIVE_SYNTH_DIR)


def build_splits(root: str | Path, seed: int = 1337) -> dict[str, Any]:
    """Строит ``splits.json``: train/val/test по группам, детерминированно.

    Два обязательных свойства, ради которых всё и написано:

    1. **Групповая изоляция.** Записи одной сессии не разъезжаются по разным
       разбиениям: иначе почти одинаковые окна попадут и в обучение, и в тест,
       и метрики окажутся завышенными (модель «узнаёт» не слово, а микрофон).
    2. **Покрытие.** В каждом из train/val/test есть и позитивы, и негативы.
       Разбиение без позитивов даёт ``recall = 0`` по пустому множеству, а без
       негативов — ``FA/час = 0``; и то и другое выглядит как результат, хотя
       результата нет. Поэтому проверка не молчит, а падает с объяснением.

    Изоляция и покрытие конфликтуют: чтобы дать val позитивы, приходится
    переносить их из train. Перенос делается ЦЕЛОЙ группой — тогда изоляция
    сохраняется. Если групп настолько мало, что покрытие недостижимо, честнее
    остановиться и сказать, чего не хватает, чем выдать нулевые метрики.
    """
    base = Path(root)
    index = build_index(base)

    if not index.positives and not index.negatives:
        raise FileNotFoundError(
            f"в {base} нет аудио — сначала запишите позитивы "
            "(record_positives.py) и соберите негативы (build_negatives.py)"
        )

    # Ключ группы: у позитивов — сессия записи, у негативов — сам файл.
    #
    # Позитивы группируются по «каталог + имя без номера»: сто записей одного
    # вечера — это одна сессия, и разрывать её между train и test нельзя.
    # Негатив же — независимый источник (своя запись комнаты, кусок
    # видеодорожки), поэтому каждый файл сам себе группа: иначе импорт одной
    # папки схлопнул бы ВСЕ негативы в одну группу (имена вида src_track_001),
    # и разложить их по трём разбиениям стало бы невозможно.
    #
    # Формула вынесена в :func:`_split_group_tuple` и :func:`split_group_of`,
    # чтобы проверки и отчеты считали группы ТЕМ ЖЕ способом: расхождение
    # «своей» формулы в тесте уже дважды давало ложную тревогу об утечке.
    def composite(item: IndexedAudio) -> tuple[str, str]:
        return _split_group_tuple(item.category, item.key, item.group)

    items = index.positives + index.negatives
    group_split: dict[tuple[str, str], str] = {}

    for item in items:
        key = composite(item)

        if key not in group_split:
            group_split[key] = _split_of(f"{key[0]}/{key[1]}", seed, SPLIT_FRACTIONS)

    splits: dict[str, list[str]] = {name: [] for name in SPLIT_NAMES}

    for item in items:
        splits[group_split[composite(item)]].append(item.key)

    # ── Покрытие: в val и test должны быть и позитивы, и негативы ──
    positive_groups = sorted({composite(item) for item in index.positives})
    negative_groups = sorted({composite(item) for item in index.negatives})

    def covered(groups: list[tuple[str, str]], split_name: str) -> bool:
        """Есть ли в разбиении хотя бы одна группа из набора."""
        return any(group_split[group] == split_name for group in groups)

    def train_groups(groups: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Группы набора, лежащие в train."""
        return [group for group in groups if group_split[group] == "train"]

    def move_group(group: tuple[str, str], to_split: str) -> None:
        """Переносит ВСЮ группу в другое разбиение (изоляция не ломается)."""
        source = group_split[group]

        for item in items:
            if composite(item) != group:
                continue

            splits[source].remove(item.key)
            splits[to_split].append(item.key)

        group_split[group] = to_split

    for name in ("val", "test"):
        for groups in (positive_groups, negative_groups):
            if covered(groups, name):
                continue

            # Донор берём из train, но так, чтобы train не остался без группы
            # этого вида: иначе лечим val и калечим обучение.
            donors = train_groups(groups)

            if len(donors) > 1:
                move_group(donors[-1], name)

    # ── Инвариант: молчаливых нулевых метрик быть не должно ──
    coverage: dict[str, dict[str, int]] = {}
    problems: list[str] = []

    for name in SPLIT_NAMES:
        members = splits[name]
        positive_count = sum(
            1 for member in members
            if member.split("/", 1)[0] in (POSITIVE_DIR, POSITIVE_SYNTH_DIR)
        )
        negative_count = sum(
            1 for member in members if member.split("/", 1)[0] in NEGATIVE_DIRS
        )
        coverage[name] = {
            "files": len(members),
            "positive": positive_count,
            "negative": negative_count,
        }

        if not positive_count:
            problems.append(f"{name}: нет позитивов — recall считать не на чем")

        if not negative_count:
            problems.append(f"{name}: нет негативов — FA/час считать не на чем")

    if problems:
        hints: list[str] = []

        if len(positive_groups) < len(SPLIT_NAMES):
            hints.append(
                f"групп позитивов всего {len(positive_groups)}, а разбиений "
                f"{len(SPLIT_NAMES)}: разложите записи по подпапкам-сессиям "
                "(positive/session1/, positive/session2/) или запишите больше "
                "(record_positives.py)"
            )

        if len(negative_groups) < len(SPLIT_NAMES):
            hints.append(
                f"негативных файлов всего {len(negative_groups)}, а разбиений "
                f"{len(SPLIT_NAMES)}: добавьте фон "
                "(build_negatives.py --from-dir <папка> --hard)"
            )

        raise SplitError(
            "разбиение не покрывает все три части:\n  - "
            + "\n  - ".join(problems)
            + ("\n\nЧто сделать:\n  * " + "\n  * ".join(hints) if hints else "")
        )

    payload: dict[str, Any] = {
        "seed": seed,
        "fractions": SPLIT_FRACTIONS,
        "split_names": list(SPLIT_NAMES),
        "counts": {name: len(splits[name]) for name in SPLIT_NAMES},
        "coverage": coverage,
        # Карта «категория/группа → разбиение»: по ней проверяется изоляция
        # train/val/test (одна сессия записи не должна попасть в два
        # разбиения), и не нужно пересчитывать группы вторым способом.
        "groups": {
            f"{category}/{group}": name
            for (category, group), name in sorted(group_split.items())
        },
        "splits": splits,
    }

    target = base / SPLITS_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    return payload


def load_splits(root: str | Path) -> dict[str, Any]:
    """Читает ``splits.json`` (понятная ошибка, если его ещё нет)."""
    target = Path(root) / SPLITS_FILENAME

    if not target.is_file():
        raise FileNotFoundError(
            f"нет {target} — соберите разбиение: "
            "python -m tools.wake_word.build_negatives --split"
        )

    return json.loads(target.read_text(encoding="utf-8"))


def split_members(root: str | Path, name: str) -> list[Path]:
    """Абсолютные пути файлов указанного разбиения."""
    base = Path(root)
    payload = load_splits(base)
    members = payload.get("splits", {}).get(name, [])

    return [base / member for member in members]


# ─── SpecAugment ────────────────────────────────────────────────


@dataclass
class SpecAugment:
    """Маскирование признаков (SpecAugment) для обучения.

    Затирание полос частот и отрезков времени заставляет модель опираться на
    несколько разнесённых признаков, а не на одну «золотую» частоту. Для
    wake word это критично: микрофон, комната и расстояние у пользователя
    другие, чем в записях, и без масок модель переобучается на артефакты
    конкретного микрофона.

    Применяется ТОЛЬКО в режиме обучения: в ONNX случайные маски попасть не
    должны, иначе вероятность «дрожала» бы от запуска к запуску.
    """

    freq_masks: int = 2
    freq_width: int = 8
    time_masks: int = 2
    time_width: int = 10

    def __call__(self, features: Any) -> Any:
        """Маскирует признаки ``(B, 1, n_mels, T)`` (запись по месту копии)."""
        import torch  # noqa: PLC0415

        masked = features.clone()
        _, _, n_mels, n_frames = masked.shape

        for batch in range(masked.shape[0]):
            for _ in range(self.freq_masks):
                width = int(torch.randint(1, self.freq_width + 1, (1,)).item())
                width = min(width, n_mels)

                if width <= 0 or n_mels - width <= 0:
                    continue

                start = int(torch.randint(0, n_mels - width + 1, (1,)).item())
                masked[batch, :, start: start + width, :] = 0.0

            for _ in range(self.time_masks):
                width = int(torch.randint(1, self.time_width + 1, (1,)).item())
                width = min(width, n_frames)

                if width <= 0 or n_frames - width <= 0:
                    continue

                start = int(torch.randint(0, n_frames - width + 1, (1,)).item())
                masked[batch, :, :, start: start + width] = 0.0

        return masked


# ─── Аугментации сигнала ────────────────────────────────────────


@dataclass
class AugmentConfig:
    """Параметры аугментации (значения — из спецификации обучения)."""

    gain_db: tuple[float, float] = (-20.0, 6.0)
    speed: tuple[float, float] = (0.85, 1.15)
    snr_db: tuple[float, float] = (0.0, 25.0)
    noise_prob: float = 0.7
    reverb_prob: float = 0.3
    #: Доля позитивов, где конец слова — в [0.80, 1.00] с окна.
    late_position_share: float = 0.8
    #: Диапазон конца слова для «поздней» и «ранней» групп.
    late_end_range: tuple[float, float] = (0.80, 1.00)
    early_end_range: tuple[float, float] = (0.65, 0.80)


def apply_gain(samples: np.ndarray, gain_db: float) -> np.ndarray:
    """Усиление/ослабление в дБ."""
    return samples * float(10.0 ** (gain_db / 20.0))


def add_noise(samples: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """Аддитивный шум с заданным SNR (по RMS речевой части)."""
    if noise.size == 0:
        return samples

    if noise.size < samples.size:
        repeats = int(math.ceil(samples.size / noise.size))
        noise = np.tile(noise, repeats)

    noise = noise[: samples.size]

    signal_rms = float(np.sqrt(np.mean(samples ** 2)) + 1e-9)
    noise_rms = float(np.sqrt(np.mean(noise ** 2)) + 1e-9)

    target_noise_rms = signal_rms / (10.0 ** (snr_db / 20.0))

    return samples + noise * (target_noise_rms / noise_rms)


def convolve_impulse(samples: np.ndarray, impulse: np.ndarray) -> np.ndarray:
    """Свёртка с импульсным откликом (простая реверберация).

    Через FFT: прямая свёртка 16000×16000 — это 256 млн умножений на сэмпл,
    что на порядки дороже для обучения «на лету».
    """
    if impulse.size == 0:
        return samples

    length = samples.size + impulse.size - 1
    spectrum = np.fft.rfft(samples, n=length) * np.fft.rfft(impulse, n=length)
    reverbed = np.fft.irfft(spectrum, n=length)[: samples.size]

    return np.ascontiguousarray(reverbed, dtype="float32")


def change_speed(samples: np.ndarray, rate: float,
                 sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Меняет темп речи без изменения тональности ощутимо (ресемпл + длина).

    Приём из классического пайплайна: ресемплим на ``rate`` и получаем тот же
    сигнал с другой длительностью и сдвинутым на ``rate`` тоном. Питч в
    пределах ±15 % для речи звучит естественно, а для wake word это ровно та
    вариация, которая нужна (быстро/медленно проговорили).
    """
    if abs(rate - 1.0) < 1e-3:
        return samples

    stretched = resample_audio(samples, sample_rate, int(round(sample_rate * rate)))

    return resample_audio(stretched, int(round(sample_rate * rate)), sample_rate)


# ─── Датасет ────────────────────────────────────────────────────

#: Фон для «пустой» части окна позитива: сначала шум/музыка, потом речь.
_BACKGROUND_CATEGORIES: tuple[str, ...] = (
    NEGATIVE_NOISE_DIR,
    NEGATIVE_ROOM_DIR,
    NEGATIVE_SPEECH_DIR,
)


class WakeWordDataset:
    """Датасет окон «слово / не слово» с аугментацией на лету.

    Намеренно НЕ наследует ``torch.utils.data.Dataset``: иначе импорт
    ``data.py`` требовал бы torch, а ``build_negatives`` и
    ``record_positives`` должны работать в окружении без него. DataLoader'у
    достаточно ``__len__`` и ``__getitem__``.
    """

    def __init__(
        self,
        corpus: CorpusIndex,
        positives: Sequence[IndexedAudio],
        negatives: Sequence[IndexedAudio],
        *,
        epoch_size: int = 4000,
        positive_ratio: float = 0.5,
        augment: bool = True,
        config: AugmentConfig | None = None,
        seed: int = 0,
        sample_rate: int = SAMPLE_RATE,
        window_samples: int = WINDOW_SAMPLES,
        live_share: float = 0.0,
    ) -> None:
        if positive_ratio <= 0.0 or positive_ratio >= 1.0:
            raise ValueError(
                f"positive_ratio должен быть в (0, 1), получено {positive_ratio}"
            )

        if not 0.0 <= live_share <= 1.0:
            raise ValueError(
                f"live_share должен быть в [0, 1], получено {live_share}"
            )

        if not positives and not negatives:
            raise ValueError("пустой датасет: нет ни позитивов, ни негативов")

        self.corpus = corpus
        self.positives = list(positives)
        self.negatives = list(negatives)
        self.epoch_size = max(1, int(epoch_size))
        self.positive_ratio = float(positive_ratio)
        self.augment = augment
        self.config = config or AugmentConfig()
        self.seed = int(seed)
        self.sample_rate = sample_rate
        self.window_samples = window_samples
        self.live_share = float(live_share)

        self._live_positives = [
            item for item in self.positives if item.category == POSITIVE_DIR
        ]
        self._synth_positives = [
            item for item in self.positives if item.category == POSITIVE_SYNTH_DIR
        ]

        self._backgrounds = [item for item in negatives if item.category in _BACKGROUND_CATEGORIES]
        self._impulses = list(corpus.impulses)

    # ─── Размер и выборка ───

    def __len__(self) -> int:
        return self.epoch_size

    def positive_target(self) -> int:
        """Сколько позитивов в эпохе (остальное — негативы)."""
        if not self.negatives:
            return self.epoch_size

        if not self.positives:
            return 0

        return int(round(self.epoch_size * self.positive_ratio))

    def __getitem__(self, index: int) -> tuple[Any, Any]:
        """Окно и метка: ``(float32 (16000,), float32 скаляр)``."""
        import torch  # noqa: PLC0415

        rng = np.random.default_rng((self.seed * 1_000_003) ^ int(index))

        target_positives = self.positive_target()
        is_positive = index < target_positives and bool(self.positives)

        if is_positive:
            audio = self._positive_window(rng)
            label = 1.0
        else:
            audio = self._negative_window(rng)
            label = 0.0

        # Клиппинг: усиление до +6 дБ легко выводит сигнал за [-1, 1], а
        # контракт ONNX обещает значения в [-1, 1].
        audio = np.clip(audio, -1.0, 1.0).astype("float32")

        return torch.from_numpy(audio), torch.tensor([label], dtype=torch.float32)

    # ─── Позитив ───

    def _pick_positive(self, rng: np.random.Generator) -> IndexedAudio:
        """Выбирает позитив: живые записи против синтеза.

        При ``live_share = 0`` выборка равномерная, как в исходной
        спецификации. Но когда живых записей 87, а синтетических 2400,
        равномерная выборка даёт живые лишь в 3.5 % позитивов — модель
        выучивает голос TTS и отвергает настоящие записи владельца (на
        обученной так модели живые позитивы получали ≈0.005, синтез ≈0.3).
        ``live_share`` задаёт долю окон из живых записей.
        """
        live = self._live_positives
        synth = self._synth_positives

        if live and (not synth or rng.random() < self.live_share):
            return live[int(rng.integers(0, len(live)))]

        pool = synth or self.positives

        return pool[int(rng.integers(0, len(pool)))]

    def _positive_window(self, rng: np.random.Generator) -> np.ndarray:
        """Собирает окно со словом в разрешённой позиции конца слова.

        Позиционирование из спецификации: у 80 % позитивов конец слова
        попадает в [0.80, 1.00] с, у 20 % — в [0.65, 0.80]. Слово НИКОГДА не
        оказывается раньше 0.65 с: детектор смотрит последнюю секунду, и
        слово, сказанное в начале окна, для него уже «в прошлом» — учить на
        таком примере значит размывать границу срабатывания.
        """
        config = self.config
        item = self._pick_positive(rng)
        samples, rate = read_wav(item.path)
        samples = resample_audio(samples, rate, self.sample_rate)

        if self.augment:
            low, high = config.speed
            samples = change_speed(samples, float(rng.uniform(low, high)), self.sample_rate)
            samples = apply_gain(samples, float(rng.uniform(*config.gain_db)))

            if self._impulses and rng.random() < config.reverb_prob:
                impulse, impulse_rate = self._random_audio(item, self._impulses, rng)
                impulse = resample_audio(impulse, impulse_rate, self.sample_rate)
                normalize = float(np.max(np.abs(impulse)) + 1e-9)
                samples = convolve_impulse(samples, impulse / normalize)

        # Обрезка тишины — это НЕ аугментация, а условие правильного
        # позиционирования: она нужна и на обучении, и на оценке, иначе
        # «конец слова» в паузах окажется не там, где задумано.
        word = tight_word(samples)[: self.window_samples]

        if word.size >= self.window_samples:
            # Слово длиннее окна (запись с запасом) — берём хвост, чтобы конец
            # слова остался у правого края.
            word = word[-self.window_samples:]

        if rng.random() < config.late_position_share:
            end_fraction = float(rng.uniform(*config.late_end_range))
        else:
            end_fraction = float(rng.uniform(*config.early_end_range))

        end_sample = int(round(end_fraction * self.window_samples))
        start_sample = max(0, end_sample - word.size)
        start_sample = min(start_sample, self.window_samples - word.size)

        window = self._background(rng, self.window_samples, exclude=None)

        stop = min(self.window_samples, start_sample + word.size)
        window[start_sample:stop] += word[: stop - start_sample]

        if self.augment:
            window = self._mix_bed(window, rng)

        return window

    # ─── Негатив ───

    def _negative_window(self, rng: np.random.Generator) -> np.ndarray:
        """Случайное окно из непрерывного негативного аудио.

        Негатив по спецификации — окно, где слова НЕТ вовсе. «Слово сказано,
        но рано» негативом НЕ считается: такое окно модель должна уверенно
        помечать как «не сейчас», но если кормить его как «нет слова», она
        перестанет различать «слово в окне» и «слова нет».
        """
        if not self.negatives:
            # Позитивы есть, негативов нет: тишина как вынужденный фон.
            return np.zeros(self.window_samples, dtype="float32")

        item = self.negatives[int(rng.integers(0, len(self.negatives)))]
        samples, rate = read_wav(item.path)
        samples = resample_audio(samples, rate, self.sample_rate)

        if samples.size < self.window_samples:
            padded = np.zeros(self.window_samples, dtype="float32")
            padded[: samples.size] = samples
            samples = padded

        start = int(rng.integers(0, samples.size - self.window_samples + 1))
        window = samples[start: start + self.window_samples].copy()

        if self.augment:
            window = apply_gain(window, float(rng.uniform(*self.config.gain_db)))

        return window

    # ─── Вспомогательное ───

    def _random_audio(self, seed_item: IndexedAudio,
                      pool: Sequence[IndexedAudio],
                      rng: np.random.Generator) -> tuple[np.ndarray, int]:
        """Читает случайный файл из пула (для шума и импульсов)."""
        chosen = pool[int(rng.integers(0, len(pool)))]

        try:
            return read_wav(chosen.path)
        except ValueError:
            # Битый файл в пуле не должен ронять обучение на середине эпохи.
            return np.zeros(self.window_samples, dtype="float32"), self.sample_rate

    def _background(self, rng: np.random.Generator, size: int,
                    exclude: Any = None) -> np.ndarray:
        """Подложка под слово: тишина или тихий фоновый шум."""
        del exclude

        if not self._backgrounds or rng.random() < 0.3:
            return np.zeros(size, dtype="float32")

        samples, rate = self._random_audio(self._backgrounds[0], self._backgrounds, rng)
        samples = resample_audio(samples, rate, self.sample_rate)

        if samples.size < size:
            padded = np.zeros(size, dtype="float32")
            padded[: samples.size] = samples
            samples = padded

        start = int(rng.integers(0, samples.size - size + 1))

        # Фон заметно тише слова: он нужен, чтобы модель не выучила
        # «слово на цифровой тишине» как единственный признак.
        return (samples[start: start + size] * 0.1).astype("float32")

    def _mix_bed(self, window: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """Подмешивает шум к готовому окну с случайным SNR."""
        if not self._backgrounds:
            return window

        low, high = self.config.snr_db
        if rng.random() >= self.config.noise_prob:
            return window

        noise, rate = self._random_audio(self._backgrounds[0], self._backgrounds, rng)
        noise = resample_audio(noise, rate, self.sample_rate)

        return add_noise(window, noise, float(rng.uniform(low, high)))


def dataset_for_split(
    root: str | Path,
    split: str,
    *,
    epoch_size: int = 4000,
    positive_ratio: float = 0.5,
    augment: bool = True,
    seed: int = 0,
    config: AugmentConfig | None = None,
    live_share: float = 0.0,
) -> WakeWordDataset:
    """Собирает датасет для разбиения из ``splits.json``.

    Пути берутся только из указанного разбиения — это и есть защита от
    утечки: val/test не пересекаются с train ни одним файлом.
    """
    base = Path(root)
    payload = load_splits(base)
    members = payload.get("splits", {}).get(split)

    if members is None:
        raise KeyError(f"в splits.json нет разбиения {split!r}")

    corpus = build_index(base)
    positive_categories = (POSITIVE_DIR, POSITIVE_SYNTH_DIR)

    def select(items: Iterable[IndexedAudio]) -> list[IndexedAudio]:
        wanted = {member for member in members}

        return [item for item in items if item.key in wanted]

    likely_positives = select(
        [item for item in corpus.positives if item.category in positive_categories]
    )
    likely_negatives = select(corpus.negatives)

    return WakeWordDataset(
        corpus,
        likely_positives,
        likely_negatives,
        epoch_size=epoch_size,
        positive_ratio=positive_ratio,
        augment=augment,
        config=config,
        seed=seed,
        live_share=live_share,
    )


def _relative_key(root: Path, path: Path) -> str:
    """Ключ файла относительно корпуса (в формате splits.json)."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def positive_files_for_split(root: str | Path, split: str) -> list[Path]:
    """Положительные файлы разбиения (живые записи и синтез).

    Общий помощник для обучения и оценки: и манифест («positives»), и recall
    должны считать один и тот же набор — иначе число в манифесте описывало бы
    не то, на чём считались метрики.
    """
    base = Path(root)
    members = load_splits(base).get("splits", {}).get(split, [])
    prefixes = (f"{POSITIVE_DIR}/", f"{POSITIVE_SYNTH_DIR}/")

    return [
        base / member
        for member in sorted(members)
        if member.startswith(prefixes) and (base / member).is_file()
    ]


def negative_windows_for_split(root: str | Path, split: str,
                               hop: int = WINDOW_SAMPLES) -> Iterator[tuple[str, np.ndarray]]:
    """Непрерывные негативы разбиения как окна — для FA/час в evaluate.

    Отдаёт по файлу: ``(относительный путь, окна (n, window))``. Негатив
    считается НЕПРЕРЫВНЫМ аудио, поэтому FA нормируется на секунды, а не на
    число окон: иначе «3 ложных срабатывания» звучали бы одинаково и на
    10 секундах, и на 3 часах.
    """
    base = Path(root)
    payload = load_splits(base)
    members = payload.get("splits", {}).get(split, [])
    negative_prefixes = tuple(f"{name}/" for name in NEGATIVE_DIRS)

    for member in sorted(members):
        if not member.startswith(negative_prefixes):
            continue

        path = base / member

        if not path.is_file():
            continue

        samples, rate = read_wav(path)
        samples = resample_audio(samples, rate, SAMPLE_RATE)

        yield member, split_windows(samples, WINDOW_SAMPLES, hop)


__all__ = [
    "AugmentConfig",
    "CorpusIndex",
    "DATA_DIR_NAME",
    "IMPULSE_DIR",
    "IndexedAudio",
    "NEGATIVE_DIRS",
    "NEGATIVE_HARD_DIR",
    "NEGATIVE_NOISE_DIR",
    "NEGATIVE_ROOM_DIR",
    "NEGATIVE_SPEECH_DIR",
    "POSITIVE_DIR",
    "POSITIVE_SYNTH_DIR",
    "SAMPLE_RATE",
    "SPLITS_FILENAME",
    "SPLIT_FRACTIONS",
    "SPLIT_NAMES",
    "SpecAugment",
    "SplitError",
    "WakeWordDataset",
    "WINDOW_SAMPLES",
    "add_noise",
    "apply_gain",
    "build_index",
    "build_splits",
    "change_speed",
    "convolve_impulse",
    "data_dir",
    "dataset_for_split",
    "ensure_data_dirs",
    "group_key",
    "iter_audio_files",
    "index_group",
    "load_splits",
    "negative_windows_for_split",
    "positive_files_for_split",
    "read_wav",
    "resample_audio",
    "split_members",
    "split_group_of",
    "split_windows",
    "tight_word",
    "total_hours",
    "wav_duration_s",
    "window_starts",
    "word_bounds",
    "write_wav",
]
