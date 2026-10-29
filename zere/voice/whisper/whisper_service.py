"""Распознавание речи STT (порт ZERE.Voice/Whisper/WhisperService.cs).

Замена библиотеки: Whisper.net (ggml) → faster-whisper (CTranslate2).

ВАЖНО: ggml-base.bin / ggml-medium.bin в Models/ — это формат whisper.cpp,
faster-whisper НЕ грузит его напрямую. По умолчанию используется модель
"base" (faster-whisper сам скачает/возьмёт из кэша CT2-эквивалент);
путь к локальной CT2-модели можно указать в config/config.json
(ключ "whisperModelPath").
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from zere import paths
from zere.core.logging.log_service import log_error
from zere.voice.audio.audio_preprocessor import AudioPreprocessor

if TYPE_CHECKING:  # только для аннотаций: пакет необязательный
    from faster_whisper import WhisperModel

# Размеры моделей, которые умеет загружать faster-whisper по имени
_MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3", "large")

# Таймаут распознавания одной команды, сек (ROADMAP 1.1 «таймауты на все
# внешние вызовы»). Этап 1 (анализ F6): 120 с для голосовой команды —
# слишком много, пользователь молча ждёт; 30 с достаточно для medium
# даже на слабом CPU. Для wake-сегментов таймаут задаётся короче (15 с).
_TRANSCRIBE_TIMEOUT_S = 30


def _load_local_model_path() -> Path | None:
    """Читает из config/config.json необязательный путь к локальной CT2-модели."""
    try:
        config_file = paths.config_path()
        if not config_file.exists():
            return None
        data = json.loads(config_file.read_text(encoding="utf-8"))
        value = data.get("whisperModelPath") or data.get("WhisperModelPath")
        if isinstance(value, str) and value:
            return Path(value)
    except Exception:  # noqa: BLE001 — конфиг не должен ронять голос
        return None
    return None


def _load_model_size_override() -> str | None:
    """Читает из config/config.json необязательный размер модели (tiny…medium)."""
    try:
        config_file = paths.config_path()
        if not config_file.exists():
            return None
        data = json.loads(config_file.read_text(encoding="utf-8"))
        value = data.get("whisperModelSize") or data.get("WhisperModelSize")
        if isinstance(value, str) and value in _MODEL_SIZES:
            return value
    except Exception:  # noqa: BLE001 — конфиг не должен ронять голос
        return None
    return None


class WhisperService:
    """Сервис STT: локальная модель faster-whisper (порт WhisperService.cs)."""

    def __init__(self) -> None:
        # В C# путь строился от AppContext.BaseDirectory до корня решения,
        # затем ZERE.Voice/Models. В Python — zere.paths.whisper_models_dir().
        models_dir = paths.whisper_models_dir()
        self._medium_model_path = models_dir / "ggml-medium.bin"
        self._base_model_path = models_dir / "ggml-base.bin"

        # Локальный путь к CT2-модели из конфига (иначе — размер по спецификации: "base")
        self._local_model_path = _load_local_model_path()

        # Выбор размера модели (ROADMAP 1.2 «multiple модели, auto-select»):
        # 1) явный размер из конфига whisperModelSize;
        # 2) иначе, как в C# (CurrentModel = medium если ggml-medium.bin есть,
        #    иначе base): тяжёлая скачанная модель → используем её CT2-эквивалент;
        # 3) иначе "base".
        override = _load_model_size_override()
        if override is not None:
            self._model_size = override
        elif self._medium_model_path.exists():
            self._model_size = "medium"
        else:
            self._model_size = "base"

        # Источник для WhisperModel(...): путь CT2-модели либо имя размера.
        # В C# здесь был Lazy<WhisperFactory> — модель грузится лениво при первом
        # распознавании (в конструкторе не грузим).
        if self._local_model_path is not None:
            self._model_source: str = str(self._local_model_path)
            self.current_model = str(self._local_model_path)
        else:
            self._model_source = self._model_size
            self.current_model = self._model_size

        # В C#: CurrentModel = "medium" если ggml-medium.bin есть, иначе "base";
        # выбор модели по ggml-файлам здесь не применяется — см. докстринг модуля.
        self._model: WhisperModel | None = None

    def is_installed(self) -> bool:
        """Модель доступна, если существует локальный CT2-путь из конфига
        либо размер модели ("base") может быть использован faster-whisper —
        он сам скачает/найдёт в кэше CT2-модель такого размера.

        (ggml-base.bin / ggml-medium.bin рядом — формат whisper.cpp,
        faster-whisper их напрямую не грузит, поэтому по ним доступность
        не проверяется; они учитываются только как признак скачанных моделей.)
        """
        if self._local_model_path is not None:
            # Путь задан — он должен существовать
            if not self._local_model_path.exists():
                return False
            return True

        # Размер "base" по спецификации — faster-whisper может его использовать,
        # либо модели уже скачаны (ggml-файлы в Models/ как в C#)
        return self._model_size in _MODEL_SIZES or self._base_model_path.exists() or self._medium_model_path.exists()

    def _get_model(self) -> "WhisperModel":
        """Ленивая загрузка модели (аналог Lazy<WhisperFactory>.Value)
        c auto-reconnect: при ошибке загрузки — одна повторная попытка
        с чистым состоянием (ROADMAP 1.1).
        """
        if self._model is not None:
            return self._model

        # Импорт внутри: faster-whisper тянет ctranslate2/onnxruntime и грузится
        # несколько секунд. При импорте на уровне модуля отсутствие пакета
        # ломало ВСЁ приложение (VoiceManager импортирует WhisperService), а не
        # только STT, — и тесты без faster-whisper не собирались вовсе.
        try:
            from faster_whisper import WhisperModel
        except ImportError as ex:
            raise RuntimeError(
                "faster-whisper не установлен: распознавание Whisper недоступно. "
                "Установите пакет из requirements.txt (pip install faster-whisper) "
                "или используйте sttEngine=gigaam."
            ) from ex

        last_error: Exception | None = None

        for attempt in range(2):
            try:
                # device="cpu", compute_type="int8" — как в спецификации
                self._model = WhisperModel(
                    self._model_source,
                    device="cpu",
                    compute_type="int8",
                )
                return self._model
            except Exception as ex:  # noqa: BLE001
                last_error = ex
                self._model = None
                log_error(
                    "WhisperService",
                    f"Ошибка загрузки модели (попытка {attempt + 1}/2): {ex}",
                )
                print(
                    f"[Whisper] Ошибка загрузки модели "
                    f"(попытка {attempt + 1}/2): {ex}"
                )
                if attempt == 0:
                    # Небольшая пауза перед reconnect
                    time.sleep(1.0)

        raise last_error if last_error is not None else RuntimeError("Неизвестная ошибка загрузки модели")

    def preload(self) -> bool:
        """Предзагрузка модели в память при старте (ROADMAP 1.3):
        первый вызов распознавания не ждёт загрузки модели.
        """
        if not self.is_installed():
            return False
        try:
            self._get_model()
            return True
        except Exception as ex:  # noqa: BLE001
            log_error("WhisperService", f"Предзагрузка модели: {ex}")
            print(f"[Whisper] Не удалось предзагрузить модель: {ex}")
            return False

    @staticmethod
    def _clean_artifacts(parts: list[str]) -> list[str]:
        """Фильтрация артефактов распознавания (ROADMAP 1.2):
        схлопывание пробелов/переносов, отбрасывание пустых и повторяющихся
        подряд сегментов.
        """
        cleaned: list[str] = []
        for text in parts:
            # Схлопываем пробелы и переносы строк внутри сегмента
            text = " ".join(text.split())
            # Пустые и «пунктуационные» сегменты
            if not text or len(text) < 2 or all(c in " .,!?-…" for c in text):
                continue
            # Повтор сразу предыдущего сегмента (артефакт галлюцинации)
            if cleaned and text.lower() == cleaned[-1].lower():
                continue
            cleaned.append(text)
        return cleaned

    def transcribe(
        self,
        wav_file: str,
        timeout_s: int | None = None,
        fast: bool = False,
    ) -> str:
        """Распознаёт WAV-файл в строку (порт TranscribeAsync, язык — ru).

        timeout_s — управляемый предел (иначе _TRANSCRIBE_TIMEOUT_S);
        fast — режим wake-слова: greedy (beam_size=1) без conditioning —
        короткий сегмент распознаётся заметно быстрее (этап 1, анализ S2/S4).

        При любой ошибке (нет модели, краш загрузки, таймаут) возвращает "",
        чтобы голосовой слой ушёл в fallback на текстовый ввод.
        """
        if not self.is_installed():
            print("[Whisper] Модель Whisper не найдена.")
            return ""

        if timeout_s is None:
            timeout_s = _TRANSCRIBE_TIMEOUT_S

        started = time.monotonic()

        # Предобработка аудио для лучшего распознавания
        processed_file = AudioPreprocessor.process_for_whisper(wav_file)

        # Результат/ошибка из рабочего потока (таймаут → отвечаем управляемо)
        result_parts: list[str] = []
        error_parts: list[BaseException] = []

        def worker() -> None:
            try:
                model = self._get_model()

                # WithLanguage("ru") в C#
                options: dict[str, object] = {"language": "ru"}
                if fast:
                    # Wake-сегменты короткие: greedy быстрее beam search,
                    # conditioning только мешает на одиночных фразах.
                    options["beam_size"] = 1
                    options["condition_on_previous_text"] = False

                segments, _info = model.transcribe(processed_file, **options)

                for segment in segments:
                    text = segment.text.strip()
                    if text:
                        result_parts.append(text)
            except BaseException as exc:  # noqa: BLE001
                error_parts.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout_s)

        try:
            if thread.is_alive():
                # Поток не остановить — он дойдёт до конца в фоне (daemon),
                # но пользователь получает управляемый ответ.
                log_error(
                    "WhisperService",
                    f"Таймаут распознавания ({timeout_s} с): {wav_file}",
                )
                print(f"[Whisper] Распознавание не уложилось в {timeout_s} с.")
                return ""

            if error_parts:
                ex = error_parts[0]
                log_error("WhisperService", f"Распознавание: {ex}")
                print(f"[Whisper] Ошибка распознавания: {ex}")
                return ""

            cleaned = self._clean_artifacts(result_parts)

            # Этап 0 (метрики): длительность STT по каждой команде.
            total_ms = int((time.monotonic() - started) * 1000)
            print(f"[Perf] STT={total_ms} мс (модель: {self.current_model})")

            return " ".join(cleaned)
        finally:
            # Удаляем обработанный файл
            if processed_file != wav_file:
                try:
                    os.remove(processed_file)
                except OSError:
                    pass
