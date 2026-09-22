"""Распознавание речи STT (порт JARVIS.Voice/Whisper/WhisperService.cs).

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
from pathlib import Path

from faster_whisper import WhisperModel

from jarvis import paths
from jarvis.voice.audio.audio_preprocessor import AudioPreprocessor

# Размеры моделей, которые умеет загружать faster-whisper по имени
_MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3", "large")


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


class WhisperService:
    """Сервис STT: локальная модель faster-whisper (порт WhisperService.cs)."""

    def __init__(self) -> None:
        # В C# путь строился от AppContext.BaseDirectory до корня решения,
        # затем JARVIS.Voice/Models. В Python — jarvis.paths.whisper_models_dir().
        models_dir = paths.whisper_models_dir()
        self._medium_model_path = models_dir / "ggml-medium.bin"
        self._base_model_path = models_dir / "ggml-base.bin"

        # Локальный путь к CT2-модели из конфига (иначе — размер по спецификации: "base")
        self._local_model_path = _load_local_model_path()
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

    def _get_model(self) -> WhisperModel:
        """Ленивая загрузка модели (аналог Lazy<WhisperFactory>.Value)."""
        if self._model is None:
            # device="cpu", compute_type="int8" — как в спецификации
            self._model = WhisperModel(
                self._model_source,
                device="cpu",
                compute_type="int8",
            )
        return self._model

    def transcribe(self, wav_file: str) -> str:
        """Распознаёт WAV-файл в строку (порт TranscribeAsync, язык — ru)."""
        if not self.is_installed():
            return "Модель Whisper не найдена."

        # Предобработка аудио для лучшего распознавания
        processed_file = AudioPreprocessor.process_for_whisper(wav_file)

        try:
            model = self._get_model()

            # WithLanguage("ru") в C#
            segments, _info = model.transcribe(processed_file, language="ru")

            result_parts: list[str] = []
            for segment in segments:
                text = segment.text.strip()

                # Фильтруем пустые сегменты и артефакты
                if text and len(text) > 1 and not all(c in (" ", ".", ",") for c in text):
                    result_parts.append(text)
                    result_parts.append(" ")

            return "".join(result_parts).strip()
        finally:
            # Удаляем обработанный файл
            if processed_file != wav_file:
                try:
                    os.remove(processed_file)
                except OSError:
                    pass
