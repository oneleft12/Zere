"""Запись живых позитивов слова-триггера с микрофона.

Живые записи — самое ценное в корпусе: синтез даёт «стерильную» речь, а
микрофон пользователя, его комната и его манера говорить — то, с чем детектор
будет работать на самом деле. 100 записей с разными условиями (близко/далеко,
тихо/громко, быстро/медленно, с шумом) дают больше, чем 3000 записей синтеза
одним голосом.

Скрипт подсказывает условие для каждой записи и следит за уровнем, чтобы
записи не оказались все одинаковыми. Файл сохраняется как 16 кГц моно WAV —
ровно в том формате, который ждёт обучение.

Что делать, если файлы уже записаны (телефон, диктофон):
    python -m tools.wake_word.record_positives --from-files D:/records

Запуск:
    python -m tools.wake_word.record_positives --count 100
    python -m tools.wake_word.record_positives --count 20 --device 3
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

#: Куда по умолчанию пишутся живые записи (относительно корня репозитория).
DEFAULT_OUT = Path("data") / ww_data.DATA_DIR_NAME / ww_data.POSITIVE_DIR

#: Длина записи: окно детектора (1.0 с) плюс запас на реакцию человека.
RECORD_SECONDS = 1.4

#: Условия проговаривания — по ним и получается разнообразие корпуса.
CONDITIONS: tuple[tuple[str, str], ...] = (
    ("обычно (нейтрально, как в жизни)", "normal"),
    ("БЛИЗКО к микрофону (15–20 см)", "close"),
    ("ДАЛЕКО от микрофона (2–3 м)", "far"),
    ("ТИХО (почти шёпотом)", "quiet"),
    ("ГРОМКО (уверенно, как команду)", "loud"),
    ("БЫСТРО (скороговоркой)", "fast"),
    ("МЕДЛЕННО (растягивая)", "slow"),
    ("С ШУМОМ (включи музыку/вентилятор)", "noisy"),
)

#: Порог, ниже которого запись считается слишком тихой (RMS).
MIN_RMS = 0.005


@dataclass
class RecordingResult:
    """Итог записи: сколько файлов записано и куда."""

    saved: list[Path]
    skipped: int = 0

    def summary(self) -> str:
        return f"записано {len(self.saved)} файлов, пропущено {self.skipped}"


# ─── Зависимости ────────────────────────────────────────────────


def require_sounddevice() -> Any:
    """Импортирует sounddevice с понятной ошибкой вместо стектрейса.

    Отдельно ловим ``OSError``: PortAudio кидает его, когда в системе нет
    звуковой подсистемы (WSL без проброса, сервер без звука, занятое
    устройство). «ModuleNotFoundError» тут был бы неверным диагнозом.
    """
    try:
        import sounddevice as sd  # noqa: PLC0415
    except ImportError as error:
        raise SystemExit(
            "Ошибка: не установлен sounddevice — запись с микрофона недоступна.\n"
            "  Установка: python -m pip install sounddevice\n"
            "  Либо импортируйте уже записанные файлы:\n"
            "    python -m tools.wake_word.record_positives --from-files <папка>"
        ) from error
    except OSError as error:
        raise SystemExit(
            f"Ошибка: звуковая подсистема недоступна ({error}).\n"
            "  В WSL микрофон по умолчанию не виден — записывайте в Windows.\n"
            "  Либо импортируйте готовые файлы: --from-files <папка>"
        ) from error

    return sd


def list_input_devices(sd: Any) -> list[tuple[int, str]]:
    """Устройства ввода: (индекс, человекочитаемое имя)."""
    devices: list[tuple[int, str]] = []

    try:
        raw = sd.query_devices()
    except Exception as error:  # noqa: BLE001 — нет звука: список пуст, не падаем
        print(f"Не удалось получить список устройств: {error}", file=sys.stderr)
        return devices

    for index, device in enumerate(raw):
        if int(device.get("max_input_channels", 0)) > 0:
            devices.append((index, f"{index}: {device.get('name', '?')}"))

    return devices


# ─── Запись ─────────────────────────────────────────────────────


def record_once(sd: Any, device: int | None, seconds: float = RECORD_SECONDS,
                sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Записывает один фрагмент; возвращает float32 моно.

    Ресемплинг не нужен: мы сами просим 16 кГц. Если устройство не умеет
    16 кГц (частая ошибка PortAudio ``Invalid sample rate [-9997]``), запись
    идёт на частоте устройства, а потом приводится к 16 кГц ресемплером из
    :mod:`data` — так запись работает на любом микрофоне.
    """
    frames = int(seconds * sample_rate)

    try:
        recorded = sd.rec(frames, samplerate=sample_rate, channels=1,
                          dtype="float32", device=device)
        sd.wait()
        return np.asarray(recorded, dtype="float32").reshape(-1)
    except Exception as error:  # noqa: BLE001 — решаем по тексту ошибки
        message = str(error)

        if "-9997" not in message and "Invalid sample rate" not in message:
            raise

    # Откат: пишем на «родной» частоте устройства и ресемплим.
    try:
        info = sd.query_devices(device, "input")
        native = int(info.get("default_samplerate") or 48000)
    except Exception:  # noqa: BLE001
        native = 48000

    print(f"  16 кГц не поддерживается — пишу на {native} Гц и ресемплю")
    frames = int(seconds * native)

    recorded = sd.rec(frames, samplerate=native, channels=1, dtype="float32",
                      device=device)
    sd.wait()

    mono = np.asarray(recorded, dtype="float32").reshape(-1)

    return ww_data.resample_audio(mono, native, sample_rate)


