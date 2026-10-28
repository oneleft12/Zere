"""Обучение слова-триггера: AdamW + cosine, early stopping по FA при recall ≥ 0.97.

Что происходит по шагам:

1. читается ``data/wakeword/splits.json`` (если его нет — строится);
2. из разбиения ``train`` собирается датасет с аугментацией на лету; баланс
   классов задаётся отношением негатив:позитив (1:1 … 1:3) — при 1:1 модель
   недоучивается на фоне, при 1:3 начинает срабатывать на речи;
3. обучение BCEWithLogitsLoss (численно устойчивее, чем BCE по вероятности)
   с ``--pos-weight`` для борьбы с перекосом классов, AdamW + cosine;
4. после каждой эпохи считается val: recall по файлам и FA/час по
   непрерывным негативам. Останавливаемся по метрике «минимальный FA/час при
   recall ≥ 0.97», а не по loss: loss на таком дисбалансе почти не связан с
   тем, что нам нужно;
5. лучший чекпойнт экспортируется в ONNX, к нему пишется манифест с
   автоподобранным порогом и кладётся в ``ZERE.Voice/WakeWord/models/``.

Запуск (GPU):
    python -m tools.wake_word.train --device cuda --epochs 40
Запуск (CPU, медленно, но работает):
    python -m tools.wake_word.train --device cpu --epochs 10 --epoch-size 1000
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np

from tools.wake_word import data as ww_data
from tools.wake_word import evaluate as ww_evaluate
from tools.wake_word.model import (
    DEFAULT_COOLDOWN_MS,
    DEFAULT_MIN_CONSECUTIVE,
    DEFAULT_THRESHOLD,
    HOP_SAMPLES,
    INPUT_NAME,
    OUTPUT_NAME,
    SAMPLE_RATE,
    WINDOW_SAMPLES,
    Manifest,
    OnnxExportUnavailable,
    WakeWordNet,
    export_onnx,
    utc_now_iso,
    verify_onnx_parity,
    word_slug,
)

#: Куда кладётся готовая модель (её ищут рантаймы обеих редакций).
MODEL_DIR = Path("ZERE.Voice") / "WakeWord" / "models"

#: Имя файла CSV с метриками внутри каталога прогона.
METRICS_FILENAME = "metrics.csv"


# ─── Конфигурация ───────────────────────────────────────────────


@dataclass
class TrainConfig:
    """Параметры обучения (то, что раньше было россыпью аргументов)."""

    data_dir: Path
    runs_dir: Path
    model_dir: Path
    word: str = "зере"
    device: str = "cpu"
    epochs: int = 40
    batch_size: int = 64
    epoch_size: int = 4000
    lr: float = 1e-3
    weight_decay: float = 1e-4
    neg_per_pos: int = 2
    pos_weight: float = 1.0
    loss: str = "bce"
    focal_gamma: float = 2.0
    patience: int = 6
    target_recall: float = ww_evaluate.TARGET_RECALL
    min_consecutive: int = 1
    val_hop: int = HOP_SAMPLES
    val_max_negative_windows: int = 20000
    num_workers: int = 0
    seed: int = 0
    augment: bool = True
    export: bool = True
    torch_version: str = ""
    manifest_min_consecutive: int = DEFAULT_MIN_CONSECUTIVE
    cooldown_ms: int = DEFAULT_COOLDOWN_MS

    @property
    def positive_ratio(self) -> float:
        """Доля позитивов в эпохе из отношения негатив:позитив.

        1:1 → 0.5, 1:3 → 0.25. Ограничение 1…3 из спецификации: больше
        позитивов ведёт к ложным срабатываниям на речи, меньше — к пропускам.
        """
        return 1.0 / (1.0 + float(self.neg_per_pos))


@dataclass
class EpochMetrics:
    """Метрики одной эпохи (строка metrics.csv)."""

    epoch: int
    lr: float
    train_loss: float
    val_recall: float
    val_fa_per_hour: float
    val_threshold: float
    improved: bool = False

    def as_row(self) -> dict[str, Any]:
        return {
            "epoch": self.epoch,
            "lr": f"{self.lr:.6g}",
            "train_loss": f"{self.train_loss:.6f}",
            "val_recall": f"{self.val_recall:.4f}",
            "val_fa_per_hour": f"{self.val_fa_per_hour:.4f}",
            "val_threshold": f"{self.val_threshold:.2f}",
            "improved": int(self.improved),
        }


@dataclass
class TrainResult:
    """Итог обучения: лучший чекпойнт, модель и метрики."""

    run_dir: Path
    best_checkpoint: Path
    history: list[EpochMetrics] = field(default_factory=list)
    model_path: Path | None = None
    manifest_path: Path | None = None
    onnx_diff: float = 0.0


# ─── Служебное ──────────────────────────────────────────────────


def resolve_device(requested: str) -> str:
    """Проверяет устройство: нет CUDA — честно откатываемся на CPU.

    Молча падать на ``--device cuda`` без видеокарты нельзя: обучение — долгий
    процесс, и узнать об этом в конце обидно. Но и отказывать не нужно: тот
    же код на CPU работает, просто медленнее.
    """
    import torch  # noqa: PLC0415

    if requested == "cuda":
        if torch.cuda.is_available():
            return "cuda"

        print(
            "Предупреждение: CUDA недоступна (нет видеокарты или сборка torch "
            "без CUDA) — учу на CPU",
            file=sys.stderr,
        )
        return "cpu"

    return "cpu"


def set_seed(seed: int) -> None:
    """Фиксирует зерно у random/numpy/torch (воспроизводимость прогонов)."""
    import random  # noqa: PLC0415

    import torch  # noqa: PLC0415

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def ensure_splits(data_dir: Path, seed: int = 1337) -> dict[str, Any]:
    """Читает ``splits.json``, а при отсутствии — строит его.

    Автосборка удобна: пользователь записал позитивы и негативы, и первый же
    запуск обучения не должен требовать помнить про ``--split``. Разбиение
    детерминировано, так что повторный запуск даёт те же файлы.
    """
    try:
        return ww_data.load_splits(data_dir)
    except FileNotFoundError:
        print(f"Разбиения нет — строю {ww_data.SPLITS_FILENAME} (зерно {seed})")
        return ww_data.build_splits(data_dir, seed=seed)


def count_positive_files(data_dir: Path, split: str) -> int:
    """Число положительных ФАЙЛОВ разбиения (для манифеста)."""
    return len(ww_data.positive_files_for_split(data_dir, split))


def negative_hours(data_dir: Path, split: str) -> float:
    """Суммарная длительность негативов разбиения в часах."""
    members = ww_data.load_splits(data_dir).get("splits", {}).get(split, [])
    prefixes = tuple(f"{name}/" for name in ww_data.NEGATIVE_DIRS)

    return ww_data.total_hours(
        data_dir / member
        for member in members
        if member.startswith(prefixes) and (data_dir / member).is_file()
    )


# ─── Функции потерь ─────────────────────────────────────────────


def compute_loss(logits: Any, targets: Any, config: TrainConfig) -> Any:
    """BCEWithLogitsLoss или focal loss.

    BCEWithLogitsLoss — основной вариант: она берёт логиты и считает
    сигмоиду внутри устойчиво (``log(1+exp(x))``), поэтому не переполняется на
    уверенных примерах. Focal — вариант для сильного перекоса классов: гасит
    вклад уже уверенно верных примеров.
    """
    import torch  # noqa: PLC0415
    import torch.nn.functional as F  # noqa: PLC0415

    pos_weight = None

    if config.pos_weight and abs(config.pos_weight - 1.0) > 1e-9:
        pos_weight = torch.tensor([config.pos_weight], device=logits.device)

    bce = F.binary_cross_entropy_with_logits(
        logits, targets, pos_weight=pos_weight, reduction="none"
    )

    if config.loss != "focal":
        return bce.mean()

    probabilities = torch.sigmoid(logits)
    pt = torch.where(targets > 0.5, probabilities, 1.0 - probabilities)

    return (((1.0 - pt) ** config.focal_gamma) * bce).mean()


# ─── Обучение ───────────────────────────────────────────────────


def train_one_epoch(model: WakeWordNet, loader: Any, optimizer: Any,
                    config: TrainConfig, device: str) -> float:
    """Одна эпоха обучения; возвращает средний loss."""
    import torch  # noqa: PLC0415

    model.train()
    total_loss = 0.0
    batches = 0

    for windows, labels in loader:
        windows = windows.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)

        logits = model.forward_logits(windows)
        loss = compute_loss(logits, labels, config)

        loss.backward()
        # Градиентный клиппинг: focal и агрессивная аугментация иногда дают
        # всплеск градиента, после которого BatchNorm «залипает».
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()

        total_loss += float(loss.detach().cpu())
        batches += 1

    return total_loss / max(1, batches)


def selection_key(evaluation: ww_evaluate.SplitEvaluation,
                  target_recall: float) -> tuple[int, float, float]:
    """Ключ сравнения эпох: сначала «дотянулись до recall», потом FA, потом recall.

    Сортировка по loss тут не годится: на фоне с дисбалансом классов loss
    почти не связан с числом ложных срабатываний в час, а нам важно именно
    оно. Первый элемент ключа — 0, если цель по recall достигнута.
    """
    reached = 0 if evaluation.recall >= target_recall else 1

    return (reached, evaluation.fa_per_hour, -evaluation.recall)


def save_checkpoint(path: Path, model: WakeWordNet, optimizer: Any,
                    epoch: int, evaluation: ww_evaluate.SplitEvaluation,
                    config: TrainConfig) -> Path:
    """Сохраняет чекпойнт (модель + оптимизатор + метрики эпохи)."""
    import torch  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state": model.state_dict(),
            "optimizer_state": optimizer.state_dict(),
            "epoch": epoch,
            "val_recall": evaluation.recall,
            "val_fa_per_hour": evaluation.fa_per_hour,
            "val_threshold": evaluation.threshold,
            "word": config.word,
            "torch_version": config.torch_version,
        },
        str(path),
    )

    return path


def write_metrics_csv(path: Path, history: Sequence[EpochMetrics]) -> Path:
    """Пишет ``metrics.csv`` (перезаписью — история у нас в памяти)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "epoch", "lr", "train_loss", "val_recall",
        "val_fa_per_hour", "val_threshold", "improved",
    ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for metrics in history:
            writer.writerow(metrics.as_row())

    return path


