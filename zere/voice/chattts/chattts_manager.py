"""ChatTTS: менеджер нейросетевого синтеза речи (2Noise/ChatTTS).

Модуль СОЗНАТЕЛЬНО не импортирует тяжёлые зависимости на уровне модуля:
`ChatTTS`, `torch`, `soundfile` и `numpy` подтягиваются внутри методов.
Благодаря этому:

* импорт модуля ничего не грузит в память (важно для старта ZERE и тестов);
* модель в память попадает ТОЛЬКО при первом обращении (ленивая загрузка),
  отсутствие ChatTTS в окружении не роняет приложение, а даёт понятную
  ошибку `ChatTtsUnavailable`.

Голоса. У ChatTTS нет именованных голосов: он умеет «случайный голос»
(`sample_random_speaker`). Поэтому «профиль голоса» ZERE — это детерминированное
зерно: имя профиля → `crc32` → `torch.manual_seed` → эмбеддинг говорящего.
Один и тот же профиль всегда звучит одинаково, разные профили — по-разному
(паритет со сменой голоса под стиль личности из Piper-редакции).
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import threading
import zlib
from pathlib import Path
from typing import Any

# ChatTTS синтезирует на 24 кГц (у Piper было 22.05 кГц — ресемплинг под
# устройство делает AudioProcessor/ResolveOutputSampleRate, вызывающий код
# не меняется).
SAMPLE_RATE = 24000

DEFAULT_VOICE = "zere-standard"

# Встроенные профили голоса. Имена читаемые, но это не «модели», а зёрна:
# см. докстроку модуля. Значения совпадают с voice_config.py и VoiceConfig.cs.
BUILTIN_VOICES: tuple[str, ...] = (
    "zere-standard",
    "zere-warm",
    "zere-strict",
    "zere-ironic",
    "zere-business",
    "zere-casual",
)

# Эталонные параметры инференса (реалистичный, но стабильный голос):
# temperature 0.3 — меньше вариативности, top_P 0.7 / top_K 20 — отсечение
# «мусорных» токенов, из-за которых голос уходил в бормотание.
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TOP_P = 0.7
DEFAULT_TOP_K = 20

# [speed_N] — единственный регулятор темпа у ChatTTS (1 — медленно, 9 — быстро,
# 5 — «нейтрально»). Паритет с Piper --length_scale: >1.0 = медленнее.
_SPEED_NORMAL = 5
_SPEED_MIN = 1
_SPEED_MAX = 9

_RE_SENTENCE = re.compile(r'[^.!?…]+[.!?…]+[»""\']*\s*|[^.!?…]+$')


class ChatTtsUnavailable(RuntimeError):
    """ChatTTS (или его зависимости) недоступен в текущем окружении."""


def strip_emotions(text: str) -> str:
    """Убирает из текста всё, что TTS не должен произносить.

    Порт PiperService.strip_emotions / SpeechText.Clean: эмодзи, текстовые
    смайлики, «ролевые» пометки (*улыбается*, (томно)), markdown-разметка.
    """
    if not text:
        return text

    # Ролевые пометки в скобках: (улыбается), (смеётся), (задумчиво)
    text = re.sub(r"\([^)]*[а-яёА-ЯЁ]{3,}[^)]*\)", " ", text)

    # Ролевые пометки в *звёздочках*: *улыбается*, *качает головой*
    text = re.sub(r"\*[^*]*[а-яёА-ЯЁ]{3,}[^*]*\*", " ", text)

    # Markdown-эмодзи :smile:, :heart:
    text = re.sub(r":[a-z_0-9]+:", " ", text)

    # Текстовые смайлики: :) ;) :D :( :P <3 =) и т.п.
    text = re.sub(r"[:;=8][\-^']?[)(DPp/\\|]", " ", text)
    text = re.sub(r"[)(DPp/\\|][\-^']?[:;=8]", " ", text)
    text = re.sub(r"<3", " ", text)

    # Юникод-эмодзи и символы (астральные + BMP-диапазоны символов)
    text = re.sub(
        r"[\U00010000-\U0010FFFF]|[️‍]"
        r"|[☀-➿]|[←-⇿]|[⬀-⯿]|[✀-➿]",
        "",
        text,
    )

    # Убираем markdown-разметку: **bold**, *italic*, `code`, ## заголовки
    text = re.sub(r"[*_`#]{1,3}([^*_`#]+)[*_`#]{1,3}", r"\1", text)
    text = re.sub(r"[*_`#~>|-]{2,}", " ", text)

    # Схлопываем пробелы
    return re.sub(r"\s{2,}", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    """Разбивает текст на предложения (порт SpeechText.SplitSentences).

    Каждое предложение синтезируется отдельно: ChatTTS на коротком тексте
    стабильнее, а вызывающий код получает первый звук раньше.
    """
    parts = [m.group(0).strip() for m in _RE_SENTENCE.finditer(text or "")]
    parts = [p for p in parts if p]

    if parts:
        return parts

    stripped = (text or "").strip()
    return [stripped] if stripped else []


class ChatTTSManager:
    """Обёртка над ChatTTS с ЛЕНИВОЙ загрузкой модели.

    Эталон инициализации (docs/TTS_CHATTTS.md):

        chat = ChatTTS.Chat()
        chat.load(compile=False)   # compile=False — стабильность первого запуска

    Модель грузится при первом `synthesize()`; повторные вызовы переиспользуют
    загруженный экземпляр. Потокобезопасно: один экземпляр на процесс.
    """

    def __init__(self, voice: str = DEFAULT_VOICE) -> None:
        self._chat: Any = None
        self._lock = threading.Lock()
        self._speaker_cache: dict[str, Any] = {}
        self._voice_files: dict[str, Path] = {}

        self.voice = voice or DEFAULT_VOICE

        self._temperature = DEFAULT_TEMPERATURE
        self._top_p = DEFAULT_TOP_P
        self._top_k = DEFAULT_TOP_K
        self._speed = _SPEED_NORMAL
        self._silence_s = 0.2

    # ─── Состояние ──────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        """Загружена ли модель в память (не «доступна ли библиотека»)."""
        return self._chat is not None

    @property
    def current_voice(self) -> str:
        return self.voice

    def set_voice(self, voice_name: str) -> None:
        """Меняет профиль голоса (перезагрузка модели НЕ нужна)."""
        if voice_name:
            self.voice = voice_name

    def set_inference_params(
        self,
        length_scale: float = 1.0,
        sentence_silence: float = 0.2,
    ) -> None:
        """Темп и пауза после предложения.

        length_scale повторяет семантику Piper `--length_scale`: 1.0 — норма,
        больше — медленнее. У ChatTTS темп задаётся токеном `[speed_N]`,
        поэтому шкала дискретная (1…9) — это честное ограничение движка.
        """
        try:
            scale = float(length_scale)
        except (TypeError, ValueError):
            scale = 1.0

        scale = min(max(scale, 0.5), 3.0)

        # 1.0 → 5 (нейтрально); 1.15 → ~4 (медленнее); 0.87 → ~6 (быстрее)
        speed = round(_SPEED_NORMAL / scale) if scale > 0 else _SPEED_NORMAL
        self._speed = int(min(max(speed, _SPEED_MIN), _SPEED_MAX))

        try:
            silence = float(sentence_silence)
        except (TypeError, ValueError):
            silence = 0.2

        self._silence_s = min(max(silence, 0.0), 2.0)

    # ─── Доступность ────────────────────────────────────────

    @staticmethod
    def availability() -> tuple[bool, str]:
        """Дешёвая проверка окружения БЕЗ импорта ChatTTS и загрузки весов.

        Возвращает (доступен, объяснение) — объяснение печатается в лог,
        чтобы отсутствие движка не выглядело «озвучка молча не работает».
        """
        missing = [
            name
            for name in ("ChatTTS", "torch", "soundfile")
            if not ChatTTSManager._has_module(name)
        ]

        if missing:
            return False, (
                "нет модулей: "
                + ", ".join(missing)
                + " (нужно: pip install ChatTTS soundfile — это ~2–3 ГБ с torch; "
                "C#-редакция поднимает движок через uv с --python 3.12)"
            )

        return True, "ChatTTS доступен (ленивая загрузка при первом синтезе)"

    @staticmethod
    def _has_module(name: str) -> bool:
        """Есть ли модуль в окружении — БЕЗ его импорта (модель не грузится)."""
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):  # noqa: PERF203
            return False

    # ─── Модель ─────────────────────────────────────────────

    def load_model(self) -> Any:
        """Загружает модель ChatTTS при первом обращении (ленивая загрузка)."""
        if self._chat is not None:
            return self._chat

        with self._lock:
            if self._chat is not None:
                return self._chat

            try:
                import ChatTTS  # noqa: PLC0415 — тяжёлый импорт только здесь
            except ImportError as ex:  # noqa: BLE001
                raise ChatTtsUnavailable(
                    f"ChatTTS не импортируется: {ex}. "
                    "Установите: pip install ChatTTS soundfile (~2–3 ГБ с torch)"
                ) from ex

            chat = ChatTTS.Chat()

            # compile=False для стабильности при первом запуске
            # (torch.compile может падать на неподдерживаемом железе).
            chat.load(compile=False)

            self._chat = chat
            return chat

    def close(self) -> None:
        """Освобождает модель (память возвращается ОС)."""
        with self._lock:
            self._chat = None
            self._speaker_cache.clear()

    # ─── Синтез ─────────────────────────────────────────────

    def waveform(self, text: str) -> Any:
        """Синтезирует текст и возвращает float32-сигнал (моно, 24 кГц).

        Один проход инференса по эталонным параметрам плюс пауза после
        предложения (аналог Piper `--sentence_silence`).
        """
        prepared = (text or "").strip()

        if not prepared:
            raise ValueError("пустой текст для синтеза")

        import numpy as np  # noqa: PLC0415

        chat = self.load_model()
        params = self._infer_params(chat)

        wavs = chat.infer([prepared], params_infer_code=params)

        if not wavs:
            raise RuntimeError("ChatTTS вернул пустой результат")

        wav = wavs[0]
        if hasattr(wav, "squeeze"):
            wav = wav.squeeze()

        samples = np.asarray(wav, dtype="float32").reshape(-1)

        return self._append_silence(samples)

    def synthesize(self, text: str, output_path: str = "output.wav") -> str:
        """Синтезирует текст в WAV-файл и возвращает путь (эталонный контракт).

            sf.write(output_path, wavs[0].squeeze(), 24000)
        """
        import soundfile as sf  # noqa: PLC0415

        samples = self.waveform(text)

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(target), samples, SAMPLE_RATE)
        return str(target)

    def synthesize_sentences(self, text: str, output_path: str) -> str:
        """Попредложенный синтез в ОДИН WAV (порт попредложенного Piper).

        ChatTTS заметно ровнее звучит на коротких фрагментах, поэтому текст
        режется на предложения; пауза между ними — `sentence_silence`.
        """
        import numpy as np  # noqa: PLC0415
        import soundfile as sf  # noqa: PLC0415

        sentences = split_sentences(text)

        if not sentences:
            raise ValueError("пустой текст для синтеза")

        chunks = []
        for sentence in sentences:
            chunks.append(self.waveform(sentence))

        samples = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(target), samples, SAMPLE_RATE)
        return str(target)

    def available_voices(self) -> list[str]:
        """Профили голоса: встроенные + пользовательские *.pt из папки голосов."""
        voices = list(BUILTIN_VOICES)

        for path in sorted(self.voice_files().values()):
            stem = path.stem
            if stem not in voices:
                voices.append(stem)

        return voices

    def voice_files(self) -> dict[str, Path]:
        """Пользовательские эмбеддинги голоса (*.pt) из voice-папки ChatTTS."""
        if self._voice_files:
            return dict(self._voice_files)

        root = Path(__file__).resolve().parents[3] / "ZERE.Voice" / "ChatTts" / "voices"

        if not root.is_dir():
            return {}

        for path in sorted(root.glob("*.pt")):
            self._voice_files[path.stem] = path

        return dict(self._voice_files)

    # ─── Внутреннее ─────────────────────────────────────────

    def _infer_params(self, chat: Any) -> Any:
        """InferCodeParams строго по эталону (temperature/top_P/top_K) + профиль.

        Свои параметры передаём через фильтр по сигнатуре: в разных версиях
        ChatTTS набор полей отличается, и «лишний» kwargs уронил бы синтез.
        """
        kwargs: dict[str, Any] = {
            "temperature": self._temperature,
            "top_P": self._top_p,
            "top_K": self._top_k,
            "prompt": f"[speed_{self._speed}]",
        }

        voice_file = self.voice_files().get(self.voice)

        if voice_file is not None:
            # Пользовательский эмбеддинг голоса (spk_smp — путь к .pt).
            kwargs["spk_smp"] = str(voice_file)
        else:
            kwargs["spk_emb"] = self._speaker(chat)

        return self._make_params(chat.InferCodeParams, kwargs)

    def _speaker(self, chat: Any) -> Any:
        """Детерминированный эмбеддинг говорящего для профиля голоса."""
        if self.voice not in self._speaker_cache:
            try:
                import torch  # noqa: PLC0415

                torch.manual_seed(self._voice_seed(self.voice))
            except ImportError:  # noqa: BLE001 — seed недоступен, голос будет случайным
                pass

            self._speaker_cache[self.voice] = chat.sample_random_speaker()

        return self._speaker_cache[self.voice]

    @staticmethod
    def _voice_seed(voice: str) -> int:
        """Имя профиля → стабильное зерно (одинаковый голос между запусками)."""
        return zlib.crc32(voice.encode("utf-8")) & 0x7FFFFFFF

    @staticmethod
    def _make_params(factory: Any, kwargs: dict[str, Any]) -> Any:
        """Создаёт params-объект, отбрасывая незнакомые версии аргументы."""
        try:
            names = set(inspect.signature(factory).parameters)
        except (TypeError, ValueError):  # noqa: PERF203 — сигнатура недоступна
            names = set()

        if names:
            filtered = {k: v for k, v in kwargs.items() if k in names}
        else:
            filtered = dict(kwargs)

        try:
            return factory(**filtered)
        except TypeError:
            # Совсем другая сигнатура: минимальный набор из эталона.
            return factory(
                temperature=kwargs.get("temperature", DEFAULT_TEMPERATURE),
                top_P=kwargs.get("top_P", DEFAULT_TOP_P),
                top_K=kwargs.get("top_K", DEFAULT_TOP_K),
            )

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
    "SAMPLE_RATE",
    "ChatTTSManager",
    "ChatTtsUnavailable",
    "split_sentences",
    "strip_emotions",
]
