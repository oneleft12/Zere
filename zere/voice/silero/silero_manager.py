"""Silero TTS v5 (русский): менеджер нейросетевого синтеза речи.

Почему Silero, а не ChatTTS: ChatTTS официально знает только китайский и
английский, на кириллице он фонетически ломается («found invalid characters»),
поэтому русская речь звучит плохо. Silero `v5_5_ru` — русская модель с
автоматическими ударениями и омографами, в 10–20 раз быстрее ChatTTS на CPU
(замер: 0.3–1.7 с синтеза на фразу 4.7 с).

Модуль СОЗНАТЕЛЬНО не импортирует тяжёлые зависимости на уровне модуля:
`torch`, `soundfile` и `numpy` подтягиваются внутри методов. Благодаря этому
импорт ничего не грузит (старт ZERE и тесты не платят за torch), а модель
попадает в память ТОЛЬКО при первом синтезе — отсутствие torch или модели не
роняет приложение, а даёт понятную ошибку `SileroUnavailable`.

Модель: `v5_5_ru` (~145 МБ) с `https://models.silero.ai`, качается при первом
синтезе в `ZERE.Voice/Silero/`. Веса — CC-NC-BY (как у ChatTTS): для личного
использования ок, для коммерческого релиза это блокер (docs/TTS_SILERO.md).

Голоса у Silero именованные (`baya`, `xenia`, `kseniya`, `aidar`, `eugene`) —
в отличие от ChatTTS, где «профиль голоса» это лишь зерно эмбеддинга.
"""

from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path
from typing import Any

from zere import paths
from zere.voice.speech_text import split_sentences, strip_emotions

# 24 кГц: столько же, сколько отдаёт ChatTTS, поэтому DSP/ресемплинг под
# устройство и сайдкар C#-редакции не меняются. v5 умеет 8/24/48 кГц.
SAMPLE_RATE = 24000

# Голоса v5_5_ru (docs: models.yml). baya — женский, «нейтральный» дефолт.
DEFAULT_VOICE = "baya"

BUILTIN_VOICES: tuple[str, ...] = ("baya", "xenia", "kseniya", "aidar", "eugene")

MODEL_ID = "v5_5_ru"
MODEL_URL = "https://models.silero.ai/models/tts/ru/v5_5_ru.pt"
MODEL_FILENAME = "v5_5_ru.pt"


class SileroUnavailable(RuntimeError):
    """Silero TTS (или его зависимости) недоступен в текущем окружении."""