def fit(config: TrainConfig) -> TrainResult:
    """Полный цикл обучения с early stopping. Возвращает результат."""
    import torch  # noqa: PLC0415

    from tools.wake_word.evaluate import evaluate_split, new_run_dir

    device = resolve_device(config.device)
    config.device = device
    config.torch_version = torch.__version__

    set_seed(config.seed)
    ensure_splits(config.data_dir, seed=config.seed + 1337)

    run_dir = new_run_dir(config.runs_dir)

    print("=" * 68)
    print(f"Слово-триггер: «{config.word}»   устройство: {device}   torch: {torch.__version__}")
    print(f"Каталог прогона: {run_dir}")
    print("=" * 68)

    augment_config = ww_data.AugmentConfig()
    train_dataset = ww_data.dataset_for_split(
        config.data_dir, "train",
        epoch_size=config.epoch_size,
        positive_ratio=config.positive_ratio,
        augment=config.augment,
        seed=config.seed,
        config=augment_config,
    )
    print(
        f"Train: позитивов {len(train_dataset.positives)} файлов, "
        f"негативов {len(train_dataset.negatives)} файлов "
        f"({negative_hours(config.data_dir, 'train'):.2f} ч фона); "
        f"эпоха {train_dataset.epoch_size} окон "
        f"({config.positive_ratio:.0%} позитивов, "
        f"негатив:позитив = {config.neg_per_pos}:1)"
    )

    loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=config.batch_size,
        shuffle=True,
        num_workers=config.num_workers,
        drop_last=False,
    )

    model = WakeWordNet().to(device)
    # SpecAugment живёт в data.py (это аугментация признаков) и ставится в
    # модель снаружи: в ONNX она попасть не должна, поэтому вызывается только
    # в режиме обучения.
    model.spec_augmenter = ww_data.SpecAugment() if config.augment else None

    print(f"Параметров модели: {model.parameter_count:,}".replace(",", " "))

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.lr, weight_decay=config.weight_decay
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=max(1, config.epochs)
    )

    best_checkpoint = run_dir / "best.pt"
    history: list[EpochMetrics] = []
    best_key: tuple[int, float, float] | None = None
    epochs_without_improvement = 0

    for epoch in range(1, config.epochs + 1):
        train_loss = train_one_epoch(model, loader, optimizer, config, device)

        evaluation = evaluate_split(
            model, config.data_dir, "val",
            min_consecutive=config.min_consecutive,
            hop=config.val_hop,
            max_negative_windows=config.val_max_negative_windows,
        )
        scheduler.step()

        key = selection_key(evaluation, config.target_recall)
        improved = best_key is None or key < best_key

        if improved:
            best_key = key
            epochs_without_improvement = 0
            save_checkpoint(best_checkpoint, model, optimizer, epoch, evaluation, config)
        else:
            epochs_without_improvement += 1

        metrics = EpochMetrics(
            epoch=epoch,
            lr=float(optimizer.param_groups[0]["lr"]),
            train_loss=train_loss,
            val_recall=evaluation.recall,
            val_fa_per_hour=evaluation.fa_per_hour,
            val_threshold=evaluation.threshold,
            improved=improved,
        )
        history.append(metrics)

        print(
            f"Эпоха {epoch:>3}/{config.epochs}  loss={train_loss:.4f}  "
            f"val: recall={evaluation.recall:.4f}  FA/час={evaluation.fa_per_hour:.3f}  "
            f"порог={evaluation.threshold:.2f}  lr={metrics.lr:.2e}"
            + ("  ← лучшая" if improved else "")
        )

        write_metrics_csv(run_dir / METRICS_FILENAME, history)

        if epochs_without_improvement >= config.patience:
            print(
                f"Ранний останов: {config.patience} эпох без улучшения "
                f"(метрика: FA/час при recall ≥ {config.target_recall:.2f})"
            )
            break

    result = TrainResult(run_dir=run_dir, best_checkpoint=best_checkpoint, history=history)

    print("-" * 68)
    print(f"Лучший чекпойнт: {best_checkpoint}")
    print(f"Метрики: {run_dir / METRICS_FILENAME}")

    if config.export:
        export_and_publish(model, checkpoint=best_checkpoint, config=config, result=result)

    return result