def recording_quality(samples: np.ndarray) -> tuple[bool, str]:
    """Оценка пригодности записи: не тишина, не клиппинг."""
    if samples.size == 0:
        return False, "пустая запись"

    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples ** 2)))

    if peak >= 0.999:
        return False, "перегрузка (клиппинг) — говорите тише или отойдите"

    if rms < MIN_RMS:
        return False, "слишком тихо — говорите ближе или громче"

    if peak < 0.05:
        return False, "почти тишина — проверьте микрофон"

    return True, f"пик {peak:.2f}, RMS {rms:.3f}"


def record_session(count: int, out_dir: Path, word: str, device: int | None,
                   sample_rate: int = SAMPLE_RATE) -> RecordingResult:
    """Интерактивная запись ``count`` позитивов с подсказками условий."""
    sd = require_sounddevice()
    out_dir.mkdir(parents=True, exist_ok=True)

    devices = list_input_devices(sd)

    if devices:
        print("Доступные устройства ввода (для --device):")
        for index, name in devices:
            print(f"  {name}")
    else:
        print("Устройства ввода не найдены — запись, скорее всего, не удастся.", file=sys.stderr)

    print()
    print(f"Слово: «{word}».  Записей: {count}.  Куда: {out_dir}")
    print("Условия чередуются — так детектор не выучит одну манеру речи.")
    print("Во время записи: Enter — принять, r — перезаписать, q — выйти.")
    print()

    result = RecordingResult(saved=[])

    for index in range(count):
        condition, tag = CONDITIONS[index % len(CONDITIONS)]
        existing = sorted(out_dir.glob(f"{tag}_*.wav"))
        number = len(existing) + 1
        target = out_dir / f"{tag}_{number:04d}.wav"

        print(f"[{index + 1}/{count}] Произнесите «{word}» — {condition}")

        while True:
            print("   ... запись через", end=" ", flush=True)

            for tick in (3, 2, 1):
                print(f"{tick}", end=" ", flush=True)
                time.sleep(0.6)

            print("ГОВОРИТЕ!", flush=True)
            samples = record_once(sd, device, sample_rate=sample_rate)

            ok, verdict = recording_quality(samples)

            if ok:
                # Обрезаем тишину по краям: файл должен содержать слово, а не
                # полсекунды ожидания перед ним (иначе позиционирование в окне
                # считается от паузы, и детектор сработает позже).
                word_audio = ww_data.tight_word(samples) if samples.size else samples

                if word_audio.size == 0:
                    word_audio = samples

                ww_data.write_wav(target, word_audio, sample_rate)
                print(f"   сохранено: {target.name}  ({verdict})")
                result.saved.append(target)
                break

            print(f"   не годится: {verdict}")
            result.skipped += 1
            answer = input("   Enter — перезаписать, q — выйти: ").strip().lower()

            if answer == "q":
                print("Выход.")
                return result

    return result


