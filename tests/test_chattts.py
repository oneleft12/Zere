"""Тесты ChatTTS — движка синтеза речи, заменившего Piper.

Проверяется то, что ломается при рефакторинге и что нельзя поймать «на слух»:

- ленивая загрузка: `initialize()` не грузит модель, веса поднимаются только
  при первом синтезе (и ровно один раз на процесс);
- контракт, идентичный прежнему PiperService, — на него опирается VoiceManager,
  который после замены движка не менялся;
- эталонные параметры инференса ChatTTS (temperature 0.3 / top_P 0.7 / top_K 20)
  и частота 24 кГц;
- профили голоса: детерминированное зерно по имени (crc32) + кэш эмбеддинга;
- попредложенный синтез: текст режется на предложения, между ними — тишина
  `sentenceSilence`;
- маппинг темпа речи в токен ChatTTS `[speed_N]`;
- контракт сайдкара `tools/zere_chattts_server.py`: подготовка текста и
  параметры запроса `/tts`.

ChatTTS, torch, numpy и soundfile в тестах НЕ нужны: тяжёлые зависимости
подменяются фейками через `sys.modules` (это ещё и проверяет, что ленивость
настоящая — импорт происходит внутри методов, а не на уровне модуля).

Запуск:
- `python3 tests/test_chattts.py` — без зависимостей;
- `pytest tests/ -q` — в CI (функции test_* без аргументов).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError

from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zere.voice.chattts.chattts_manager import (  # noqa: E402
    BUILTIN_VOICES,
    DEFAULT_VOICE,
    SAMPLE_RATE,
    ChatTTSManager,
    split_sentences,
    strip_emotions,
)
from zere.voice.chattts.chattts_service import ChatTtsService  # noqa: E402


# ── Фейковые зависимости ────────────────────────────────────────────


class FakeArray:
    """Минимальный аналог numpy-массива для проверки конвейера синтеза."""

    def __init__(self, data: Any, int16: bool = False) -> None:
        self.data = [float(v) for v in data]
        self.int16 = int16

    def reshape(self, *_args: Any) -> "FakeArray":
        return self

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, item: Any) -> "FakeArray":
        return FakeArray(self.data[item], self.int16)

    def __mul__(self, factor: float) -> "FakeArray":
        if self.int16:
            return self
        return FakeArray([v * factor for v in self.data])

    def astype(self, _dtype: str) -> "FakeArray":
        return FakeArray([int(v) for v in self.data], int16=True)

    def tobytes(self) -> bytes:
        return b"".join(
            max(-32768, min(32767, int(v))).to_bytes(2, "little", signed=True)
            for v in self.data
        )


class FakeNumpy:
    float32 = "float32"

    @staticmethod
    def asarray(value: Any, dtype: Any = None) -> FakeArray:  # noqa: ARG004
        return FakeArray([float(v) for v in value])

    @staticmethod
    def zeros(count: int, dtype: Any = None) -> FakeArray:  # noqa: ARG004
        return FakeArray([0.0] * count)

    @staticmethod
    def clip(value: FakeArray, low: float, high: float) -> FakeArray:
        return FakeArray([min(max(v, low), high) for v in value.data])

    @staticmethod
    def concatenate(parts: list[FakeArray]) -> FakeArray:
        joined: list[float] = []
        for part in parts:
            joined.extend(part.data if isinstance(part, FakeArray) else list(part))
        return FakeArray(joined)


class FakeWave:
    """Кадр, который ChatTTS возвращает из infer (у него есть .squeeze())."""

    SAMPLES = 240  # 10 мс @ 24 кГц

    def __init__(self, value: float = 0.25) -> None:
        self.value = value

    def squeeze(self) -> list[float]:
        return [self.value] * self.SAMPLES


class FakeInferCodeParams:
    """Заглушка Chat.InferCodeParams: запоминает переданные поля.

    Сигнатура повторяет настоящую (spk_emb/spk_smp/temperature/top_P/top_K/
    prompt) — ChatTTSManager фильтрует kwargs по сигнатуре, и тест обязан
    это учитывать.
    """

    def __init__(
        self,
        spk_emb: Any = None,
        spk_smp: Any = None,
        temperature: float = 0.3,
        top_P: float = 0.7,
        top_K: int = 20,
        prompt: Any = None,
    ) -> None:
        self.spk_emb = spk_emb
        self.spk_smp = spk_smp
        self.temperature = temperature
        self.top_P = top_P
        self.top_K = top_K
        self.prompt = prompt


class FakeChat:
    """Заглушка ChatTTS.Chat: считает загрузки и вызовы инференса."""

    InferCodeParams = FakeInferCodeParams

    instances: list["FakeChat"] = []

    def __init__(self) -> None:
        self.load_calls: list[bool] = []
        self.infer_calls: list[tuple[list[str], FakeInferCodeParams]] = []
        self.speaker_calls = 0
        FakeChat.instances.append(self)

    def load(self, compile: bool = True) -> None:  # noqa: A002 — имя из API ChatTTS
        self.load_calls.append(compile)

    def sample_random_speaker(self) -> str:
        self.speaker_calls += 1
        return "speaker-embedding"

    def infer(
        self,
        texts: list[str],
        params_infer_code: FakeInferCodeParams | None = None,
    ) -> list[FakeWave]:
        self.infer_calls.append((list(texts), params_infer_code))
        return [FakeWave()]


class FakeSoundFile:
    """Заглушка soundfile: запоминает пути, данные и частоту."""

    writes: list[tuple[str, int, int]] = []

    @staticmethod
    def write(path: str, data: FakeArray, rate: int) -> None:
        FakeSoundFile.writes.append((path, rate, len(data)))


class FakeChatTTSModule:
    """Заглушка пакета ChatTTS (chat.load(compile=False) — как в эталоне)."""

    Chat = FakeChat

    @staticmethod
    def reset() -> None:
        FakeChat.instances.clear()
        FakeSoundFile.writes.clear()


@contextmanager
def fake_dependencies() -> Iterator[None]:
    """Подменяет ChatTTS/numpy/soundfile на время теста и возвращает как было."""
    FakeChatTTSModule.reset()

    saved = {
        name: sys.modules.get(name)
        for name in ("ChatTTS", "numpy", "soundfile", "torch")
    }

    sys.modules["ChatTTS"] = FakeChatTTSModule  # type: ignore[assignment]
    sys.modules["numpy"] = FakeNumpy  # type: ignore[assignment]
    sys.modules["soundfile"] = FakeSoundFile  # type: ignore[assignment]
    # torch нужен только для seed: без него голос был бы случайным.
    sys.modules.pop("torch", None)

    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _manager(voice: str = DEFAULT_VOICE) -> ChatTTSManager:
    return ChatTTSManager(voice)


# ── Текст ───────────────────────────────────────────────────────────


def test_split_sentences_breaks_text() -> None:
    """Текст режется по границам предложений (попредложенный синтез)."""
    assert split_sentences("Привет. Как дела? Хорошо!") == [
        "Привет.",
        "Как дела?",
        "Хорошо!",
    ]


def test_split_sentences_keeps_trailing_fragment() -> None:
    """Последний фрагмент без точки не теряется."""
    assert split_sentences("Привет. Хвост без точки") == ["Привет.", "Хвост без точки"]


def test_split_sentences_empty_text() -> None:
    """Пустой текст — пустой список (синтез не запускается)."""
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_strip_emotions_removes_tts_noise() -> None:
    """Эмодзи, смайлики, ролевые пометки и markdown-эмодзи не читаются вслух."""
    cleaned = strip_emotions("Привет 😊 *улыбается* (томно) важно :smile: :)")

    assert "😊" not in cleaned
    assert "улыбается" not in cleaned
    assert "томно" not in cleaned
    assert ":smile:" not in cleaned
    assert ":)" not in cleaned
    assert "важно" in cleaned
    assert cleaned.startswith("Привет")


def test_strip_emotions_keeps_legacy_parity_for_markdown() -> None:
    """Паритет с прежним PiperService: ролевые *звёздочки* съедают блок **жирный**.

    Это известная особенность унаследованной чистки текста, а не новое
    поведение: `SpeechText.Clean` в C# гасит такие блоки так же. Тест
    фиксирует паритет — модули, которые зависят от текста для TTS, не
    меняются вместе с движком.
    """
    cleaned = strip_emotions("**жирный** текст")

    assert "жирный" not in cleaned
    assert "текст" in cleaned


def test_strip_emotions_keeps_plain_text() -> None:
    """Обычный текст не меняется (кроме пробелов)."""
    assert strip_emotions("Сегодня хорошая погода.") == "Сегодня хорошая погода."


# ── Ленивая загрузка ────────────────────────────────────────────────


def test_model_is_lazy_and_loads_once() -> None:
    """Модель грузится при первом синтезе и только один раз на процесс."""
    with fake_dependencies(), tempfile.TemporaryDirectory() as tmp:
        manager = _manager()

        assert manager.is_loaded is False, "конструктор не должен грузить модель"
        assert FakeChat.instances == [], "ChatTTS.Chat() создаётся лениво"

        first = manager.synthesize("Проверка.", str(Path(tmp) / "a.wav"))
        assert Path(first).name == "a.wav"
        assert len(FakeChat.instances) == 1

        manager.synthesize("Ещё раз.", str(Path(tmp) / "b.wav"))
        assert len(FakeChat.instances) == 1, "второй синтез переиспользует модель"

        assert FakeChat.instances[0].load_calls == [False], (
            "эталон инициализации: chat.load(compile=False)"
        )


def test_load_model_is_idempotent() -> None:
    """Повторный load_model() не создаёт второй экземпляр ChatTTS."""
    with fake_dependencies():
        manager = _manager()

        manager.load_model()
        manager.load_model()

        assert len(FakeChat.instances) == 1


def test_close_releases_model() -> None:
    """close() выгружает модель: следующий синтез создаёт её заново."""
    with fake_dependencies():
        manager = _manager()
        manager.load_model()

        manager.close()

        assert manager.is_loaded is False
        manager.load_model()
        assert len(FakeChat.instances) == 2


def test_initialize_does_not_load_model() -> None:
    """Адаптер: initialize() проверяет окружение, но модель не грузит."""
    with fake_dependencies(), mock.patch.object(
        ChatTTSManager, "availability", return_value=(True, "ChatTTS доступен")
    ):
        service = ChatTtsService()

        assert service.initialize("zere-warm") is True
        assert service.current_voice == "zere-warm"
        assert FakeChat.instances == [], "initialize не должен поднимать модель"


def test_availability_reports_missing_modules() -> None:
    """Проверка окружения не импортирует ChatTTS и объясняет причину отказа."""
    ok, reason = ChatTTSManager.availability()

    assert isinstance(ok, bool)
    assert isinstance(reason, str) and reason

    if not ok:
        assert "ChatTTS" in reason or "torch" in reason or "soundfile" in reason


def test_availability_does_not_import_heavy_modules() -> None:
    """availability() работает без импорта ChatTTS (иначе лавина зависимостей)."""
    saved = sys.modules.pop("ChatTTS", None)

    try:
        ChatTTSManager.availability()
        assert "ChatTTS" not in sys.modules, "availability() не должен импортировать ChatTTS"
    finally:
        if saved is not None:
            sys.modules["ChatTTS"] = saved


# ── Эталонные параметры и профили голоса ────────────────────────────


def test_reference_inference_params() -> None:
    """temperature 0.3 / top_P 0.7 / top_K 20 — эталонные настройки голоса."""
    with fake_dependencies(), tempfile.TemporaryDirectory() as tmp:
        manager = _manager("zere-warm")
        manager.synthesize("Проверка.", str(Path(tmp) / "p.wav"))

        params = FakeChat.instances[0].infer_calls[0][1]

        assert params is not None
        assert params.temperature == 0.3
        assert params.top_P == 0.7
        assert params.top_K == 20
        assert params.spk_emb == "speaker-embedding"


def test_speaker_is_deterministic_and_cached() -> None:
    """Профиль голоса — стабильное зерно: один профиль = один голос."""
    with fake_dependencies(), tempfile.TemporaryDirectory() as tmp:
        first = _manager("zere-ironic")
        second = _manager("zere-ironic")

        first.synthesize("Раз.", str(Path(tmp) / "1.wav"))
        second.synthesize("Два.", str(Path(tmp) / "2.wav"))

        assert ChatTTSManager._voice_seed("zere-ironic") == ChatTTSManager._voice_seed("zere-ironic")
        assert ChatTTSManager._voice_seed("zere-ironic") != ChatTTSManager._voice_seed("zere-warm")

        assert FakeChat.instances[0].speaker_calls == 1, "эмбеддинг кэшируется"

        same = _manager("zere-ironic")
        same.load_model()
        same._speaker(same._chat)  # noqa: SLF001 — прямой доступ к кэшу эмбеддинга
        same._speaker(same._chat)  # noqa: SLF001
        assert same._chat.speaker_calls == 1  # noqa: SLF001


def test_available_voices_contains_builtin_profiles() -> None:
    """Список профилей голоса не пуст и содержит профиль по умолчанию."""
    manager = _manager()

    voices = manager.available_voices()

    assert DEFAULT_VOICE in voices
    assert set(BUILTIN_VOICES).issubset(set(voices))


def test_set_voice_switches_profile() -> None:
    """Смена профиля не требует перезагрузки модели."""
    manager = _manager()

    manager.set_voice("zere-business")

    assert manager.current_voice == "zere-business"
    assert manager.is_loaded is False


# ── Темп речи ───────────────────────────────────────────────────────


def test_speed_maps_to_chattts_token() -> None:
    """length_scale → [speed_N]: 1.0 нейтрально, >1 медленнее (как у Piper)."""
    with fake_dependencies(), tempfile.TemporaryDirectory() as tmp:
        manager = _manager()

        manager.set_inference_params(1.15, 0.0)
        manager.synthesize("Раз.", str(Path(tmp) / "1.wav"))
        assert FakeChat.instances[-1].infer_calls[-1][1].prompt == "[speed_4]"

        manager.set_inference_params(1.0, 0.0)
        manager.synthesize("Два.", str(Path(tmp) / "2.wav"))
        assert FakeChat.instances[-1].infer_calls[-1][1].prompt == "[speed_5]"


def test_speed_is_clamped() -> None:
    """Слишком быстрый/медленный темп зажимается в шкалу 1…9 ChatTTS."""
    with fake_dependencies(), tempfile.TemporaryDirectory() as tmp:
        manager = _manager()

        manager.set_inference_params(0.5, 0.0)
        manager.synthesize("Раз.", str(Path(tmp) / "1.wav"))
        assert FakeChat.instances[-1].infer_calls[-1][1].prompt == "[speed_9]"

        manager.set_inference_params(3.0, 0.0)
        manager.synthesize("Два.", str(Path(tmp) / "2.wav"))
        assert FakeChat.instances[-1].infer_calls[-1][1].prompt == "[speed_2]"


# ── Синтез ──────────────────────────────────────────────────────────


def test_synthesize_writes_wav_at_24khz() -> None:
    """WAV пишется через soundfile на 24000 Гц (частота ChatTTS)."""
    with fake_dependencies(), tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "out.wav"
        manager = _manager()
        manager.set_inference_params(1.0, 0.0)  # без добавочной тишины

        result = manager.synthesize("Привет.", str(target))

        assert result == str(target)
        assert SAMPLE_RATE == 24000
        assert FakeSoundFile.writes == [(str(target), 24000, FakeWave.SAMPLES)]


def test_synthesize_sentences_appends_silence() -> None:
    """Попредложенный синтез: по кадру на предложение + тишина после каждого."""
    with fake_dependencies(), tempfile.TemporaryDirectory() as tmp:
        manager = _manager()
        manager.set_inference_params(1.0, 0.1)  # 0.1 с = 2400 сэмплов

        manager.synthesize_sentences("Привет. Как дела?", str(Path(tmp) / "s.wav"))

        chat = FakeChat.instances[0]
        assert [texts[0] for texts, _ in chat.infer_calls] == ["Привет.", "Как дела?"]

        _, rate, samples = FakeSoundFile.writes[0]
        assert rate == 24000
        assert samples == 2 * (FakeWave.SAMPLES + 2400), "тишина дописана после предложений"


def test_synthesize_rejects_empty_text() -> None:
    """Пустой текст — ошибка, а не «тихий» WAV нулевой длины."""
    manager = _manager()

    for text in ("", "   "):
        try:
            manager.waveform(text)
        except ValueError:
            continue
        raise AssertionError(f"ожидалось ValueError для {text!r}")


# ── Контракт ChatTtsService (паритет с PiperService) ────────────────


def test_service_contract_matches_previous_engine_contract() -> None:
    """Набор членов — тот же, что был у прежнего движка: VoiceManager не менялся."""
    service = ChatTtsService()

    for name in (
        "is_loaded",
        "current_voice",
        "initialize",
        "speak",
        "set_voice",
        "set_inference_params",
        "get_available_voices",
        "close",
    ):
        assert hasattr(service, name), f"в контракте нет {name}"

    assert service.is_loaded is False, "до initialize движок не считается готовым"


def test_service_unavailable_falls_back_to_text() -> None:
    """Нет ChatTTS — speak() возвращает "" (вызывающий код печатает текст)."""
    with mock.patch.object(
        ChatTTSManager, "availability", return_value=(False, "нет модулей: ChatTTS")
    ):
        service = ChatTtsService()

        assert service.initialize() is False
        assert service.is_loaded is False
        assert service.speak("Привет.") == ""


def test_service_speak_strips_noise_and_returns_path() -> None:
    """speak() чистит текст и отдаёт путь к WAV, полученный от менеджера."""
    with mock.patch.object(
        ChatTTSManager, "availability", return_value=(True, "ChatTTS доступен")
    ), mock.patch.object(
        ChatTTSManager, "synthesize_sentences", return_value="/tmp/out.wav"
    ) as synth:
        service = ChatTtsService()
        assert service.initialize() is True

        assert service.speak("Привет 😊") == "/tmp/out.wav"

        spoken_text = synth.call_args[0][0]
        assert "😊" not in spoken_text
        assert spoken_text.startswith("Привет")


def test_service_speak_skips_empty_text() -> None:
    """Пустой текст после чистки не доходит до модели."""
    with mock.patch.object(
        ChatTTSManager, "availability", return_value=(True, "ChatTTS доступен")
    ), mock.patch.object(ChatTTSManager, "synthesize_sentences") as synth:
        service = ChatTtsService()
        service.initialize()

        assert service.speak("   ") == ""
        synth.assert_not_called()


def test_service_output_dir_is_chattts() -> None:
    """Временные WAV синтеза лежат в ZERE.Voice/ChatTts (а не в старой папке Piper)."""
    service = ChatTtsService()

    assert service._output_dir.name == "ChatTts"  # noqa: SLF001
    assert service._output_dir.parent.name == "ZERE.Voice"  # noqa: SLF001


def test_service_set_voice_updates_manager() -> None:
    """set_voice() доходит до менеджера (голос меняется без перезагрузки)."""
    service = ChatTtsService()

    service.set_voice("zere-casual")

    assert service.current_voice == "zere-casual"
    assert service.manager.current_voice == "zere-casual"


# ── Сайдкар для C#-редакции ─────────────────────────────────────────


def _load_server_module() -> Any:
    """Импортирует tools/zere_chattts_server.py без запуска сервера."""
    path = ROOT / "tools" / "zere_chattts_server.py"
    spec = importlib.util.spec_from_file_location("zere_chattts_server", path)
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_server_prepare_flattens_text() -> None:
    """Сайдкар отдаёт в модель ровный текст без переводов строк."""
    server = _load_server_module()

    assert server.prepare("Первая строка.\nВторая строка.\r\n") == (
        "Первая строка. Вторая строка."
    )


def test_server_speed_matches_manager_mapping() -> None:
    """Клиент присылает length_scale — сайдкар переводит его в [speed_N]."""
    server = _load_server_module()

    with fake_dependencies():
        manager = server.MANAGER
        manager.set_voice("zere-standard")

        server.apply_request_params({"voice": "zere-warm", "speed": 1.0, "silence": 0.0})
        assert manager.current_voice == "zere-warm"

        manager.synthesize("Проверка.", "unused.wav")
        assert FakeChat.instances[-1].infer_calls[-1][1].prompt == "[speed_5]"


def test_server_declares_pcm_contract() -> None:
    """Контракт данных: PCM s16le, 24 кГц, X-Sample-Rate в ответе."""
    server = _load_server_module()

    source = (ROOT / "tools" / "zere_chattts_server.py").read_text(encoding="utf-8")

    assert server.SAMPLE_RATE == 24000
    assert "X-Sample-Rate" in source
    assert "application/octet-stream" in source
    assert "/health" in source and "/tts" in source


@contextmanager
def running_server(server: Any) -> Iterator[str]:
    """Поднимает сайдкар на свободном порту (модель подменена фейком)."""
    from http.server import ThreadingHTTPServer
    from threading import Thread

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _http_get(url: str) -> tuple[int, dict[str, str], bytes]:
    from urllib.request import urlopen

    with urlopen(url, timeout=10) as response:  # noqa: S310 — локальный сервер теста
        return response.status, dict(response.headers), response.read()


def _http_post(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    from urllib.request import Request, urlopen

    request = Request(  # noqa: S310 — локальный сервер теста
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers or {}), error.read()


def test_server_health_reports_ready_contract() -> None:
    """/health отдаёт статус, частоту и список профилей голоса (C# ждёт ready)."""
    with fake_dependencies():
        server = _load_server_module()
        server.STATUS = {"state": "ready", "detail": ""}

        with running_server(server) as base:
            status, _headers, body = _http_get(base + "/health")

        payload = json.loads(body.decode("utf-8"))

        assert status == 200
        assert payload["status"] == "ready"
        assert payload["sample_rate"] == 24000
        assert DEFAULT_VOICE in payload["voices"]


def test_server_streams_pcm_with_sample_rate_header() -> None:
    """/tts отдаёт PCM s16le (2 байта на сэмпл) и заголовок X-Sample-Rate."""
    with fake_dependencies():
        server = _load_server_module()
        server.STATUS = {"state": "ready", "detail": ""}

        samples = FakeArray([0.0, 0.5, -0.5, 1.5])
        server.MANAGER.waveform = lambda _text: samples  # type: ignore[method-assign]

        with running_server(server) as base:
            status, headers, body = _http_post(
                base + "/tts",
                {"text": "Привет.", "voice": "zere-warm", "speed": 1.0, "silence": 0.0},
            )

        assert status == 200
        assert headers.get("X-Sample-Rate") == "24000"
        assert headers.get("Content-Type") == "application/octet-stream"
        assert len(body) == 2 * len(samples), "s16le: 2 байта на сэмпл"
        # 1.5 обрезается клипом до 1.0 → 32767; −0.5 → −16383
        assert int.from_bytes(body[0:2], "little", signed=True) == 0
        assert int.from_bytes(body[2:4], "little", signed=True) == 16383
        assert int.from_bytes(body[4:6], "little", signed=True) == -16383
        assert int.from_bytes(body[6:8], "little", signed=True) == 32767


def test_server_rejects_empty_text_and_unknown_path() -> None:
    """Пустой текст — 400, неизвестный путь — 404 (клиент видит внятную ошибку)."""
    with fake_dependencies():
        server = _load_server_module()

        with running_server(server) as base:
            status_text, _, _ = _http_post(base + "/tts", {"text": "   "})
            status_path, _, _ = _http_post(base + "/speak", {"text": "Привет."})

        assert status_text == 400
        assert status_path == 404


def test_command_runner_passes_command_verbatim() -> None:
    """Команда установки уходит в cmd.exe ДОСЛОВНО, без экранирования кавычек.

    Регрессия реального сбоя: `subprocess.run(["cmd.exe", "/c", command])`
    заставляет Python экранировать внутренние кавычки обратными слэшами, а
    cmd.exe такого не понимает. Строка установки ChatTTS
    (`"<venv>\\python.exe" -m pip install ...`) превращалась в
    `"\\"<venv>\\python.exe\\" ..."` и падала с сообщением «не является
    внутренней или внешней командой» — установка не доходила до pip.
    """
    from zere.core.dependencies import dependency_checker as dc

    captured: dict[str, Any] = {}

    def fake_run(command: Any, **kwargs: Any) -> Any:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, b"", b"")

    command = '"C:\\path with spaces\\python.exe" -m pip install ChatTTS soundfile'

    with mock.patch.object(dc.subprocess, "run", side_effect=fake_run):
        exit_code = dc.DependencyChecker._run_streaming(command)

    assert exit_code == 0
    assert isinstance(captured["command"], str), "команда идёт строкой, а не списком"
    assert captured["command"] == command, "кавычки не должны переэкранироваться"
    assert '\\"' not in captured["command"]
    assert captured["kwargs"].get("shell") is True, (
        "только shell=True отдаёт команду в cmd.exe дословно"
    )