# ─── Экспорт и манифест ─────────────────────────────────────────


def export_and_publish(model: WakeWordNet, checkpoint: Path, config: TrainConfig,
                       result: TrainResult) -> TrainResult:
    """Экспортирует лучший чекпойнт в ONNX и кладёт модель с манифестом.

    Порог подбирается на val (recall ≥ 0.97 при минимальном FA/час) и
    фиксируется в манифесте: рантайм не должен угадывать его сам, иначе
    поведение детектора «плывёт» между сборками.
    """
    import torch  # noqa: PLC0415

    # Берём именно лучший чекпойнт: после последней эпохи в памяти лежит
    # худшая модель (обучение остановилось, когда метрика перестала расти).
    payload = torch.load(str(checkpoint), map_location="cpu", weights_only=False)
    model.load_state_dict(payload["model_state"])
    model.eval()

    torch.save({"model_state": model.state_dict()}, str(result.run_dir / "final.pt"))

    onnx_path = export_onnx(model, result.run_dir / "model.onnx")
    diff = verify_onnx_parity(model, onnx_path)
    print(f"ONNX: {onnx_path}  (паритет torch↔onnxruntime: {diff:.2e})")

    val = ww_evaluate.evaluate_split(
        model, config.data_dir, "val", min_consecutive=config.min_consecutive
    )
    test = ww_evaluate.evaluate_split(
        model, config.data_dir, "test", min_consecutive=config.min_consecutive
    )

    # Порог выбираем на val, а метрики в манифесте отдаём с test: выбор порога
    # по test превратил бы held-out в часть обучения.
    threshold = val.threshold if val.rows else DEFAULT_THRESHOLD

    manifest = Manifest(
        word=config.word,
        sample_rate=SAMPLE_RATE,
        window_samples=WINDOW_SAMPLES,
        hop_samples=HOP_SAMPLES,
        threshold=round(float(threshold), 4),
        min_consecutive=config.manifest_min_consecutive,
        cooldown_ms=config.cooldown_ms,
        input_name=INPUT_NAME,
        output_name=OUTPUT_NAME,
        trained_at=utc_now_iso(),
        metrics={
            "test_recall": round(test.recall, 4),
            "test_fa_per_hour": round(test.fa_per_hour, 4),
            "val_recall": round(val.recall, 4),
            "val_fa_per_hour": round(val.fa_per_hour, 4),
        },
        torch_version=config.torch_version,
        positives=count_positive_files(config.data_dir, "train"),
        negatives_hours=round(negative_hours(config.data_dir, "train"), 3),
    )

    manifest.write(result.run_dir / "manifest.json")

    # Публикация: в проекте модель ищется как wake_<слово>.onnx рядом с .json.
    publish_dir = Path(config.model_dir)
    publish_dir.mkdir(parents=True, exist_ok=True)
    slug = word_slug(config.word)

    published_onnx = publish_dir / f"wake_{slug}.onnx"
    published_manifest = publish_dir / f"wake_{slug}.json"
    published_onnx.write_bytes(onnx_path.read_bytes())
    manifest.write(published_manifest)

    result.model_path = published_onnx
    result.manifest_path = published_manifest
    result.onnx_diff = diff

    print("-" * 68)
    print(f"Порог (val, recall ≥ {ww_evaluate.TARGET_RECALL:.2f}): {threshold:.2f}")
    print(f"val:  recall={val.recall:.4f}  FA/час={val.fa_per_hour:.3f}")
    print(f"test: recall={test.recall:.4f}  FA/час={test.fa_per_hour:.3f}")
    print(f"Модель: {published_onnx}")
    print(f"Манифест: {published_manifest}")
    print(
        "Проверка: python -m tools.wake_word.evaluate "
        f"--onnx {published_onnx.as_posix()}"
    )

    ww_evaluate.write_report(
        result.run_dir / "eval_report.md",
        [val, test],
        {
            "Дата": utc_now_iso(),
            "Чекпойнт": str(checkpoint),
            "Порог": f"{threshold:.2f}",
            "Паритет torch↔onnxruntime": f"{diff:.2e}",
        },
    )

    return result


