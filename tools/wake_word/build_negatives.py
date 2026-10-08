"""Сбор негативов: где слова «зере» нет.

Негативы важнее позитивов. Позитивов нужно ~100 живых плюс синтез, а фон
встречается в жизни постоянно: речь родных, телевизор, музыка, вентилятор,
улица. Именно от негативов зависит FA/час — сколько раз ассистент проснётся
сам. Поэтому их считают часами, а не файлами.

Источники (все — только по явному указанию, скачиваний по умолчанию НЕТ):

* ``--from-dir`` — свои аудио/видео-дорожки (рекурсивно);
* ``--download musan`` — датасет MUSAN (CC BY 4.0), ~11 ГБ, качается только
  по этому флагу;
* ``--hard`` — похожие слова (зера, зери, зори, зрение, озеро, сервер,
  джарвис): их отсутствие в фоне — главная причина ложных срабатываний;
* ``--split`` — пересобрать детерминированное разбиение train/val/test.

Похожие слова синтезируются тем же Silero, что и позитивы (``--hard``), либо
импортируются через ``--from-dir`` вместе с категорией ``negative_hard``.

Запуск:
    python -m tools.wake_word.build_negatives --from-dir D:/youtube-rips
    python -m tools.wake_word.build_negatives --from-dir ./room --category negative_room
    python -m tools.wake_word.build_negatives --hard --hard-count 40
    python -m tools.wake_word.build_negatives --download musan --musan-limit 200
    python -m tools.wake_word.build_negatives --split
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np

from tools.wake_word import data as ww_data
from tools.wake_word.contract import SAMPLE_RATE

#: Минимальная длительность негатива: из 0.3 с фона окно 1 с не набрать.
MIN_NEGATIVE_SECONDS = 1.0

#: Похожие слова — то, на чём детектор ошибается чаще всего.
HARD_WORDS: tuple[str, ...] = (
    "зера", "зери", "зори", "зрение", "озеро", "сервер", "джарвис",
)

#: MUSAN (OpenSLR 17, CC BY 4.0). Качается ТОЛЬКО по флагу --download musan.
MUSAN_URL = "https://www.openslr.org/resources/17/musan.tar.gz"

#: Каталоги MUSAN → наши категории негативов.
MUSAN_LAYOUT: dict[str, str] = {
    "noise": ww_data.NEGATIVE_NOISE_DIR,
    "music": ww_data.NEGATIVE_NOISE_DIR,
    "speech": ww_data.NEGATIVE_SPEECH_DIR,
}


@dataclass
class CollectResult:
    """Итог сбора: сколько файлов добавлено по категориям."""

    added: dict[str, int] = field(default_factory=dict)
    skipped: int = 0

    def note(self, category: str, count: int = 1) -> None:
        self.added[category] = self.added.get(category, 0) + count

    def summary(self) -> str:
        if not self.added:
            return f"ничего не добавлено (пропущено {self.skipped})"

        parts = [f"{name}: {count}" for name, count in sorted(self.added.items())]

        return ", ".join(parts) + f" (пропущено {self.skipped})"


# ─── Импорт своих аудио ─────────────────────────────────────────


def unique_target(out_dir: Path, stem: str, suffix: str = ".wav") -> Path:
    """Свободный путь, не перезаписывающий существующий файл.

    Имена из разных источников легко совпадают (``track01.wav`` в каждой
    папке), а молча затирать уже собранный фон нельзя — потеря данных
    незаметна и обнаружится только по метрикам.
    """
    candidate = out_dir / f"{stem}{suffix}"
    counter = 1

    while candidate.exists():
        candidate = out_dir / f"{stem}_{counter:03d}{suffix}"
        counter += 1

    return candidate


def import_directory(source: Path, out_dir: Path, category: str,
                     sample_rate: int = SAMPLE_RATE,
                     limit: int | None = None) -> CollectResult:
    """Импортирует аудио из папки: ресемпл в 16 кГц моно, длинные — целиком.

    Длинные файлы НЕ режем на куски: обучение читает окна с диска само, а
    FA/час считается по непрерывному аудио. Нарезание заранее только съело бы
    диск и потеряло контекст.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = CollectResult()

    if not source.exists():
        raise SystemExit(f"Ошибка: путь не найден — {source}")

    files = list(ww_data.iter_audio_files(source))

    if not files:
        raise SystemExit(
            f"Ошибка: в {source} нет аудио ({', '.join(ww_data.SUPPORTED_SUFFIXES)}).\n"
            "  Видео/другие форматы конвертируйте заранее (ffmpeg), "
            "либо установите soundfile для дополнительных форматов."
        )

    if limit:
        files = files[:limit]

    print(f"Импорт {len(files)} файлов: {source} → {out_dir} (категория {category})")

    for path in files:
        try:
            samples, rate = ww_data.read_wav(path)
        except ValueError as error:
            print(f"  пропуск {path.name}: {error}", file=sys.stderr)
            result.skipped += 1
            continue

        samples = ww_data.resample_audio(samples, rate, sample_rate)

        if samples.size < MIN_NEGATIVE_SECONDS * sample_rate:
            result.skipped += 1
            continue

        target = unique_target(out_dir, f"src_{path.stem}")

        try:
            ww_data.write_wav(target, samples, sample_rate)
        except OSError as error:
            print(f"  пропуск {path.name}: {error}", file=sys.stderr)
            result.skipped += 1
            continue

        result.note(category)
        print(f"  {path.name} → {target.name} ({samples.size / sample_rate:.1f} с)")

    return result


