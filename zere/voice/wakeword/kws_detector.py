"""Стриминговый детектор ключевого слова (keyword spotting) для ZERE.

Зачем: `docs/VOICE_PERF_STABILITY_ANALYSIS.md`, S2. Прежний детектор
(`wake_word_detector.WakeWordDetector`) — это энергетический VAD плюс
ПОЛНЫЙ STT на каждый всплеск речи и сравнение строк: любая речь в комнате
(ТВ, разговор) запускала распознавание сегмента до 9 с, жгла CPU и давала
ложные срабатывания, а запись сегмента ещё и сохранялась на диск.

Здесь вместо ASR — одна крошечная ONNX-модель «окно 1 с → вероятность
слова» (~50–100 тыс. параметров, весь DSP внутри графа), обученная под
одно конкретное слово. Поток считается прямо из аудиозахвата:

    аудио 16 кГц → кольцевой буфер → окно 1 с каждые 40 мс
      → ONNX (log-mel + CNN) → вероятность
      → сглаживание (N подряд ≥ порога) → cooldown → срабатывание

Что это даёт: нет второго потока записи, нет файлов на диске, нет вызовов
STT до срабатывания, задержка «слово → индикатор» ≈ hop + сглаживание
(единицы десятков миллисекунд) плюс сама модель, а не секунды.

Контракт модели (её обучает `tools/wake_word/`):
- `ZERE.Voice/WakeWord/models/wake_<слово>.onnx` — вход `audio`
  float32 (batch, window_samples), значения [-1, 1]; выход `score`
  float32 (batch, 1) — вероятность слова в окне;
- `wake_<слово>.json` рядом — манифест (sample_rate, window_samples,
  hop_samples, threshold, min_consecutive, cooldown_ms, имена входов).

Модель можно задать явно через `config.wake_model_path`. Если модели нет,
фабрика `create_wake_detector()` отдаёт прежний детектор на STT — голосовой
режим не ломается (см. `zere/voice/wakeword/__init__.py`).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from zere import paths
from zere.voice.audio.continuous_audio_recorder import ContinuousAudioRecorder
from zere.voice.voice_config import VoiceConfig

#: Папка с моделями wake word. Модели коммитятся (файл < 1 МБ): установщику
#: не нужен ни download, ни SHA — в отличие от GigaAM/Whisper.
MODEL_DIR: Path = paths.VOICE_DIR / "WakeWord" / "models"

#: Дефолты манифеста (если `.json` рядом с моделью отсутствует или битый).
DEFAULT_MANIFEST: dict[str, Any] = {
    "sample_rate": 16000,
    "window_samples": 16000,   # 1.0 с — окно модели
    "hop_samples": 640,        # 40 мс — шаг инференса
    "threshold": 0.7,
    "min_consecutive": 2,      # кадров подряд ≥ порога для срабатывания
    "cooldown_ms": 1800,       # пауза после срабатывания
    "input_name": "audio",
    "output_name": "score",
}

#: Русские буквы → латиница (имя файла модели: wake_zere.onnx).
_TRANSLIT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    """«зере» → «zere» (имя файла модели). Не-буквы отбрасываются."""
    result: list[str] = []

    for char in text.strip().lower():
        if char in _TRANSLIT:
            result.append(_TRANSLIT[char])
        elif char.isalnum() and char.isascii():
            result.append(char)

    return "".join(result) or "wake"


def model_path_for(word: str) -> Path:
    """Путь к модели по слову-триггеру: wake_<транслит>.onnx."""
    return MODEL_DIR / f"wake_{transliterate(word)}.onnx"


def manifest_path_for(model_path: Path) -> Path:
    """Манифест рядом с моделью: wake_zere.onnx → wake_zere.json."""
    return model_path.with_suffix(".json")


def resolve_model_path(config: VoiceConfig) -> Optional[Path]:
    """Находит модель: явный путь из конфига, иначе папка моделей.

    Возвращает None, если файла нет (фабрика уйдёт на прежний STT-детектор).
    """
    explicit = str(getattr(config, "wake_model_path", "") or "").strip()

    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = paths.PROJECT_ROOT / path
        return path if path.exists() else None

    candidate = model_path_for(str(getattr(config, "wake_word", "") or "зере"))
    return candidate if candidate.exists() else None


def load_manifest(model_path: Path) -> dict[str, Any]:
    """Читает манифест модели, дополняя недостающие ключи дефолтами."""
    manifest = dict(DEFAULT_MANIFEST)
    path = manifest_path_for(model_path)

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                manifest.update(data)
        except (OSError, json.JSONDecodeError):
            print(f"⚠️ Манифест модели битый ({path}) — беру дефолты")

    return manifest


def onnx_available() -> bool:
    """Есть ли onnxruntime (без него KWS-движок недоступен)."""
    try:
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001 — ImportError или сбой нативной либы
        return False

    return True


def default_session_factory(model_path: Path) -> Any:
    """Создаёт сессию onnxruntime (CPU: модель крошечная, GPU не нужен).

    Ленивый импорт: без onnxruntime ZERE работает на прежнем детекторе,
    а не падает при импорте модуля.
    """
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3          # только ошибки
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1        # модель крошечная: 1 поток дешевле

    return ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )


class _RingBuffer:
    """Кольцевой буфер float32: пишем блоки, читаем последние N сэмплов."""

    def __init__(self, capacity: int) -> None:
        self._buffer = np.zeros(capacity, dtype=np.float32)
        self._capacity = capacity
        self._write_pos = 0
        self._written = 0

    @property
    def written(self) -> int:
        """Сколько всего сэмплов записано (монотонный счётчик)."""
        return self._written

    def write(self, samples: np.ndarray) -> None:
        count = len(samples)

        if count >= self._capacity:
            self._buffer[:] = samples[-self._capacity:]
            self._write_pos = 0
            self._written += count
            return

        space = self._capacity - self._write_pos
        take = min(count, space)
        self._buffer[self._write_pos:self._write_pos + take] = samples[:take]

        if count > take:
            self._buffer[:count - take] = samples[take:]

        # Позицию двигаем на ВЕСЬ блок (не только на первую часть): иначе
        # после записи «через край» буфер начинает читаться не по порядку.
        self._write_pos = (self._write_pos + count) % self._capacity
        self._written += count

    def read_last(self, count: int) -> np.ndarray:
        """Последние `count` сэмплов (короче — если записано меньше)."""
        available = min(count, self._written, self._capacity)
        if available <= 0:
            return np.zeros(0, dtype=np.float32)

        result = np.empty(available, dtype=np.float32)
        read_pos = (self._write_pos - available + self._capacity) % self._capacity
        first = min(available, self._capacity - read_pos)

        result[:first] = self._buffer[read_pos:read_pos + first]
        if first < available:
            result[first:] = self._buffer[:available - first]

        return result


class KwsWakeWordDetector:
    """Детектор ключевого слова на ONNX-модели (streaming keyword spotting).

    Интерфейс совпадает с прежним `WakeWordDetector`: `recorder`,
    `wait_for_wake_word(cancel_event) -> str`, `close()`. Разница в том, что
    STT не участвует: возвращается само найденное слово.
    """

    ENGINE_NAME = "onnx-kws"

    #: Во сколько раз опрос чаще шага инференса (40 мс → опрос каждые 20 мс),
    #: чтобы не терять окна при джиттере планировщика.
    POLL_DIVISOR = 2

    #: Длина окна для энергетической отсечки тишины (мс) и её уровень.
    GATE_WINDOW_MS = 300

    def __init__(
        self,
        config: VoiceConfig,
        model_path: Optional[Path] = None,
        session_factory: Optional[Callable[[Path], Any]] = None,
    ) -> None:
        self._config = config
        self._recorder = ContinuousAudioRecorder()

        path = Path(model_path) if model_path is not None else resolve_model_path(config)
        if path is None:
            raise FileNotFoundError("Модель wake word не найдена")

        self._model_path = path
        self._manifest = load_manifest(path)
        self._session_factory = session_factory or default_session_factory
        self._session: Any = None
        self._session_lock = threading.Lock()

        # Параметры из манифеста + переопределения из конфига
        # (0/пусто в конфиге = не переопределять).
        self._sample_rate = int(self._manifest.get("sample_rate", 16000))
        self._window_samples = int(self._manifest.get("window_samples", 16000))
        self._hop_samples = max(1, int(self._manifest.get("hop_samples", 640)))
        self._input_name = str(self._manifest.get("input_name", "audio"))
        self._output_name = str(self._manifest.get("output_name", "score"))

        self._threshold = float(
            getattr(config, "wake_threshold", 0.0) or self._manifest.get("threshold", 0.7)
        )
        self._min_consecutive = int(
            getattr(config, "wake_min_consecutive", 0)
            or self._manifest.get("min_consecutive", 2)
        )
        self._cooldown_s = (
            float(getattr(config, "wake_cooldown_ms", 0) or self._manifest.get("cooldown_ms", 1800))
            / 1000.0
        )

        self._gate_samples = int(self._sample_rate * self.GATE_WINDOW_MS / 1000)
        self._debug = os.environ.get("ZERE_WAKE_DEBUG", "") not in ("", "0", "false")

        self._ring = _RingBuffer(self._window_samples * 2)
        self._ring_lock = threading.Lock()
        self._scored_until = 0        # монотонный счётчик обработанных сэмплов
        self._recent: list[float] = []
        self._cooldown_until = 0.0
        self._listening = False

        #: Последняя посчитанная вероятность (для панели/отладки).
        self.last_score: float = 0.0

    # ── Публичные свойства ──────────────────────────────────

    @property
    def engine(self) -> str:
        return self.ENGINE_NAME

    @property
    def model_path(self) -> Path:
        return self._model_path

    @property
    def is_ready(self) -> bool:
        """Загружена ли ONNX-сессия (проверка после `warmup()`)."""
        return self._session is not None

    @property
    def recorder(self) -> ContinuousAudioRecorder:
        """Рекордер для записи команды после срабатывания (как у STT-детектора)."""
        return self._recorder

    # ── Сессия ──────────────────────────────────────────────

    def warmup(self) -> None:
        """Создаёт сессию и прогоняет нулевое окно (первый инференс — самый
        дорогой: инициализация графа ~50–200 мс). Сбой не критичен."""
        try:
            session = self._ensure_session()
            self._run_model(session, np.zeros(self._window_samples, dtype=np.float32))
        except Exception as ex:  # noqa: BLE001 — прогрев не должен мешать работе
            print(f"⚠️ Прогрев wake-модели не удался: {ex}")

    def _ensure_session(self) -> Any:
        with self._session_lock:
            if self._session is None:
                self._session = self._session_factory(self._model_path)
            return self._session

    def _run_model(self, session: Any, window: np.ndarray) -> float:
        """Один инференс: окно float32 → вероятность слова."""
        audio = np.ascontiguousarray(window, dtype=np.float32).reshape(1, -1)
        outputs = session.run([self._output_name], {self._input_name: audio})
        value = float(np.asarray(outputs[0]).reshape(-1)[0])
        return float(min(max(value, 0.0), 1.0))

    # ── Аудиозахват ─────────────────────────────────────────

    def _on_audio(self, samples: np.ndarray) -> None:
        """Callback из потока sounddevice: только копия в буфер (без инференса)."""
        if not self._listening:
            return

        with self._ring_lock:
            self._ring.write(samples)

    def _score_window(self, session: Any) -> float:
        """Считает вероятность для последнего окна (с отсечкой тишины)."""
        with self._ring_lock:
            window = self._ring.read_last(self._window_samples)

        if window.size < self._window_samples:
            # Ещё не набрали окно (старт записи): дополняем нулями слева,
            # чтобы модель всегда получала ровно window_samples сэмплов.
            window = np.concatenate(
                (np.zeros(self._window_samples - window.size, dtype=np.float32), window)
            )

        if bool(getattr(self._config, "wake_energy_gate", True)):
            tail = window[-self._gate_samples:]
            # RMS тишины ~0.0005, речи ~0.02–0.1: порог 0.0015 безопасен и
            # экономит инференс, пока в комнате тихо.
            rms = float(np.sqrt(np.mean(np.square(tail)))) if tail.size else 0.0
            if rms < float(getattr(self._config, "wake_gate_rms", 0.0015)):
                return 0.0

        return self._run_model(session, window)

    # ── Ожидание слова ──────────────────────────────────────

    @staticmethod
    def _wait(seconds: float, cancel_event: Optional[threading.Event]) -> bool:
        """Ждём до отмены. True — отмена сработала (аналог Task.Delay(ct))."""
        if cancel_event is None:
            time.sleep(seconds)
            return False

        return cancel_event.wait(seconds)

    def wait_for_wake_word(self, cancel_event: Optional[threading.Event] = None) -> str:
        """Ждёт произнесения ключевого слова. Возвращает слово или "" (отмена).

        Поток записи не перезапускается при срабатывании: кольцевой буфер
        нужен дальше для записи команды (`VoiceManager.listen_command`).
        """
        session = self._ensure_session()
        poll_s = max(0.01, self._hop_samples / self._sample_rate / self.POLL_DIVISOR)

        self._recorder.start_continuous_recording(buffer_seconds=10)

        # Свежий буфер на каждый цикл ожидания: в старом остался хвост
        # предыдущей команды (и он бы сразу дал ложное срабатывание).
        with self._ring_lock:
            self._ring = _RingBuffer(self._window_samples * 2)

        self._scored_until = 0
        self._recent = []
        self._listening = True
        self._recorder.add_listener(self._on_audio)

        word = str(getattr(self._config, "wake_word", "") or "зере")
        completed = False

        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    break

                if self._wait(poll_s, cancel_event):
                    break

                with self._ring_lock:
                    written = self._ring.written

                # Реальное время: если отстали, считаем только последнее окно,
                # а не догоняем очередь устаревших (иначе копится задержка).
                if written - self._scored_until < self._hop_samples:
                    continue

                self._scored_until = written
                score = self._score_window(session)
                self.last_score = score

                if self._debug and score >= 0.3:
                    print(f"🎚️ KWS: {score:.3f}")

                now = time.monotonic()

                if now < self._cooldown_until:
                    continue

                self._recent.append(score)
                if len(self._recent) > self._min_consecutive:
                    self._recent.pop(0)

                if (
                    len(self._recent) >= self._min_consecutive
                    and all(value >= self._threshold for value in self._recent)
                ):
                    print(f'🔔 Обнаружено (KWS): "{word}" (score={score:.2f})')
                    completed = True
                    self._cooldown_until = now + self._cooldown_s
                    self._recent = []
                    return word
        except Exception as ex:  # noqa: BLE001 — как в прежнем детекторе
            print(f"⚠️ Ошибка KWS-детектора: {ex}")
        finally:
            self._listening = False
            self._recorder.remove_listener(self._on_audio)

            # При срабатывании запись продолжается: она нужна для команды.
            if not completed:
                self._recorder.stop_continuous_recording()

        return ""

    # ── Освобождение ────────────────────────────────────────

    def close(self) -> None:
        """Снимает слушателя и освобождает запись (модель трогать не нужно)."""
        self._listening = False

        try:
            self._recorder.remove_listener(self._on_audio)
        except Exception:  # noqa: BLE001
            pass

        self._recorder.close()

    def __enter__(self) -> "KwsWakeWordDetector":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