# ─── CLI ────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Аргументы командной строки обучения."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.wake_word.train",
        description="Обучение слова-триггера «зере» и экспорт в ONNX.",
    )
    parser.add_argument("--data-dir", default="data/wakeword",
                        help="корень корпуса (по умолчанию data/wakeword)")
    parser.add_argument("--runs-dir", default=None,
                        help="куда писать прогоны (по умолчанию <data-dir>/runs)")
    parser.add_argument("--model-dir", default=str(MODEL_DIR),
                        help="куда положить готовую модель (ZERE.Voice/WakeWord/models)")
    parser.add_argument("--word", default="зере", help="слово-триггер")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                        help="устройство обучения")
    parser.add_argument("--epochs", type=int, default=40, help="число эпох")
    parser.add_argument("--batch-size", type=int, default=64, help="размер батча")
    parser.add_argument("--epoch-size", type=int, default=4000,
                        help="окон в эпохе (независимо от размера корпуса)")
    parser.add_argument("--lr", type=float, default=1e-3, help="скорость обучения AdamW")
    parser.add_argument("--weight-decay", type=float, default=1e-4, help="weight decay AdamW")
    parser.add_argument("--neg-per-pos", type=int, default=2,
                        help="сколько негативов на позитив (1…3)")
    parser.add_argument("--pos-weight", type=float, default=1.0,
                        help="вес положительного класса в BCE")
    parser.add_argument("--loss", default="bce", choices=["bce", "focal"],
                        help="функция потерь")
    parser.add_argument("--focal-gamma", type=float, default=2.0, help="гамма focal loss")
    parser.add_argument("--patience", type=int, default=6,
                        help="эпох без улучшения до остановки")
    parser.add_argument("--target-recall", type=float, default=ww_evaluate.TARGET_RECALL,
                        help="целевой recall для early stopping")
    parser.add_argument("--min-consecutive", type=int, default=1,
                        help="серий подряд при подборе порога (1 — без сглаживания)")
    parser.add_argument("--manifest-min-consecutive", type=int, default=DEFAULT_MIN_CONSECUTIVE,
                        help="min_consecutive для манифеста (рантайм)")
    parser.add_argument("--cooldown-ms", type=int, default=DEFAULT_COOLDOWN_MS,
                        help="cooldown_ms для манифеста (рантайм)")
    parser.add_argument("--val-hop", type=int, default=HOP_SAMPLES,
                        help="шаг окон по негативам на валидации (сэмплов)")
    parser.add_argument("--val-max-negative-windows", type=int, default=20000,
                        help="предел окон негативов на эпоху валидации (0 — без предела)")
    parser.add_argument("--num-workers", type=int, default=0,
                        help="процессов DataLoader (0 — в основном процессе)")
    parser.add_argument("--seed", type=int, default=0, help="зерно")
    parser.add_argument("--no-augment", action="store_true",
                        help="выключить аугментацию (для отладки)")
    parser.add_argument("--no-export", action="store_true",
                        help="не экспортировать ONNX после обучения")

    return parser


