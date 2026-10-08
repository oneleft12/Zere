"""Оценка модели на held-out: recall, ложные срабатывания в час, подбор порога.

Метрики считаются так, как их видит рантайм, а не «как удобно нарезать файлы»:

* recall — по каждому положительному файлу берётся ЛУЧШЕЕ окно среди позиций
  конца слова из спецификации ([0.80, 1.00] с и [0.65, 0.80] с). Рантайм
  скользит окном каждые 40 мс, поэтому вопрос звучит «загорится ли детектор
  хотя бы на одном окне», а не «на каком-то случайном положении»;
* FA/час — негативы считаются НЕПРЕРЫВНЫМ аудио: окна идут с шагом 40 мс,
  ложные окна делятся на суммарную длительность и умножаются на 3600. Иначе
  «3 срабатывания» одинаково звучали бы и на 10 секундах, и на трёх часах.

Порог подбирается автоматически: среди порогов с recall ≥ 0.97 берётся
минимальный FA/час. Такой порог и попадает в манифест — рантайм не должен
угадывать сам.

Запуск:
    python -m tools.wake_word.evaluate --run data/wakeword/runs/20261008-2100
    python -m tools.wake_word.evaluate --onnx ZERE.Voice/WakeWord/models/wake_zere.onnx
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np

from tools.wake_word import data as ww_data
# Константы и манифест берём из torch-свободного contract.py: оценка готового
# ONNX-файла (`--onnx`) не должна требовать torch, а torch-модель
# подгружается лениво только для оценки чекпойнта.
from tools.wake_word.contract import (
    HOP_SAMPLES,
    INPUT_NAME,
    OUTPUT_NAME,
    SAMPLE_RATE,
    WINDOW_SAMPLES,
    Manifest,
)

#: Минимальный recall, при котором порог вообще рассматривается.
TARGET_RECALL = 0.97

#: Порог по умолчанию, если цель по recall недостижима ни на одном пороге.
FALLBACK_THRESHOLD = 0.7

#: Сетка порогов для таблицы «порог → recall / FA/час».
THRESHOLD_GRID: tuple[float, ...] = tuple(round(0.05 * step, 2) for step in range(1, 20))

#: Позиции конца слова (доли окна), в которых рантайм обязан его поймать.
END_FRACTIONS: tuple[float, ...] = tuple(
    round(0.65 + 0.35 * step / 6.0, 4) for step in range(7)
)


# ─── Результаты ─────────────────────────────────────────────────


@dataclass
class ThresholdRow:
    """Строка таблицы: что будет при данном пороге."""

    threshold: float
    recall: float
    false_windows: int
    fa_per_hour: float

    def as_dict(self) -> dict[str, float]:
        return {
            "threshold": self.threshold,
            "recall": self.recall,
            "false_windows": float(self.false_windows),
            "fa_per_hour": self.fa_per_hour,
        }


@dataclass
class SplitEvaluation:
    """Оценка одного разбиения (val или test)."""

    split: str
    positive_files: int
    positive_scores: list[float] = field(default_factory=list)
    negative_windows: int = 0
    negative_scores: list[float] = field(default_factory=list)
    rows: list[ThresholdRow] = field(default_factory=list)
    threshold: float = FALLBACK_THRESHOLD
    recall: float = 0.0
    fa_per_hour: float = 0.0

    @property
    def negative_hours(self) -> float:
        """Длительность негативов в часах (окна × шаг рантайма)."""
        return self.negative_windows * (HOP_SAMPLES / SAMPLE_RATE) / 3600.0

    def summary(self) -> str:
        return (
            f"{self.split}: recall={self.recall:.4f} "
            f"FA/час={self.fa_per_hour:.3f} порог={self.threshold:.2f} "
            f"(позитивов {self.positive_files}, негативов "
            # Три знака после запятой: на маленьком наборе негативов (десятки
            # секунд) два знака дают «0.00 ч», и строка выглядит как «негативов
            # нет», хотя они есть.
            f"{self.negative_hours:.3f} ч)"
        )


# ─── Модель ─────────────────────────────────────────────────────


def load_checkpoint_model(checkpoint: str | Path,
                          device: str = "cpu") -> tuple[Any, dict[str, Any]]:
    """Загружает модель из чекпойнта обучения (``best.pt``/``last.pt``)."""
    import torch  # noqa: PLC0415

    from tools.wake_word.model import WakeWordNet  # noqa: PLC0415 — требует torch

    payload = torch.load(str(checkpoint), map_location="cpu", weights_only=False)
    model = WakeWordNet()

    state = payload.get("model_state") or payload.get("state_dict") or payload

    if not isinstance(state, dict):
        raise ValueError(f"в чекпойнте {checkpoint} нет состояния модели")

    model.load_state_dict(state)
    model.to(torch.device(device))
    model.eval()

    return model, payload if isinstance(payload, dict) else {}


def load_onnx_session(onnx_path: str | Path) -> Any:
    """Сессия onnxruntime на CPU — тот же путь, что у рантайма."""
    import onnxruntime as ort  # noqa: PLC0415

    return ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])


# ─── Скоринг ────────────────────────────────────────────────────


def _batch_scores_torch(model: WakeWordNet, windows: np.ndarray, device: str,
                        batch_size: int = 64) -> np.ndarray:
    """Вероятности для набора окон через torch (батчами)."""
    import torch  # noqa: PLC0415

    if windows.size == 0:
        return np.zeros(0, dtype="float64")

    scores: list[np.ndarray] = []
    torch_device = torch.device(device)

    with torch.no_grad():
        for start in range(0, windows.shape[0], batch_size):
            chunk = windows[start: start + batch_size]
            tensor = torch.from_numpy(np.ascontiguousarray(chunk, dtype="float32"))
            out = model(tensor.to(torch_device))
            scores.append(out.detach().cpu().numpy().reshape(-1))

    return np.concatenate(scores).astype("float64")


def _batch_scores_onnx(session: Any, windows: np.ndarray,
                       batch_size: int = 64) -> np.ndarray:
    """Вероятности для набора окон через onnxruntime (проверка самого файла)."""
    if windows.size == 0:
        return np.zeros(0, dtype="float64")

    scores: list[np.ndarray] = []

    for start in range(0, windows.shape[0], batch_size):
        chunk = np.ascontiguousarray(windows[start: start + batch_size], dtype="float32")
        out = session.run([OUTPUT_NAME], {INPUT_NAME: chunk})[0]
        scores.append(np.asarray(out, dtype="float64").reshape(-1))

    return np.concatenate(scores)


def make_scorer(model: Any, device: str = "cpu") -> Any:
    """Возвращает функцию ``windows (n, 16000) → вероятности (n,)``.

    Принимает либо torch-модель, либо сессию onnxruntime: оценка «того самого
    файла» не должна требовать torch, если модель уже экспортирована.
    """
    if hasattr(model, "run"):
        return lambda windows: _batch_scores_onnx(model, windows)

    return lambda windows: _batch_scores_torch(model, windows, device)


# ─── Окна позитивов ─────────────────────────────────────────────


def positive_windows(path: str | Path,
                     end_fractions: Sequence[float] = END_FRACTIONS) -> np.ndarray:
    """Окна одного позитива: слово заканчивается в заданных долях окна.

    Без аугментации и без случайности — оценка обязана быть воспроизводимой:
    два прогона на одном чекпойнте должны давать одинаковые числа.
    """
    samples, rate = ww_data.read_wav(path)
    samples = ww_data.resample_audio(samples, rate, SAMPLE_RATE)

    if samples.size == 0:
        return np.zeros((0, WINDOW_SAMPLES), dtype="float32")

    # Та же обрезка тишины, что и на обучении: паузы в синтезе не должны
    # сдвигать «конец слова» относительно позиции, которую мы проверяем.
    word = ww_data.tight_word(samples)[: WINDOW_SAMPLES]

    if word.size > WINDOW_SAMPLES:
        word = word[-WINDOW_SAMPLES:]

    windows: list[np.ndarray] = []

    for fraction in end_fractions:
        end_sample = int(round(fraction * WINDOW_SAMPLES))
        start_sample = min(max(0, end_sample - word.size), WINDOW_SAMPLES - word.size)

        window = np.zeros(WINDOW_SAMPLES, dtype="float32")
        stop = min(WINDOW_SAMPLES, start_sample + word.size)
        window[start_sample:stop] = word[: stop - start_sample]
        windows.append(window)

    return np.stack(windows)


def positive_scores(model: Any, paths: Sequence[Path]) -> list[float]:
    """Лучшая (максимальная) вероятность по каждому положительному файлу."""
    score = make_scorer(model) if not callable(model) else model
    results: list[float] = []

    for path in paths:
        windows = positive_windows(path)

        if windows.shape[0] == 0:
            results.append(0.0)
            continue

        results.append(float(np.max(score(windows))))

    return results


# ─── Сглаживание ────────────────────────────────────────────────


def consecutive_fires(flags: np.ndarray, min_consecutive: int) -> int:
    """Число серий из ``min_consecutive`` подряд идущих True.

    Ровно так работает рантайм: одиночный «выброс» выше порога не считается
    срабатыванием. Поэтому и FA/час в отчёте считается по сериям, иначе мы
    хвалили бы модель за порог, который в бою шумит.
    """
    if min_consecutive <= 1:
        return int(np.count_nonzero(flags))

    if flags.size < min_consecutive:
        return 0

    total = 0
    run = 0

    for flag in flags:
        if flag:
            run += 1
        else:
            run = 0

        if run == min_consecutive:
            total += 1
            run = 0

    return total


# ─── Метрики ────────────────────────────────────────────────────


def threshold_rows(positive_scores_seq: Sequence[float],
                   negative_scores_seq: Sequence[float],
                   negative_windows: int,
                   min_consecutive: int = 1,
                   grid: Sequence[float] = THRESHOLD_GRID) -> list[ThresholdRow]:
    """Таблица «порог → recall / FA/час».

    FA/час = (доля ложных решений) × 3600 / (шаг рантайма в секундах):
    решения принимаются каждые 40 мс, то есть 25 раз в секунду, и «ложных
    срабатываний в час» — это скорость событий, а не доля аудио.
    """
    positives = np.asarray(positive_scores_seq, dtype="float64")
    negatives = np.asarray(negative_scores_seq, dtype="float64")

    hop_seconds = HOP_SAMPLES / SAMPLE_RATE
    rows: list[ThresholdRow] = []

    for threshold in grid:
        if positives.size:
            recall = float(np.count_nonzero(positives >= threshold) / positives.size)
        else:
            recall = 0.0

        if negatives.size:
            false_windows = consecutive_fires(negatives >= threshold, min_consecutive)
        else:
            false_windows = 0

        # Знаменатель — вся длительность негативов в секундах. Считаем от
        # фактического числа окон, а не от суммы длительностей файлов: тогда
        # знаменатель совпадает с числом принятых решений.
        seconds = max(1e-9, negative_windows * hop_seconds)
        fa_per_hour = false_windows / seconds * 3600.0

        rows.append(ThresholdRow(threshold, recall, false_windows, fa_per_hour))

    return rows


def pick_threshold(rows: Sequence[ThresholdRow],
                   target_recall: float = TARGET_RECALL) -> ThresholdRow:
    """Порог с минимальным FA/час среди тех, где recall ≥ цели.

    Если цель по recall недостижима (мало данных, слабая модель), берётся
    порог с максимальным recall — честно плохой результат лучше тихо
    выбранного порога, который «в среднем неплох».
    """
    eligible = [row for row in rows if row.recall >= target_recall]

    if eligible:
        return min(eligible, key=lambda row: (row.fa_per_hour, -row.threshold))

    return max(rows, key=lambda row: (row.recall, -row.threshold))


def evaluate_split(model: Any, root: str | Path, split: str,
                   min_consecutive: int = 1,
                   hop: int = HOP_SAMPLES,
                   max_negative_windows: int | None = None) -> SplitEvaluation:
    """Считает recall и FA/час для одного разбиения.

    ``max_negative_windows`` ограничивает объём негативов: на валидации внутри
    эпохи считать все 3 часа фона с шагом 40 мс — это сотни тысяч прогонов
    модели на каждую эпоху. Итоговую оценку делает :mod:`evaluate` без
    ограничения.
    """
    base = Path(root)
    result = SplitEvaluation(split=split, positive_files=0)

    positive_paths: list[Path] = []
    members = ww_data.load_splits(base).get("splits", {}).get(split, [])
    positive_prefixes = (
        f"{ww_data.POSITIVE_DIR}/",
        f"{ww_data.POSITIVE_SYNTH_DIR}/",
    )

    for member in sorted(members):
        path = base / member

        if not path.is_file():
            continue

        if member.startswith(positive_prefixes):
            positive_paths.append(path)

    result.positive_files = len(positive_paths)

    scorer = make_scorer(model)

    for path in positive_paths:
        windows = positive_windows(path)

        if windows.shape[0] == 0:
            result.positive_scores.append(0.0)
            continue

        result.positive_scores.append(float(np.max(scorer(windows))))

    for _member, windows in ww_data.negative_windows_for_split(base, split, hop):
        scores = scorer(windows)
        result.negative_scores.extend(scores.tolist())
        result.negative_windows += int(windows.shape[0])

        if max_negative_windows and result.negative_windows >= max_negative_windows:
            break

    result.rows = threshold_rows(
        result.positive_scores, result.negative_scores,
        result.negative_windows, min_consecutive,
    )

    if result.rows:
        chosen = pick_threshold(result.rows)
        result.threshold = chosen.threshold
        result.recall = chosen.recall
        result.fa_per_hour = chosen.fa_per_hour

    return result


# ─── Отчёт ──────────────────────────────────────────────────────


def render_report(evaluations: Sequence[SplitEvaluation],
                  extra: dict[str, Any] | None = None) -> str:
    """Markdown-отчёт: сводка, таблица порогов и вывод по качеству."""
    lines: list[str] = ["# Отчёт по слову-триггеру «зере»", ""]

    if extra:
        for key, value in extra.items():
            if key != "rows":
                lines.append(f"- **{key}**: {value}")

        lines.append("")

    lines.append("## Сводка")
    lines.append("")
    lines.append("| Разбиение | Recall | FA/час | Порог | Позитивов | Негативов, ч |")
    lines.append("|---|---|---|---|---|---|")

    for evaluation in evaluations:
        lines.append(
            f"| {evaluation.split} | {evaluation.recall:.4f} | "
            f"{evaluation.fa_per_hour:.3f} | {evaluation.threshold:.2f} | "
            f"{evaluation.positive_files} | {evaluation.negative_hours:.3f} |"
        )

    lines.append("")

    for evaluation in evaluations:
        lines.append(f"## Порог → recall / FA/час ({evaluation.split})")
        lines.append("")
        lines.append("| Порог | Recall | Ложных окон | FA/час |")
        lines.append("|---|---|---|---|")

        for row in evaluation.rows:
            marker = " ✅" if abs(row.threshold - evaluation.threshold) < 1e-9 else ""
            lines.append(
                f"| {row.threshold:.2f}{marker} | {row.recall:.4f} | "
                f"{row.false_windows} | {row.fa_per_hour:.3f} |"
            )

        lines.append("")

    lines.append("## Как читать")
    lines.append("")
    lines.append(
        f"- Порог выбран автоматически: минимальный FA/час среди порогов с "
        f"recall ≥ {TARGET_RECALL:.2f}."
    )
    lines.append(
        "- FA/час — ожидаемое число ложных срабатываний за час непрерывного "
        "фонового аудио (та же метрика, что у рантайма с шагом 40 мс)."
    )
    lines.append(
        "- Если recall < 0.97: добавьте живые записи (record_positives.py) и "
        "шум своей комнаты (build_negatives.py --from-dir)."
    )
    lines.append(
        "- Если FA/час велик: поднимите порог в манифесте или добавьте "
        "негативы, похожие на слово (build_negatives.py --hard)."
    )
    lines.append("")

    return "\n".join(lines)


def write_report(path: str | Path, evaluations: Sequence[SplitEvaluation],
                 extra: dict[str, Any] | None = None) -> Path:
    """Пишет Markdown-отчёт и возвращает путь."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(evaluations, extra), encoding="utf-8")

    return target