# ─── Импорт готовых файлов ──────────────────────────────────────


def import_files(source: Path, out_dir: Path, word: str,
                 sample_rate: int = SAMPLE_RATE) -> RecordingResult:
    """Импортирует уже записанные аудио: ресемпл в 16 кГц моно и обрезка.

    Идемпотентно: файлы с совпадающим именем не перезаписываются повторно —
    можно запускать импорт несколько раз, добавляя новые записи.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = RecordingResult(saved=[])

    if not source.is_dir():
        raise SystemExit(f"Ошибка: папки нет — {source}")

    files = list(ww_data.iter_audio_files(source))

    if not files:
        raise SystemExit(
            f"Ошибка: в {source} нет аудиофайлов "
            f"({', '.join(ww_data.SUPPORTED_SUFFIXES)})"
        )

    print(f"Импорт: {len(files)} файлов из {source} → {out_dir}")
    print(f"Слово: «{word}»")

    for index, path in enumerate(files):
        target = out_dir / f"imported_{index:04d}_{path.stem}.wav"

        if target.exists():
            continue

        try:
            samples, rate = ww_data.read_wav(path)
        except ValueError as error:
            print(f"  пропуск {path.name}: {error}", file=sys.stderr)
            result.skipped += 1
            continue

        samples = ww_data.resample_audio(samples, rate, sample_rate)

        if samples.size == 0:
            result.skipped += 1
            continue

        ok, verdict = recording_quality(samples)

        if not ok:
            print(f"  пропуск {path.name}: {verdict}", file=sys.stderr)
            result.skipped += 1
            continue

        ww_data.write_wav(target, ww_data.tight_word(samples), sample_rate)
        result.saved.append(target)
        print(f"  {path.name} → {target.name}")

    return result


# ─── CLI ────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Аргументы командной строки записи."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.wake_word.record_positives",
        description="Запись живых позитивов слова-триггера с микрофона.",
    )
    parser.add_argument("--count", type=int, default=100,
                        help="сколько записей сделать (по умолчанию 100)")
    parser.add_argument("--device", type=int, default=None,
                        help="индекс устройства ввода (см. список при запуске)")
    parser.add_argument("--word", default="зере", help="слово-триггер")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="куда сохранять (по умолчанию data/wakeword/positive)")
    parser.add_argument("--from-files", default=None, metavar="ПАПКА",
                        help="импортировать готовые записи вместо микрофона")
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE,
                        help="частота дискретизации (по умолчанию 16000)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа ``python -m tools.wake_word.record_positives``."""
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out)

    if args.from_files:
        result = import_files(Path(args.from_files), out_dir, args.word, args.sample_rate)
    elif args.count <= 0:
        print("Ошибка: --count должен быть больше нуля", file=sys.stderr)
        return 2
    else:
        result = record_session(args.count, out_dir, args.word, args.device, args.sample_rate)

    print()
    print(f"Итог: {result.summary()}")
    print(f"Папка: {out_dir.resolve()}")
    print(
        "Дальше: соберите негативы "
        "(python -m tools.wake_word.build_negatives --from-dir <папка>) "
        "и обучите модель (python -m tools.wake_word.train --device cuda)"
    )

    return 0 if result.saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