def _console_safe() -> None:
    """Вывод не должен ронять прогон из-за кодировки консоли.

    На Windows stdout по умолчанию cp1251, и первый же ``print`` со стрелкой
    («← лучшая») падал с UnicodeEncodeError — обучение умирало после первой
    эпохи, хотя чекпойнт уже был записан. Русский текст оставляем в кодировке
    консоли, а непереводимые символы заменяем, а не выбрасываем исключение.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа ``python -m tools.wake_word.train``."""
    _console_safe()
    args = build_parser().parse_args(argv)

    if not 1 <= args.neg_per_pos <= 3:
        print("Ошибка: --neg-per-pos должен быть 1…3 (спецификация баланса)", file=sys.stderr)
        return 2

    data_dir = Path(args.data_dir).resolve()
    config = TrainConfig(
        data_dir=data_dir,
        runs_dir=Path(args.runs_dir).resolve() if args.runs_dir else data_dir / "runs",
        model_dir=Path(args.model_dir),
        word=args.word,
        device=args.device,
        epochs=args.epochs,
        batch_size=args.batch_size,
        epoch_size=args.epoch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        neg_per_pos=args.neg_per_pos,
        pos_weight=args.pos_weight,
        loss=args.loss,
        focal_gamma=args.focal_gamma,
        patience=args.patience,
        target_recall=args.target_recall,
        min_consecutive=args.min_consecutive,
        manifest_min_consecutive=args.manifest_min_consecutive,
        cooldown_ms=args.cooldown_ms,
        val_hop=args.val_hop,
        val_max_negative_windows=args.val_max_negative_windows,
        num_workers=args.num_workers,
        seed=args.seed,
        augment=not args.no_augment,
        export=not args.no_export,
    )

    try:
        fit(config)
    except FileNotFoundError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    except ww_data.SplitError as error:
        # Разбиение не покрывает train/val/test: это не «вообще нет данных», а
        # конкретная проблема раскладки — сообщение уже говорит, что делать.
        print(f"Ошибка разбиения.\n{error}", file=sys.stderr)
        return 2
    except OnnxExportUnavailable as error:
        # onnx и onnxruntime — разные пакеты; сообщение объясняет это прямо.
        print(f"Ошибка экспорта ONNX.\n{error}", file=sys.stderr)
        return 4
    except ModuleNotFoundError as error:
        print(
            f"Ошибка: не хватает модуля ({error.name}). Для обучения нужен torch: "
            "pip install torch (GPU-сборка ставится с https://pytorch.org)",
            file=sys.stderr,
        )
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