def test_install_chattts_targets_current_interpreter() -> None:
    """Установка ChatTTS идёт в текущее окружение и без лишних кавычек."""
    from zere.core.dependencies import dependency_checker as dc

    executed: list[tuple[str, str]] = []

    def fake_execute(command: str, description: str) -> None:
        executed.append((command, description))

    checker = dc.DependencyChecker.__new__(dc.DependencyChecker)
    # Подменяем на экземпляре: метод вызывается как self._execute_command_...
    checker._execute_command_with_confirmation = fake_execute  # noqa: SLF001

    with mock.patch.object(
        dc, "_chattts_availability", return_value=(True, "ChatTTS доступен")
    ):
        dc.DependencyChecker._install_chattts(checker)

    assert len(executed) == 1
    command, _description = executed[0]

    assert sys.executable in command, "ставим в тот же Python, которым запущен ZERE"
    assert "pip install ChatTTS soundfile" in command
    assert '\\"' not in command


def test_availability_message_has_no_stale_python_limit() -> None:
    """Сообщение о недоступности не обещает несуществующего ограничения версии.

    Проверено по PyPI: у зависимостей ChatTTS (torch, torchaudio, numba,
    pybase16384) есть колёса для Python 3.10–3.14, поэтому «Python ≤ 3.12»
    в тексте вводило бы в заблуждение.
    """
    from zere.voice.chattts.chattts_manager import ChatTTSManager

    _ok, reason = ChatTTSManager.availability()

    assert "≤ 3.12" not in reason
    assert "3.13" not in reason


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов ChatTTS")


if __name__ == "__main__":
    sys.exit(main())