class SileroManager:
    """Обёртка над Silero TTS с ЛЕНИВОЙ загрузкой модели.

    Эталон (docs/TTS_SILERO.md):

        torch.hub.download_url_to_file(MODEL_URL, 'v5_5_ru.pt')
        model = torch.package.PackageImporter('v5_5_ru.pt').load_pickle(
            "tts_models", "model")
        audio = model.apply_tts(text=..., speaker='baya', sample_rate=24000)

    Модель грузится при первом `synthesize()`; повторные вызовы переиспользуют
    загруженный экземпляр. Потокобезопасно: один экземпляр на процесс.
    """

    def __init__(self, voice: str = DEFAULT_VOICE, model_path: str | Path | None = None) -> None:
        self._model: Any = None
        self._lock = threading.Lock()
        self._silence_s = 0.2
        self._model_path = Path(model_path) if model_path else None

        self.voice = self._sanitize_voice(voice)

    # ─── Состояние ──────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        """Загружена ли модель в память (не «доступна ли библиотека»)."""
        return self._model is not None

    @property
    def current_voice(self) -> str:
        return self.voice

    def set_voice(self, voice_name: str) -> None:
        """Меняет голос (перезагрузка модели НЕ нужна)."""
        if voice_name:
            self.voice = self._sanitize_voice(voice_name)

    def set_inference_params(
        self,
        length_scale: float = 1.0,
        sentence_silence: float = 0.2,
    ) -> None:
        """Пауза после предложения; темп у Silero не настраивается.

        `length_scale` принимается ради общего контракта с ChatTTS/Piper, но
        игнорируется: у Silero v5 нет параметра скорости (это честное
        ограничение движка, оно видно в панели как «скорость фиксирована»).
        """
        try:
            silence = float(sentence_silence)
        except (TypeError, ValueError):
            silence = 0.2

        self._silence_s = min(max(silence, 0.0), 2.0)

    def close(self) -> None:
        """Освобождает модель (память возвращается ОС)."""
        with self._lock:
            self._model = None

    # ─── Доступность ────────────────────────────────────────

    @staticmethod
    def availability() -> tuple[bool, str]:
        """Дешёвая проверка окружения БЕЗ импорта torch и загрузки модели.

        Возвращает (доступен, объяснение). Модель (~145 МБ) качается при первом
        синтезе — это не ошибка окружения, поэтому проверяется только torch.
        """
        missing = [
            name
            for name in ("torch", "soundfile")
            if not SileroManager._has_module(name)
        ]

        if missing:
            return False, (
                "нет модулей: "
                + ", ".join(missing)
                + " (нужно: pip install torch soundfile — torch уже приходит "
                "с ChatTTS; C#-редакция поднимает движок через uv)"
            )

        return True, (
            f"Silero TTS {MODEL_ID} доступен (русский голос; модель ~145 МБ "
            "качается при первом синтезе)"
        )

    @staticmethod
    def _has_module(name: str) -> bool:
        """Есть ли модуль в окружении — БЕЗ его импорта (модель не грузится)."""
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    # ─── Модель ─────────────────────────────────────────────

    def model_path(self) -> Path:
        """Путь к файлу модели (по умолчанию — `ZERE.Voice/Silero`)."""
        if self._model_path is not None:
            return self._model_path

        return paths.silero_dir() / MODEL_FILENAME

    def ensure_model_file(self) -> Path:
        """Скачивает модель, если её ещё нет (один раз, ~145 МБ)."""
        target = self.model_path()

        if target.is_file() and target.stat().st_size > 0:
            return target

        try:
            import torch  # noqa: PLC0415
        except ImportError as ex:
            raise SileroUnavailable(
                "не установлен torch: pip install torch soundfile"
            ) from ex

        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            torch.hub.download_url_to_file(MODEL_URL, str(target))
        except Exception as ex:  # noqa: BLE001 — сеть/диск: объясняем словами
            raise SileroUnavailable(
                f"не удалось скачать модель Silero ({MODEL_URL}): {ex} "
                "(проверьте сеть/прокси, файл можно скачать вручную в "
                f"{target})"
            ) from ex

        if not target.is_file() or target.stat().st_size == 0:
            raise SileroUnavailable(
                f"модель Silero не появилась по пути {target} — проверьте права на запись"
            )

        return target

    def load_model(self) -> Any:
        """Загружает модель Silero при первом обращении (ленивая загрузка)."""
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is not None:
                return self._model

            try:
                import torch  # noqa: PLC0415
                import torch.package  # noqa: F401,PLC0415 — нужен PackageImporter
            except ImportError as ex:
                raise SileroUnavailable(
                    "не установлен torch: pip install torch soundfile"
                ) from ex

            model_file = self.ensure_model_file()

            try:
                model = torch.package.PackageImporter(str(model_file)).load_pickle(
                    "tts_models", "model"
                )
            except Exception as ex:  # noqa: BLE001 — битый/недокачанный файл
                raise SileroUnavailable(
                    f"не удалось загрузить модель Silero ({model_file.name}): {ex}. "
                    "Удалите файл — он скачается заново."
                ) from ex

            # CPU-потоки: у Silero это основной рычаг скорости; больше 8 обычно
            # не помогает, а на слабых ПК мешает остальному ZERE.
            try:
                torch.set_num_threads(max(1, min(8, os.cpu_count() or 4)))
            except Exception:  # noqa: BLE001 — настройка не критична
                pass

            model.to(torch.device("cpu"))
            self._model = model
            return model

    # ─── Синтез ─────────────────────────────────────────────

    def waveform(self, text: str) -> Any:
        """Синтезирует текст и возвращает float32-сигнал (моно, 24 кГц)."""
        prepared = (text or "").strip()

        if not prepared:
            raise ValueError("пустой текст для синтеза")

        import numpy as np  # noqa: PLC0415

        model = self.load_model()

        try:
            audio = model.apply_tts(
                text=prepared,
                speaker=self.voice,
                sample_rate=SAMPLE_RATE,
            )
        except Exception as ex:  # noqa: BLE001 — ошибка инференса: понятный текст
            raise SileroUnavailable(
                f"синтез Silero не удался (голос «{self.voice}»): {ex}"
            ) from ex

        # apply_tts отдаёт torch.Tensor; на всякий случай принимаем и numpy/список.
        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()

        samples = np.asarray(audio, dtype="float32").reshape(-1)

        return self._append_silence(samples)

    def synthesize(self, text: str, output_path: str = "output.wav") -> str:
        """Синтезирует текст в WAV-файл и возвращает путь."""
        samples = self.waveform(text)

        import soundfile as sf  # noqa: PLC0415

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(target), samples, SAMPLE_RATE)
        return str(target)

    def synthesize_sentences(self, text: str, output_path: str) -> str:
        """Попредложенный синтез в ОДИН WAV (пауза между фразами — тишина)."""
        sentences = split_sentences(text)

        # Пустой текст отсекаем ДО импорта тяжёлых зависимостей: в окружении
        # без soundfile ошибка должна говорить о тексте, а не о модуле.
        if not sentences:
            raise ValueError("пустой текст для синтеза")

        import numpy as np  # noqa: PLC0415
        import soundfile as sf  # noqa: PLC0415

        chunks = [self.waveform(sentence) for sentence in sentences]
        samples = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(target), samples, SAMPLE_RATE)
        return str(target)

    def available_voices(self) -> list[str]:
        """Именованные голоса v5_5_ru."""
        return list(BUILTIN_VOICES)

    @staticmethod
    def strip_emotions(text: str) -> str:
        """Порт PiperService.strip_emotions (оставлен для совместимости)."""
        return strip_emotions(text)

    # ─── Внутреннее ─────────────────────────────────────────

    @staticmethod
    def _sanitize_voice(voice: str) -> str:
        """Неизвестное имя голоса → дефолт.

        Так конфиг с профилем ChatTTS (`zere-standard`) не роняет Silero: у
        движков разные пространства голосов, а ключ voice в конфиге общий.
        """
        return voice if voice in BUILTIN_VOICES else DEFAULT_VOICE

    def _append_silence(self, samples: Any) -> Any:
        """Дописывает тишину после предложения (Piper --sentence_silence)."""
        if self._silence_s <= 0:
            return samples

        import numpy as np  # noqa: PLC0415

        count = int(self._silence_s * SAMPLE_RATE)

        if count <= 0:
            return samples

        return np.concatenate([samples, np.zeros(count, dtype="float32")])


__all__ = [
    "BUILTIN_VOICES",
    "DEFAULT_VOICE",
    "MODEL_FILENAME",
    "MODEL_ID",
    "MODEL_URL",
    "SAMPLE_RATE",
    "SileroManager",
    "SileroUnavailable",
    "split_sentences",
    "strip_emotions",
]
