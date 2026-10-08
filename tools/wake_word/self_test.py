"""Смоук-тест всего конвейера БЕЗ реальных данных — должен проходить за < 2 минут.

Зачем: обучение на живых записях длится долго, и ошибка в экспорте ONNX
обнаружилась бы только в конце. Этот тест прогоняет весь путь на синтетике —
генерация «слов» и «фона», разбиение, датасет с аугментациями, две эпохи на
CPU, экспорт ONNX, паритет torch↔onnxruntime, манифест — и печатает ``OK``.

Что проверяется по-настоящему (а не «код не упал»):

1. **Математика frontend.** Базис ДПФ, посчитанный через ``Conv1d``, сверяется
   с независимой реализацией на numpy-FFT. Если матрица базиса «поедет»,
   признаки изменятся незаметно для глаза, но модель обучится на мусоре.
2. **Контракт ONNX.** Имена ``audio``/``score``, формы ``(batch, 16000)`` и
   ``(batch, 1)``, opset 17, отсутствие операторов DFT/STFT.
3. **Паритет.** Расхождение torch и onnxruntime < 1e-3 (реально ~1e-7).
4. **Диапазон.** ``score`` лежит в [0, 1] — в графе есть сигмоида.
5. **Манифест.** Набор ключей ровно тот, что читают рантаймы.
6. **Разбиение.** Группы записей не пересекаются между train/val/test.

Всё пишется в временный каталог: тест НЕ трогает ``data/wakeword`` и
``ZERE.Voice/WakeWord/models``. Ключ ``--keep`` оставляет каталог для разбора.

Запуск:
    python -m tools.wake_word.self_test
    python -m tools.wake_word.self_test --keep
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

#: Ключи манифеста — ровно контракт (порядок и состав).
EXPECTED_MANIFEST_KEYS: tuple[str, ...] = (
    "engine", "format", "word", "sample_rate", "window_samples", "hop_samples",
    "threshold", "min_consecutive", "cooldown_ms", "input_name", "output_name",
    "trained_at", "metrics", "torch_version", "positives", "negatives_hours",
)

EXPECTED_METRIC_KEYS: tuple[str, ...] = (
    "test_recall", "test_fa_per_hour", "val_recall", "val_fa_per_hour",
)

#: Операторы, которых в графе быть НЕ должно: их поддержка в onnxruntime
#: различается по версиям, и именно ради этого STFT считается свёрткой.
FORBIDDEN_OPS: frozenset[str] = frozenset({"DFT", "STFT", "RFFT", "FFT", "IFFT"})


class SelfTestFailure(AssertionError):
    """Проверка конвейера не прошла (сообщение — что именно сломалось)."""


def check(condition: bool, message: str) -> None:
    """Утверждение с понятным текстом (без «assert» в выводе пользователю)."""
    if not condition:
        raise SelfTestFailure(message)


# ─── Синтетический корпус ───────────────────────────────────────


def synth_word(rng: Any, sample_rate: int = 16000, duration: float = 0.45) -> Any:
    """Синтетическое «слово»: три форманты с огибающей и шумовым придыханием.

    Не настоящая речь, но у него есть то, за что может зацепиться CNN:
    формантная структура (набор частот) и характерная длительность. Для
    смоук-теста этого достаточно — проверяется конвейер, а не качество.
    """
    import numpy as np  # noqa: PLC0415

    count = int(duration * sample_rate)
    time_axis = np.arange(count) / sample_rate

    # Огибающая: плавная атака и спад, чтобы не было щелчков на краях.
    envelope = np.sin(np.pi * np.linspace(0.0, 1.0, count)) ** 1.5

    formants = (520.0, 1480.0, 2560.0)
    signal = np.zeros(count, dtype="float64")

    for index, frequency in enumerate(formants):
        # Небольшой случайный сдвиг формант: примеры не должны быть
        # побитово одинаковыми, иначе val/test неотличимы от train.
        shifted = frequency * float(rng.uniform(0.9, 1.1))
        signal += (0.6 ** index) * np.sin(2.0 * np.pi * shifted * time_axis)

    signal += 0.05 * rng.standard_normal(count)
    signal *= envelope

    peak = float(np.max(np.abs(signal)) + 1e-9)
    return (signal / peak * 0.7).astype("float32")


def synth_background(rng: Any, duration: float,
                     sample_rate: int = 16000) -> Any:
    """Синтетический фон: шум, гул и «чужая речь» без формант слова."""
    import numpy as np  # noqa: PLC0415

    count = int(duration * sample_rate)
    time_axis = np.arange(count) / sample_rate

    kind = int(rng.integers(0, 3))

    if kind == 0:
        signal = 0.2 * rng.standard_normal(count)  # широкополосный шум
    elif kind == 1:
        signal = 0.3 * np.sin(2.0 * np.pi * 120.0 * time_axis)  # гул
        signal += 0.05 * rng.standard_normal(count)
    else:
        # «Речь»: скользящая частота, но БЕЗ формантной структуры слова.
        sweep = 300.0 + 200.0 * np.sin(2.0 * np.pi * 1.5 * time_axis)
        signal = 0.3 * np.sin(2.0 * np.pi * sweep * time_axis)
        signal += 0.05 * rng.standard_normal(count)

    return np.clip(signal, -1.0, 1.0).astype("float32")


def build_synthetic_corpus(root: Path, seed: int = 0) -> dict[str, int]:
    """Раскладывает синтетический корпус по каталогам ``data/wakeword``.

    Файлы раскладываются по подпапкам-«сессиям»: так у групп разные ключи, и
    проверяется настоящее групповое разбиение, а не его аварийная ветка.
    """
    import numpy as np  # noqa: PLC0415

    from tools.wake_word import data as ww_data

    rng = np.random.default_rng(seed)
    ww_data.ensure_data_dirs(root)

    counts = {"positive": 0, "negative": 0}

    for session in ("session1", "session2", "session3"):
        for index in range(4):
            path = root / ww_data.POSITIVE_DIR / session / f"zere_{index:04d}.wav"
            ww_data.write_wav(path, synth_word(rng), ww_data.SAMPLE_RATE)
            counts["positive"] += 1

        # Синтез TTS: те же «слова», но другие — чтобы категория не пустовала.
        for index in range(3):
            path = root / ww_data.POSITIVE_SYNTH_DIR / session / f"zere_tts_{index:04d}.wav"
            ww_data.write_wav(path, synth_word(rng, duration=0.5), ww_data.SAMPLE_RATE)
            counts["positive"] += 1

    # Негативы: длинные файлы (по 3 с) — из них нарезаются окна, а FA/час
    # считается по непрерывному аудио.
    for category, sessions in (
        (ww_data.NEGATIVE_SPEECH_DIR, ("session1", "session2")),
        (ww_data.NEGATIVE_NOISE_DIR, ("session1", "session2")),
        (ww_data.NEGATIVE_ROOM_DIR, ("session1",)),
        (ww_data.NEGATIVE_HARD_DIR, ("session1",)),
    ):
        for session in sessions:
            for index in range(2):
                path = root / category / session / f"bg_{index:04d}.wav"
                ww_data.write_wav(path, synth_background(rng, 3.0), ww_data.SAMPLE_RATE)
                counts["negative"] += 1

    # Импульсный отклик: проверяет ветку реверберации в аугментациях.
    ww_data.write_wav(
        root / ww_data.IMPULSE_DIR / "room_0001.wav",
        synth_background(rng, 0.25) * 0.3,
        ww_data.SAMPLE_RATE,
    )

    return counts


# ─── Проверки ───────────────────────────────────────────────────


def verify_frontend_math() -> float:
    """Сверяет признаки из ``Conv1d``-ДПФ с независимым numpy-FFT.

    Это главная проверка frontend: если она проходит, DSP в графе считается
    верно, и расхождение с эталонным librosa будет только в пределах
    float32. Порог 1e-4 — с запасом на разницу float32/float64 в окне и FFT.
    """
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    from tools.wake_word.model import WINDOW_SAMPLES, WakeWordNet, reference_features

    model = WakeWordNet()
    model.eval()

    rng = np.random.default_rng(1234)
    audio = rng.uniform(-0.9, 0.9, size=WINDOW_SAMPLES).astype("float32")

    with torch.no_grad():
        features = model.frontend(torch.from_numpy(audio)[None, :])[0, 0].numpy()

    reference = reference_features(audio)

    check(
        features.shape == reference.shape,
        f"форма признаков {features.shape} != эталона {reference.shape}",
    )

    diff = float(np.max(np.abs(features - reference)))
    check(
        diff < 1e-4,
        f"признаки frontend расходятся с numpy-FFT на {diff:.3g}: "
        "проверьте базис ДПФ, окно Ханна и мел-фильтры",
    )

    return diff


def verify_normalization() -> None:
    """Пер-оконная нормализация обязана давать среднее ~0 и std ~1."""
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    from tools.wake_word.model import WINDOW_SAMPLES, WakeWordNet

    model = WakeWordNet()
    model.eval()

    rng = np.random.default_rng(7)
    batch = rng.uniform(-0.5, 0.5, size=(3, WINDOW_SAMPLES)).astype("float32")

    with torch.no_grad():
        features = model.frontend(torch.from_numpy(batch))

    means = features.mean(dim=(1, 2, 3)).numpy()
    stds = features.std(dim=(1, 2, 3), unbiased=False).numpy()

    check(
        float(np.max(np.abs(means))) < 1e-4,
        f"среднее после нормализации не ноль: {means}",
    )
    # std = 1 только если std сигнала >> 1e-5 (на цифровой тишине
    # нормализация делит на 1e-5 и даёт нули — это ожидаемо).
    check(
        bool(np.all((stds > 0.9) & (stds < 1.1))),
        f"std после нормализации не единица: {stds}",
    )


def verify_onnx_graph(onnx_path: Path) -> dict[str, Any]:
    """Проверяет контракт графа: имена, формы, opset, отсутствие DFT/STFT."""
    import onnx  # noqa: PLC0415

    from tools.wake_word.model import INPUT_NAME, OUTPUT_NAME, WINDOW_SAMPLES

    graph = onnx.load(str(onnx_path)).graph

    check(len(graph.input) == 1, f"у графа {len(graph.input)} входов, ожидался один")
    check(len(graph.output) == 1, f"у графа {len(graph.output)} выходов, ожидался один")

    input_node = graph.input[0]
    output_node = graph.output[0]

    check(
        input_node.name == INPUT_NAME,
        f"имя входа «{input_node.name}» != «{INPUT_NAME}»",
    )
    check(
        output_node.name == OUTPUT_NAME,
        f"имя выхода «{output_node.name}» != «{OUTPUT_NAME}»",
    )

    input_dims = [dim.dim_value or dim.dim_param for dim in input_node.type.tensor_type.shape.dim]
    output_dims = [
        dim.dim_value or dim.dim_param for dim in output_node.type.tensor_type.shape.dim
    ]

    check(input_dims[0] in ("batch", ""), f"ось 0 входа не динамическая: {input_dims}")
    check(
        input_dims[1] == WINDOW_SAMPLES,
        f"окно входа {input_dims[1]} != {WINDOW_SAMPLES} сэмплов",
    )
    check(
        output_dims[0] in ("batch", ""),
        f"ось 0 выхода не динамическая: {output_dims}",
    )
    check(output_dims[1] == 1, f"выход не (batch, 1): {output_dims}")

    ops = {node.op_type for node in graph.node}
    forbidden = ops & FORBIDDEN_OPS

    check(
        not forbidden,
        f"в графе есть операторы {sorted(forbidden)}: onnxruntime может их не "
        "поддержать — STFT должен считаться свёрткой с базисом ДПФ",
    )

    opset = onnx.load(str(onnx_path)).opset_import[0].version
    check(opset == 17, f"opset {opset} вместо 17")

    return {"ops": sorted(ops), "opset": opset, "input": input_dims, "output": output_dims}


def verify_dataset_samples(data_root: Path) -> dict[str, Any]:
    """Проверяет, что датасет отдаёт окна нужной формы и оба класса."""
    from tools.wake_word import data as ww_data

    dataset = ww_data.dataset_for_split(
        data_root, "train", epoch_size=32, positive_ratio=0.5, augment=True, seed=3
    )

    check(len(dataset) == 32, f"длина датасета {len(dataset)} вместо 32")

    shapes: set[tuple[int, ...]] = set()
    labels: set[float] = set()

    for index in range(len(dataset)):
        window, label = dataset[index]
        shapes.add(tuple(window.shape))
        labels.add(float(label.item()))

        low, high = float(window.min()), float(window.max())
        check(
            -1.0001 <= low and high <= 1.0001,
            f"значения окна вне [-1, 1]: [{low:.4f}, {high:.4f}]",
        )

    check(shapes == {(ww_data.WINDOW_SAMPLES,)}, f"формы окон: {shapes}")
    check(labels == {0.0, 1.0}, f"в датасете не оба класса: {labels}")

    return {"shapes": sorted(shapes), "labels": sorted(labels)}


def verify_splits_are_grouped(data_root: Path) -> dict[str, str]:
    """Проверяет групповую изоляцию И покрытие train/val/test.

    Группы берутся тем же помощником, что и в :func:`build_splits`
    (``index_group``), а не пересчитываются «по-своему»: своя формула в тесте
    дала бы ложную тревогу или, что хуже, пропустила бы утечку.

    Покрытие проверяется отдельно и жёстко: разбиение без позитивов даёт
    ``recall = 0`` по пустому множеству, и это выглядит как плохая модель,
    хотя модель тут ни при чём. Такая ошибка обязана быть громкой.
    """
    from tools.wake_word import data as ww_data

    payload = ww_data.build_splits(data_root, seed=99)
    splits = payload["splits"]

    owners: dict[tuple[str, str], str] = {}
    groups_in_payload = payload["groups"]

    for name, members in splits.items():
        for member in members:
            # Группа считается тем же помощником, что и в build_splits:
            # «своя» формула здесь уже давала ложную тревогу об утечке.
            group = ww_data.split_group_of(data_root, member)

            previous = owners.get(group)

            check(
                previous is None or previous == name,
                f"группа «{group[0]}/{group[1]}» попала и в {previous}, и в "
                f"{name}: val/test пересекаются с train, метрики будут завышены",
            )
            owners[group] = name

            recorded = groups_in_payload.get(f"{group[0]}/{group[1]}")

            check(
                recorded == name,
                f"файл {member} лежит в {name}, а карта групп говорит {recorded}",
            )

    coverage = payload.get("coverage", {})

    for name in ("train", "val", "test"):
        check(splits[name], f"разбиение {name} пустое")
        check(name in coverage, f"в splits.json нет покрытия для {name}")

        info = coverage[name]
        check(
            info.get("positive", 0) > 0,
            f"в разбиении {name} нет позитивов: recall посчитается по пустому "
            "множеству и даст 0 — это ошибка разбиения, а не плохая модель",
        )
        check(
            info.get("negative", 0) > 0,
            f"в разбиении {name} нет негативов: FA/час посчитается по пустому "
            "множеству и даст 0",
        )

    # Разбиение обязано быть воспроизводимым: то же зерно — те же файлы.
    again = ww_data.build_splits(data_root, seed=99)["splits"]

    for name in ("train", "val", "test"):
        check(
            sorted(again[name]) == sorted(splits[name]),
            f"разбиение {name} не воспроизводится при том же зерне",
        )

    return {
        name: f"{coverage[name]['files']}ф {coverage[name]['positive']}п "
              f"{coverage[name]['negative']}н"
        for name in ("train", "val", "test")
    }


def verify_split_error_is_loud(work_dir: Path) -> str:
    """Неполное разбиение обязано падать с понятной ошибкой, а не молчать.

    Собираем заведомо недостаточный корпус: позитивы одной сессии и один
    негативный файл на три разбиения. Покрытие недостижимо, поэтому вместо
    нулевых метрик должен быть :class:`SplitError` с объяснением, чего не
    хватает. Без этой проверки регрессия вернула бы `recall = 0` на test, и
    её приняли бы за слабую модель.
    """
    import numpy as np  # noqa: PLC0415

    from tools.wake_word import data as ww_data

    root = work_dir / "poor" / "data" / ww_data.DATA_DIR_NAME
    ww_data.ensure_data_dirs(root)

    rng = np.random.default_rng(5)

    # Одна сессия: имена без номера сессии → все файлы в одной группе.
    for index in range(4):
        ww_data.write_wav(
            root / ww_data.POSITIVE_DIR / f"zere_{index:04d}.wav",
            synth_word(rng), ww_data.SAMPLE_RATE,
        )

    ww_data.write_wav(
        root / ww_data.NEGATIVE_NOISE_DIR / "bg.wav",
        synth_background(rng, 2.0), ww_data.SAMPLE_RATE,
    )

    try:
        ww_data.build_splits(root, seed=1)
    except ww_data.SplitError as error:
        message = str(error)

        check(
            "позитив" in message and "сесси" in message,
            "ошибка разбиения не объясняет, что делать с позитивами:\n" + message,
        )

        return message.strip().splitlines()[0]

    raise SelfTestFailure(
        "разбиение с одной группой позитивов и одним негативом НЕ упало: "
        "val/test остались бы без позитивов, и метрики молча вышли нулевыми"
    )


def verify_manifest(manifest_path: Path) -> dict[str, Any]:
    """Манифест: ровно контрактные ключи и осмысленные значения."""
    from tools.wake_word.model import (
        HOP_SAMPLES,
        INPUT_NAME,
        OUTPUT_NAME,
        OUTPUT_NAME as _OUTPUT,
        SAMPLE_RATE,
        WINDOW_SAMPLES,
    )

    check(manifest_path.is_file(), f"манифест не создан: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    keys = tuple(payload.keys())

    check(
        keys == EXPECTED_MANIFEST_KEYS,
        "ключи манифеста не совпадают с контрактом.\n"
        f"  получено: {keys}\n  ожидалось: {EXPECTED_MANIFEST_KEYS}",
    )

    check(payload["engine"] == "onnx-kws", f"engine={payload['engine']!r}")
    check(payload["format"] == 1, f"format={payload['format']!r}")
    check(payload["sample_rate"] == SAMPLE_RATE, f"sample_rate={payload['sample_rate']!r}")
    check(
        payload["window_samples"] == WINDOW_SAMPLES,
        f"window_samples={payload['window_samples']!r}",
    )
    check(payload["hop_samples"] == HOP_SAMPLES, f"hop_samples={payload['hop_samples']!r}")
    check(payload["input_name"] == INPUT_NAME, f"input_name={payload['input_name']!r}")
    check(payload["output_name"] in (OUTPUT_NAME, _OUTPUT), "output_name не score")
    check(
        0.0 <= float(payload["threshold"]) <= 1.0,
        f"порог вне [0, 1]: {payload['threshold']}",
    )
    check(
        tuple(payload["metrics"].keys()) == EXPECTED_METRIC_KEYS,
        f"ключи metrics не по контракту: {tuple(payload['metrics'].keys())}",
    )
    check(payload["trained_at"], "trained_at пуст")
    check(payload["torch_version"], "torch_version пуст")

    return payload


# ─── Прогон ─────────────────────────────────────────────────────


def run_self_test(work_dir: Path, verbose: bool = True) -> dict[str, Any]:
    """Прогоняет весь конвейер на синтетике; бросает SelfTestFailure при сбое."""
    from tools.wake_word import data as ww_data
    from tools.wake_word import evaluate as ww_evaluate
    from tools.wake_word.model import verify_onnx_parity

    data_root = work_dir / "data" / ww_data.DATA_DIR_NAME
    models_dir = work_dir / "models"

    def step(number: int, title: str) -> None:
        if verbose:
            print(f"[{number}/9] {title} ... ", end="", flush=True)

    def done(detail: str = "") -> None:
        if verbose:
            print(f"ок{f' ({detail})' if detail else ''}")

    step(1, "Синтетический корпус")
    counts = build_synthetic_corpus(data_root, seed=0)
    done(f"позитивов {counts['positive']}, негативов {counts['negative']}")

    step(2, "Математика frontend (Conv1d-ДПФ против numpy-FFT)")
    frontend_diff = verify_frontend_math()
    done(f"расхождение {frontend_diff:.2e}")

    step(3, "Пер-оконная нормализация")
    verify_normalization()
    done("mean≈0, std≈1")

    step(4, "Разбиение train/val/test: изоляция групп + покрытие")
    split_counts = verify_splits_are_grouped(data_root)
    done(" ".join(f"{name}={info}" for name, info in split_counts.items()))

    step(5, "Громкая ошибка на неполном разбиении")
    loud_error = verify_split_error_is_loud(work_dir)
    done(loud_error)

    step(6, "Датасет и аугментации")
    dataset_info = verify_dataset_samples(data_root)
    done(f"окна {dataset_info['shapes']}, метки {dataset_info['labels']}")

    step(7, "Обучение 2 эпохи на CPU")
    from tools.wake_word.train import TrainConfig, fit

    config = TrainConfig(
        data_dir=data_root,
        runs_dir=work_dir / "runs",
        model_dir=models_dir,
        word="зере",
        device="cpu",
        epochs=2,
        batch_size=16,
        epoch_size=64,
        lr=1e-3,
        neg_per_pos=2,
        patience=3,
        num_workers=0,
        seed=0,
        augment=True,
        export=True,
        val_max_negative_windows=400,
    )
    result = fit(config)

    check(result.best_checkpoint.is_file(), f"чекпойнт не создан: {result.best_checkpoint}")
    check(result.model_path is not None, "модель не опубликована в каталог прогона")
    done(f"loss {result.history[-1].train_loss:.4f}")

    step(8, "Контракт ONNX и паритет torch↔onnxruntime")
    import torch  # noqa: PLC0415

    from tools.wake_word.model import WakeWordNet

    graph_info = verify_onnx_graph(result.model_path)

    model = WakeWordNet()
    payload = torch.load(str(result.best_checkpoint), map_location="cpu", weights_only=False)
    model.load_state_dict(payload["model_state"])

    parity = verify_onnx_parity(model, result.model_path)
    done(f"ops {len(graph_info['ops'])}, расхождение {parity:.2e}")

    step(9, "Манифест, отчёт оценки и метрики test")
    manifest = verify_manifest(result.manifest_path)
    report = result.run_dir / "eval_report.md"

    check(report.is_file(), f"отчёт оценки не создан: {report}")

    # Метрики на test обязаны быть посчитаны по НЕПУСТЫМ множествам: именно
    # эта проверка ловит «recall=0 из-за разбиения», а не из-за модели.
    metrics = manifest["metrics"]
    done(
        f"порог {manifest['threshold']}, "
        f"test recall={metrics['test_recall']:.3f} "
        f"FA/час={metrics['test_fa_per_hour']:.2f}"
    )

    # Каталог прогона обязан содержать и metrics.csv — иначе обучение
    # невозможно разобрать постфактум.
    check(
        (result.run_dir / "metrics.csv").is_file(),
        f"нет metrics.csv в {result.run_dir}",
    )

    # Отчёт «порог → recall / FA/час» должен быть непустым: если негативов
    # нет, таблица окажется пустой и подбирать порог будет не на чем.
    check(manifest["metrics"], "metrics в манифесте пуст")

    return {
        "frontend_diff": frontend_diff,
        "parity": parity,
        "graph": graph_info,
        "splits": split_counts,
        "split_error": loud_error,
        "manifest": manifest,
        "metrics": manifest["metrics"],
        "run_dir": str(result.run_dir),
        "model": str(result.model_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа ``python -m tools.wake_word.self_test``."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.wake_word.self_test",
        description="Смоук-тест конвейера обучения слова-триггера на синтетике.",
    )
    parser.add_argument("--keep", action="store_true",
                        help="не удалять временный каталог (для разбора)")
    parser.add_argument("--quiet", action="store_true", help="печатать только итог")
    args = parser.parse_args(argv)

    started = time.monotonic()

    # Проверяем зависимости ДО работы: без torch конвейер не проверить, и
    # честнее сказать об этом сразу, чем упасть на импорте внутри.
    try:
        import torch  # noqa: PLC0415
    except ImportError:
        print(
            "ОШИБКА: torch не установлен — конвейер обучения не проверить.\n"
            "  Установка (CPU): python -m pip install torch --index-url "
            "https://download.pytorch.org/whl/cpu\n"
            "  Установка (GPU): python -m pip install torch --index-url "
            "https://download.pytorch.org/whl/cu124\n"
            "  В проекте torch уже приходит с ChatTTS (requirements.txt).",
            file=sys.stderr,
        )
        return 3

    try:
        import onnxruntime  # noqa: F401,PLC0415
    except ImportError:
        print(
            "ОШИБКА: onnxruntime не установлен — паритет torch↔ONNX не проверить.\n"
            "  Установка: python -m pip install onnxruntime",
            file=sys.stderr,
        )
        return 3

    # onnx и onnxruntime — разные пакеты: первый нужен только для ЭКСПОРТА
    # графа из torch, второй — чтобы его исполнять. Проверяем оба, иначе тест
    # упал бы внутренней ошибкой torch на шаге экспорта.
    try:
        import onnx  # noqa: F401,PLC0415
    except ImportError:
        print(
            "ОШИБКА: пакет onnx не установлен — экспорт модели в ONNX не проверить.\n"
            "  Установка: python -m pip install onnx\n"
            "  Это НЕ onnxruntime: onnxruntime исполняет модель, onnx её "
            "сериализует (в рантайме onnx не нужен).",
            file=sys.stderr,
        )
        return 3

    work_dir = Path(tempfile.mkdtemp(prefix="ww_self_test_"))
    print(f"torch {torch.__version__}, каталог: {work_dir}")
    print("-" * 68)

    try:
        info = run_self_test(work_dir, verbose=not args.quiet)
    except SelfTestFailure as failure:
        print("\n" + "=" * 68)
        print("ПРОВАЛ СМОУК-ТЕСТА")
        print(f"  {failure}")
        print("=" * 68)
        print(f"Каталог прогона: {work_dir}")

        return 1
    except FileNotFoundError as error:
        print("\nПРОВАЛ: не хватает данных/файлов")
        print(f"  {error}")
        return 1
    except Exception as error:  # noqa: BLE001 — показываем причину, а не стек
        # Сюда попадают SplitError (неполное разбиение) и
        # OnnxExportUnavailable (нет пакета onnx): у обоих уже есть понятный
        # русский текст, и стектрейс тут только мешает.
        if type(error).__name__ in ("SplitError", "OnnxExportUnavailable"):
            print("\nПРОВАЛ СМОУК-ТЕСТА")
            print(f"  {error}")
            print(f"\nКаталог прогона: {work_dir}")

            return 1

        raise

    elapsed = time.monotonic() - started

    print("-" * 68)
    print(
        f"frontend: расхождение с numpy-FFT {info['frontend_diff']:.2e}; "
        f"паритет torch↔onnxruntime {info['parity']:.2e}"
    )
    print(f"граф: opset {info['graph']['opset']}, {len(info['graph']['ops'])} операторов")
    print(
        "разбиение (файлов/позитивов/негативов): "
        + "; ".join(f"{name} {value}" for name, value in info["splits"].items())
    )
    print(
        f"test: recall={info['metrics']['test_recall']:.3f} "
        f"FA/час={info['metrics']['test_fa_per_hour']:.2f} "
        f"порог={info['manifest']['threshold']}"
    )
    print(f"модель: {info['model']}")
    print(f"время: {elapsed:.1f} с")

    if args.keep:
        print(f"Временный каталог сохранён: {work_dir}")
    else:
        shutil.rmtree(work_dir, ignore_errors=True)

    print("OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