# ─── MUSAN ──────────────────────────────────────────────────────


def download_musan(target: Path, url: str = MUSAN_URL,
                   timeout: int = 60) -> Path:
    """Скачивает MUSAN с прогрессом (только по явному флагу).

    Скачивание идёт через stdlib ``urllib`` — новых зависимостей не нужно.
    Обрыв сети не должен оставлять битый файл: качаем во временное имя и
    переименовываем только после успеха.
    """
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.is_file() and target.stat().st_size > 0:
        print(f"Архив уже скачан: {target} ({target.stat().st_size / 1e9:.1f} ГБ)")
        return target

    partial = target.with_suffix(target.suffix + ".part")
    print(f"Скачивание MUSAN: {url}")
    print("  Внимание: архив ~11 ГБ. Прервать можно Ctrl+C — .part не помешает")
    print(f"  Куда: {target}")

    started = time.monotonic()

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            chunk_size = 1 << 20

            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(chunk_size)

                    if not chunk:
                        break

                    handle.write(chunk)
                    done += len(chunk)

                    if total:
                        percent = done / total * 100
                        print(
                            f"\r  {done / 1e9:.2f}/{total / 1e9:.2f} ГБ "
                            f"({percent:.1f}%)",
                            end="", flush=True,
                        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SystemExit(
            f"Ошибка: не удалось скачать MUSAN ({error}).\n"
            "  Скачайте вручную и распакуйте:\n"
            f"    {url}\n"
            "  Затем импортируйте папки: "
            "python -m tools.wake_word.build_negatives --from-dir <папка>"
        ) from error

    print()
    partial.replace(target)
    print(f"Готово за {time.monotonic() - started:.0f} с: {target}")

    return target


def _iter_musan_members(archive: Path, limit_per_kind: int | None) -> Iterator[tuple[str, Any]]:
    """Отдаёт нужные члены архива: ``(категория, member)``.

    MUSAN — это ~11 ГБ и сотни тысяч файлов; для KWS хватает нескольких сотен
    часовых кусков. ``limit_per_kind`` не даёт распаковке занять диск целиком.
    """
    counts: dict[str, int] = {}

    try:
        handle = tarfile.open(archive, "r:gz")
    except (tarfile.TarError, OSError) as error:
        raise SystemExit(
            f"Ошибка: не удалось открыть архив MUSAN ({error}). "
            "Файл мог скачаться не полностью — удалите его и повторите."
        ) from error

    with handle:
        for member in handle:
            if not member.isfile():
                continue

            parts = Path(member.name).parts
            kind = parts[1] if len(parts) > 2 and parts[0] == "musan" else None

            if kind not in MUSAN_LAYOUT:
                continue

            suffix = Path(member.name).suffix.lower()

            if suffix not in ww_data.SUPPORTED_SUFFIXES:
                continue

            if limit_per_kind and counts.get(kind, 0) >= limit_per_kind:
                continue

            counts[kind] = counts.get(kind, 0) + 1

            yield MUSAN_LAYOUT[kind], member


def extract_musan(archive: Path, data_dir: Path, limit_per_kind: int | None = 200,
                  sample_rate: int = SAMPLE_RATE) -> CollectResult:
    """Раскладывает MUSAN по нашим категориям, приводя всё к 16 кГц моно."""
    result = CollectResult()
    prepared: list[tuple[str, Path]] = []

    print(f"Отбор файлов из MUSAN (лимит {limit_per_kind or 'без лимита'} на тип)")

    with tarfile.open(archive, "r:gz") as handle:
        for category, member in _iter_musan_members(archive, limit_per_kind):
            extracted = handle.extractfile(member)

            if extracted is None:
                continue

            stem = Path(member.name).stem
            out_dir = data_dir / category
            out_dir.mkdir(parents=True, exist_ok=True)
            target = unique_target(out_dir, f"musan_{stem}")

            try:
                with target.open("wb") as destination:
                    shutil.copyfileobj(extracted, destination)
            except OSError as error:
                print(f"  пропуск {member.name}: {error}", file=sys.stderr)
                result.skipped += 1
                continue

            prepared.append((category, target))

    print(f"Извлечено {len(prepared)} файлов, привожу к {sample_rate} Гц моно")

    for category, path in prepared:
        try:
            samples, rate = ww_data.read_wav(path)
        except ValueError as error:
            print(f"  пропуск {path.name}: {error}", file=sys.stderr)
            result.skipped += 1
            path.unlink(missing_ok=True)
            continue

        samples = ww_data.resample_audio(samples, rate, sample_rate)
        ww_data.write_wav(path, samples, sample_rate)
        result.note(category)

    return result


# ─── Похожие слова ──────────────────────────────────────────────


def generate_hard_words(out_dir: Path, count_per_word: int, device: str,
                        seed: int, voices: Sequence[str]) -> CollectResult:
    """Синтезирует похожие слова в ``negative_hard``.

    Похожие слова — самые ценные негативы: «зера» отличается от «зере» одной
    гласной, и именно на таких парах детектор учится различать, а не просто
    «слышать шипящий звук».
    """
    from tools.wake_word.synth_positives import (
        TtsUnavailable,
        VariationConfig,
        make_backend,
        make_variant,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    result = CollectResult()
    rng = np.random.default_rng(seed)
    config = VariationConfig()
    voices = list(voices)

    backend: Any = None
    total = len(HARD_WORDS) * count_per_word
    done = 0

    print(
        f"Синтез похожих слов: {len(HARD_WORDS)} слов × {count_per_word} "
        f"= {total} файлов"
    )

    for word in HARD_WORDS:
        for index in range(count_per_word):
            voice = voices[index % len(voices)]

            try:
                if backend is None:
                    backend = make_backend(voice, device)
                    print(f"Движок синтеза: {backend.name}")

                samples = make_variant(backend, word, rng, config)
            except TtsUnavailable as error:
                print(
                    f"\nСинтез недоступен: {error}\n"
                    "  Похожие слова можно импортировать своими записями:\n"
                    "    python -m tools.wake_word.build_negatives "
                    "--from-dir <папка> --category negative_hard",
                    file=sys.stderr,
                )
                return result

            target = unique_target(out_dir, f"hard_{word}_{index:04d}")
            ww_data.write_wav(target, samples, SAMPLE_RATE)
            result.note(ww_data.NEGATIVE_HARD_DIR)
            done += 1

            if done % 25 == 0 or done == total:
                print(f"  {done}/{total}")

    return result


# ─── Разбиение ──────────────────────────────────────────────────


def rebuild_splits(data_dir: Path, seed: int) -> dict[str, Any]:
    """Пересобирает ``splits.json`` и печатает сводку."""
    payload = ww_data.build_splits(data_dir, seed=seed)
    counts = payload["counts"]

    print(
        f"Разбиение пересобрано: train={counts['train']} "
        f"val={counts['val']} test={counts['test']} (файлов)"
    )
    print(f"  Файл: {data_dir / ww_data.SPLITS_FILENAME}")

    return payload


def print_corpus_summary(data_dir: Path) -> None:
    """Показывает, что получилось: файлы и часы по категориям."""
    index = ww_data.build_index(data_dir)
    print()
    print("Корпус сейчас:")

    if index.positive_count:
        print(f"  позитивы: {index.positive_count} файлов")

    if index.negatives:
        hours = ww_data.total_hours(item.path for item in index.negatives)
        print(f"  негативы: {index.negative_count} файлов (~{hours:.2f} ч)")

    if index.impulses:
        print(f"  импульсы: {len(index.impulses)} файлов")

    if not index.positives:
        print("  позитивов НЕТ — запишите: python -m tools.wake_word.record_positives")

    if not index.negatives:
        print("  негативов НЕТ — соберите: --from-dir <папка> или --download musan")


# ─── CLI ────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Аргументы командной строки сборки негативов."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.wake_word.build_negatives",
        description="Сбор негативов для слова-триггера (без скачиваний по умолчанию).",
    )
    parser.add_argument("--from-dir", action="append", default=[], metavar="ПАПКА",
                        help="импортировать свои аудио (можно несколько раз)")
    parser.add_argument("--category", default=ww_data.NEGATIVE_ROOM_DIR,
                        choices=list(ww_data.NEGATIVE_DIRS),
                        help="в какую категорию импортировать (по умолчанию negative_room)")
    parser.add_argument("--limit", type=int, default=0,
                        help="импортировать не больше N файлов (0 — все)")
    parser.add_argument("--download", choices=["musan"], default=None,
                        help="скачать датасет (только по этому флагу; MUSAN ~11 ГБ)")
    parser.add_argument("--musan-url", default=MUSAN_URL, help="свой URL архива MUSAN")
    parser.add_argument("--musan-archive", default=None,
                        help="уже скачанный архив MUSAN (пропустить скачивание)")
    parser.add_argument("--musan-limit", type=int, default=200,
                        help="файлов на тип (noise/music/speech) из MUSAN")
    parser.add_argument("--hard", action="store_true",
                        help="синтезировать похожие слова в negative_hard")
    parser.add_argument("--hard-count", type=int, default=40,
                        help="вариаций на каждое похожее слово")
    parser.add_argument("--voices", nargs="+", default=None, help="голоса для --hard")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                        help="устройство синтеза для --hard")
    parser.add_argument("--split", action="store_true",
                        help="пересобрать splits.json после сбора")
    parser.add_argument("--data-dir", default=None,
                        help="корень корпуса (по умолчанию data/wakeword)")
    parser.add_argument("--seed", type=int, default=1337, help="зерно разбиения")
    parser.add_argument("--clean-musan", action="store_true",
                        help="удалить скачанный архив после распаковки (освободить ~11 ГБ)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа ``python -m tools.wake_word.build_negatives``."""
    args = build_parser().parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else (
        Path("data") / ww_data.DATA_DIR_NAME
    )
    ww_data.ensure_data_dirs(data_dir)

    result = CollectResult()
    did_something = False

    for source in args.from_dir:
        partial = import_directory(
            Path(source), data_dir / args.category, args.category,
            limit=args.limit or None,
        )
        result.added.update(
            {name: result.added.get(name, 0) + count for name, count in partial.added.items()}
        )
        result.skipped += partial.skipped
        did_something = True

    archive: Path | None = None

    if args.download == "musan":
        archive = Path(args.musan_archive) if args.musan_archive else (
            data_dir / "musan.tar.gz"
        )

        if not args.musan_archive:
            download_musan(archive, args.musan_url)

        partial = extract_musan(archive, data_dir, args.musan_limit or None)

        for name, count in partial.added.items():
            result.added[name] = result.added.get(name, 0) + count

        result.skipped += partial.skipped
        did_something = True

        if args.clean_musan and archive.is_file():
            archive.unlink()
            print(f"Архив удалён: {archive}")

    if args.hard:
        voices = args.voices or ["baya", "xenia", "kseniya", "aidar", "eugene"]
        partial = generate_hard_words(
            data_dir / ww_data.NEGATIVE_HARD_DIR, args.hard_count,
            args.device, args.seed, voices,
        )

        for name, count in partial.added.items():
            result.added[name] = result.added.get(name, 0) + count

        result.skipped += partial.skipped
        did_something = True

    if args.split:
        try:
            rebuild_splits(data_dir, args.seed)
        except ww_data.SplitError as error:
            # Неполное разбиение — не внутренняя ошибка, а следствие раскладки
            # корпуса: показываем объяснение без стектрейса.
            print(f"\nРазбиение собрать не удалось.\n{error}", file=sys.stderr)
            print_corpus_summary(data_dir)

            return 2

        did_something = True

    if not did_something:
        print("Ничего не задано: укажите --from-dir, --download musan, --hard или --split.")
        print_corpus_summary(data_dir)
        return 0

    print()
    print(f"Итог: {result.summary()}")
    print_corpus_summary(data_dir)

    if args.split:
        print()
        print("Дальше: python -m tools.wake_word.train --device cuda")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