def new_run_dir(runs_root: str | Path, stamp: str | None = None) -> Path:
    """Каталог прогона ``<runs_root>/<ts>`` (создаётся).

    Принимает именно корень прогонов (``data/wakeword/runs``), а не корпус:
    иначе путь получался бы ``runs/runs/<ts>`` — и метрики, и модель
    оказывались бы на уровень глубже, чем их ищут остальные скрипты.
    """
    name = stamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = Path(runs_root) / name
    target.mkdir(parents=True, exist_ok=True)

    return target


# ─── CLI ────────────────────────────────────────────────────────


def _positive_paths(root: Path, split: str) -> list[Path]:
    """Положительные файлы разбиения (обёртка над общим помощником data)."""
    return ww_data.positive_files_for_split(root, split)


def _run_cli(args: argparse.Namespace) -> int:
    root = Path(args.data_dir).resolve()

    model: Any
    if args.onnx:
        onnx_path = Path(args.onnx).resolve()
        print(f"Модель (ONNX): {onnx_path}")
        model = load_onnx_session(onnx_path)
        manifest_path = onnx_path.with_suffix(".json")
    else:
        checkpoint = Path(args.checkpoint or Path(args.run or "") / "best.pt").resolve()
        print(f"Модель (чекпойнт): {checkpoint}")
        model, _payload = load_checkpoint_model(checkpoint, args.device)
        manifest_path = Path(args.run).resolve() / "manifest.json" if args.run else None

    evaluations = [
        evaluate_split(model, root, split, args.min_consecutive)
        for split in args.splits
    ]

    for evaluation in evaluations:
        print(evaluation.summary())

    extra: dict[str, Any] = {"Дата": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    if manifest_path and manifest_path.is_file():
        manifest = Manifest.read(manifest_path)
        extra["Манифест"] = str(manifest_path)
        extra["Порог в манифесте"] = manifest.get("threshold")

    report = write_report(
        Path(args.out or Path(args.run or new_run_dir(root / "runs")) / "eval_report.md"),
        evaluations, extra,
    )
    print(f"Отчёт: {report}")

    if args.json:
        payload = {
            evaluation.split: {
                "recall": evaluation.recall,
                "fa_per_hour": evaluation.fa_per_hour,
                "threshold": evaluation.threshold,
                "rows": [row.as_dict() for row in evaluation.rows],
            }
            for evaluation in evaluations
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"JSON: {args.json}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Аргументы командной строки оценки."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.wake_word.evaluate",
        description="Оценка слова-триггера: recall, FA/час, подбор порога.",
    )
    parser.add_argument("--data-dir", default="data/wakeword",
                        help="корень корпуса (по умолчанию data/wakeword)")
    parser.add_argument("--run", help="каталог прогона с best.pt и manifest.json")
    parser.add_argument("--checkpoint", help="явный путь к чекпойнту (best.pt)")
    parser.add_argument("--onnx", help="оценивать готовую ONNX-модель (без torch)")
    parser.add_argument("--splits", nargs="+", default=["val", "test"],
                        help="какие разбиения оценивать (по умолчанию val test)")
    parser.add_argument("--min-consecutive", type=int, default=1,
                        help="серий подряд для срабатывания (как в манифесте)")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                        help="устройство для чекпойнта")
    parser.add_argument("--out", help="куда положить eval_report.md")
    parser.add_argument("--json", help="дополнительно сохранить метрики в JSON")
    parser.add_argument("--seed", type=int, default=0, help="зерно (зарезервировано)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа ``python -m tools.wake_word.evaluate``."""
    args = build_parser().parse_args(argv)

    try:
        return _run_cli(args)
    except FileNotFoundError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    except ModuleNotFoundError as error:
        print(
            f"Ошибка: не хватает модуля ({error.name}). "
            "Для оценки нужны torch и onnxruntime: pip install torch onnxruntime",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
