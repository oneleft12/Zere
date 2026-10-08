"""Замороженный контракт модели и манифеста — БЕЗ зависимости от torch.

Константы аудио/признаков и разбор манифеста нужны всем шагам конвейера, но
torch для этого не требуется. Если держать их в :mod:`tools.wake_word.model`,
то ``import model`` тянет torch, и тогда:

* ``record_positives`` / ``build_negatives`` не запускаются в окружении без
  torch (а записывать голос и раскладывать шум — можно и без него);
* ``evaluate --onnx`` требует torch, хотя оценивает уже готовый ONNX-файл и
  работает на одном onnxruntime.

Поэтому контракт вынесен в отдельный модуль, а :mod:`model` его
переэкспортирует — прежние импорты вида
``from tools.wake_word.model import SAMPLE_RATE`` продолжают работать.

Значения здесь — часть замороженного контракта: их изменение делает
несовместимыми уже обученные модели и рантаймы обеих редакций.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── Контракт аудио ─────────────────────────────────────────────

SAMPLE_RATE = 16000
WINDOW_SAMPLES = 16000  # ровно 1.0 с — размер окна детектора
HOP_SAMPLES = 640  # 40 мс — шаг рантайма (в графе не используется)

# ─── Контракт frontend ──────────────────────────────────────────

N_FFT = 256
WIN_LENGTH = 256
HOP_LENGTH = 160
FMIN = 0.0
FMAX = 8000.0
N_MELS = 40

#: С кадров при center=False: 1 + (16000 - 256) // 160 = 99.
N_FRAMES = 1 + (WINDOW_SAMPLES - WIN_LENGTH) // HOP_LENGTH

#: Логарифм от mel-мощности; 1e-6 не даёт log(0) у тишины.
LOG_EPS = 1e-6

#: Пер-оконная нормализация: std + 1e-5 (защита от деления на ноль на тишине).
NORM_EPS = 1e-5

#: Имена входов/выходов графа — часть замороженного контракта.
INPUT_NAME = "audio"
OUTPUT_NAME = "score"

#: Порог и сглаживание по умолчанию (train.py подберёт порог точнее).
DEFAULT_THRESHOLD = 0.7
DEFAULT_MIN_CONSECUTIVE = 2
DEFAULT_COOLDOWN_MS = 1800

ONNX_OPSET = 17


# ─── Манифест модели ────────────────────────────────────────────


@dataclass
class Manifest:
    """Манифест рядом с ONNX-моделью (ровно этот набор ключей читает рантайм).

    Ключи и их порядок — часть контракта: рантайм обеих редакций разбирает
    файл как JSON-объект, а человек читает его глазами.
    """

    engine: str = "onnx-kws"
    format: int = 1
    word: str = "зере"
    sample_rate: int = SAMPLE_RATE
    window_samples: int = WINDOW_SAMPLES
    hop_samples: int = HOP_SAMPLES
    threshold: float = DEFAULT_THRESHOLD
    min_consecutive: int = DEFAULT_MIN_CONSECUTIVE
    cooldown_ms: int = DEFAULT_COOLDOWN_MS
    input_name: str = INPUT_NAME
    output_name: str = OUTPUT_NAME
    trained_at: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    torch_version: str = ""
    positives: int = 0
    negatives_hours: float = 0.0

    def to_json(self) -> str:
        """JSON-строка манифеста (UTF-8, ключи в порядке контракта)."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

    def write(self, path: str | Path) -> Path:
        """Записывает манифест рядом с моделью."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")

        return target

    @staticmethod
    def read(path: str | Path) -> dict[str, Any]:
        """Читает манифест как словарь (для evaluate и проверок контракта)."""
        return json.loads(Path(path).read_text(encoding="utf-8"))


def utc_now_iso() -> str:
    """Метка времени обучения в ISO-8601 UTC (``2026-10-08T21:00:00Z``)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: Транслитерация для имени файла модели: рантайм ищет ``wake_<слово>.onnx``
#: по латинице, а слово в проекте русское («зере» → ``wake_zere.onnx``).
_TRANSLIT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def word_slug(word: str) -> str:
    """Латинский слаг слова для имени файла модели (``зере`` → ``zere``).

    Если после транслитерации не осталось букв/цифр (экзотическое слово),
    берётся устойчивый хеш: имя файла всё равно должно быть предсказуемым и
    одинаковым на Windows и в WSL.
    """
    letters = [
        _TRANSLIT.get(char, char)
        for char in (word or "").strip().lower()
        if char.isalnum() or char in _TRANSLIT
    ]
    slug = "".join(letters)
    slug = "".join(char for char in slug if char.isalnum() or char in "_-")

    return slug or hashlib.sha1((word or "").encode("utf-8")).hexdigest()[:8]


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
    "Manifest",
    "N_FFT",
    "N_FRAMES",
    "N_MELS",
    "NORM_EPS",
    "ONNX_OPSET",
    "OUTPUT_NAME",
    "SAMPLE_RATE",
    "WINDOW_SAMPLES",
    "WIN_LENGTH",
    "utc_now_iso",
    "word_slug",
]
