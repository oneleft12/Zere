"""Тесты Silero TTS — русского движка синтеза (замена ChatTTS для русского).

Проверяется то, что ломается при рефакторинге и что нельзя поймать «на слух»:

- ленивая загрузка: `initialize()` не трогает torch и не грузит модель; файл
  модели качается только при первом синтезе (и ровно один раз на процесс);
- контракт, идентичный ChatTtsService, — на него опирается VoiceManager;
- «санитайзинг» голоса: профиль ChatTTS (`zere-standard`) в конфиге не роняет
  Silero, а подменяется дефолтным голосом движка;
- разбивка на предложения и тишина `sentenceSilence` между ними;
- частота 24 кГц (как у ChatTTS, поэтому DSP и сайдкар не меняются);
- маршрутизация VoiceManager по ключу `ttsEngine` (chattts | silero) и честная
  возможность «темп речи» (у Silero v5 его нет);
- нормализация текста под русскую модель: цифры/дроби/даты/годы/единицы
  прописью, латиница практической транскрипцией, символы, которых нет в наборе
  символов модели, и гарантия «на выходе нет латиницы и цифр» (именно их
  `apply_tts` выбрасывал молча: «В 2026 году» звучало как «В году»);
- регрессия разбивки: точка между цифрами («3.5», «12.05.2026») не считается
  концом предложения.

torch, numpy и soundfile в тестах НЕ нужны: тяжёлые зависимости подменяются
фейками через `sys.modules` (это ещё и проверяет, что импорт ленивый —
зависимости подтягиваются внутри методов, а не на уровне модуля).

Запуск:
- `python3 tests/test_silero.py` — без зависимостей;
- `pytest tests/ -q` — в CI (функции test_* без аргументов).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zere.voice.silero.russian_numbers import (  # noqa: E402
    agree,
    decimal_to_words,
    integer_to_words,
    ordinal_to_words,
)
from zere.voice.silero.silero_manager import (  # noqa: E402
    BUILTIN_VOICES,
    DEFAULT_VOICE,
    MODEL_URL,
    SAMPLE_RATE,
    SileroManager,
    SileroUnavailable,
    split_sentences,
)
from zere.voice.silero.silero_service import SileroTtsService  # noqa: E402
from zere.voice.silero.silero_text import normalize  # noqa: E402


# ── Фейковые зависимости ────────────────────────────────────────────


class FakeArray:
    """Минимальный аналог numpy-массива для проверки конвейера синтеза."""

    def __init__(self, data: Any) -> None:
        self.data = [float(v) for v in data]

    def reshape(self, *_args: Any) -> "FakeArray":
        return self

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, item: Any) -> Any:
        # Как numpy: срез — массив, индекс — число (иначе ломается итерация
        # `for value in samples` в _to_pcm16).
        if isinstance(item, slice):
            return FakeArray(self.data[item])
        return self.data[item]


class FakeNumpy:
    float32 = "float32"

    @staticmethod
    def asarray(value: Any, dtype: Any = None) -> FakeArray:  # noqa: ARG004
        if isinstance(value, FakeArray):
            return value
        return FakeArray([float(v) for v in value])

    @staticmethod
    def zeros(count: int, dtype: Any = None) -> FakeArray:  # noqa: ARG004
        return FakeArray([0.0] * count)

    @staticmethod
    def concatenate(parts: list[FakeArray]) -> FakeArray:
        joined: list[float] = []
        for part in parts:
            joined.extend(part.data)
        return FakeArray(joined)


class FakeTensor:
    """Аналог torch.Tensor: нужны detach().cpu().numpy()."""

    def __init__(self, data: list[float]) -> None:
        self._data = data

    def detach(self) -> "FakeTensor":
        return self

    def cpu(self) -> "FakeTensor":
        return self

    def numpy(self) -> list[float]:
        return list(self._data)


class FakeModel:
    """Модель Silero: apply_tts(text, speaker, sample_rate) → «тензор»."""

    def __init__(self, samples: int = 10, value: float = 0.3) -> None:
        self.samples = samples
        self.value = value
        self.calls: list[tuple[str, str, int]] = []
        self.devices: list[Any] = []

    def to(self, device: Any) -> "FakeModel":
        self.devices.append(device)
        return self

    def apply_tts(self, *, text: str, speaker: str, sample_rate: int) -> FakeTensor:
        self.calls.append((text, speaker, sample_rate))
        return FakeTensor([self.value] * self.samples)


class FakePackageImporter:
    """Аналог torch.package.PackageImporter: считает загрузки модели."""

    instances: list["FakePackageImporter"] = []
    model: FakeModel | None = None
    error: Exception | None = None
    #: Предупреждения, которые «печатает» код ВНУТРИ модели при загрузке:
    #: реальный `v5_5_ru.pt` сыпет SyntaxWarning про `"\^"` (см. тесты ниже).
    warnings_to_emit: list[tuple[str, type[Warning]]] = []

    def __init__(self, path: str) -> None:
        self.path = path
        FakePackageImporter.instances.append(self)

    def load_pickle(self, group: str, name: str) -> FakeModel:
        assert (group, name) == ("tts_models", "model"), (group, name)

        if FakePackageImporter.error is not None:
            raise FakePackageImporter.error

        for message, category in FakePackageImporter.warnings_to_emit:
            warnings.warn(message, category, stacklevel=2)

        return FakePackageImporter.model or FakeModel()


class FakeHub:
    """Аналог torch.hub: «скачивание» создаёт файл нужного размера."""

    downloads: list[tuple[str, str]] = []

    @staticmethod
    def download_url_to_file(url: str, target: str, *args: Any, **kwargs: Any) -> None:  # noqa: ARG004
        FakeHub.downloads.append((url, target))
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PT")


class FakeTorch:
    """Аналог torch: hub/package/device/set_num_threads."""

    threads: list[int] = []
    package = types.SimpleNamespace(PackageImporter=FakePackageImporter)
    hub = FakeHub

    @staticmethod
    def device(name: str) -> str:
        return name

    @staticmethod
    def set_num_threads(count: int) -> None:
        FakeTorch.threads.append(count)


class FakeSoundfile:
    """Аналог soundfile: пишет «файл» и запоминает частоту дискретизации."""

    writes: list[tuple[str, int, int]] = []

    @staticmethod
    def write(path: str, samples: FakeArray, rate: int) -> None:
        FakeSoundfile.writes.append((str(path), len(samples.data), rate))
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"RIFF")


@contextmanager
def fake_dependencies() -> Iterator[FakeModel]:
    """Подменяет torch/numpy/soundfile фейками и отдаёт модель Silero."""
    model = FakeModel()

    FakePackageImporter.instances = []
    FakePackageImporter.model = model
    FakePackageImporter.error = None
    FakePackageImporter.warnings_to_emit = []
    FakeHub.downloads = []
    FakeSoundfile.writes = []
    FakeTorch.threads = []

    modules = {
        "torch": FakeTorch,
        "torch.package": FakeTorch.package,
        "numpy": FakeNumpy,
        "soundfile": FakeSoundfile,
    }

    with mock.patch.dict(sys.modules, modules):
        yield model


def reset_fakes() -> None:
    FakePackageImporter.instances = []
    FakePackageImporter.model = None
    FakePackageImporter.error = None
    FakePackageImporter.warnings_to_emit = []
    FakeHub.downloads = []
    FakeSoundfile.writes = []
    FakeTorch.threads = []


# ── Доступность ─────────────────────────────────────────────────────


def test_availability_true_when_modules_present() -> None:
    """torch и soundfile есть → движок доступен, а причина говорит про модель."""
    with mock.patch.object(SileroManager, "_has_module", return_value=True):
        available, reason = SileroManager.availability()

    assert available is True
    assert "Silero" in reason
    assert "модель" in reason, "пользователь должен знать про скачивание модели"


def test_availability_reports_missing_modules() -> None:
    """Нет torch → движок недоступен и причина говорит, что поставить."""

    def has_module(name: str) -> bool:
        return name != "torch"

    with mock.patch.object(SileroManager, "_has_module", side_effect=has_module):
        available, reason = SileroManager.availability()

    assert available is False
    assert "torch" in reason
    assert "pip install" in reason


# ── Голоса ──────────────────────────────────────────────────────────


def test_voice_is_sanitized_to_builtin() -> None:
    """Профиль ChatTTS из конфига не роняет Silero — берётся дефолтный голос."""
    manager = SileroManager("zere-standard")

    assert manager.current_voice == DEFAULT_VOICE
    assert DEFAULT_VOICE in BUILTIN_VOICES

    manager.set_voice("aidar")
    assert manager.current_voice == "aidar"

    manager.set_voice("zere-ironic")
    assert manager.current_voice == DEFAULT_VOICE, "чужой профиль → дефолт движка"


def test_available_voices_are_named_silero_voices() -> None:
    """У Silero голоса именованные (в отличие от «зёрен» ChatTTS)."""
    manager = SileroManager()

    assert manager.available_voices() == list(BUILTIN_VOICES)
    assert "baya" in manager.available_voices()


# ── Ленивая загрузка и модель ───────────────────────────────────────


def test_manager_does_not_load_model_until_synthesis() -> None:
    """Модель не грузится ни в конструкторе, ни в initialize-подобных вызовах."""
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        model_file = Path(tmp) / "v5_5_ru.pt"

        with fake_dependencies():
            manager = SileroManager(model_path=model_file)
            manager.set_inference_params(1.15, 0.2)

            assert manager.is_loaded is False
            assert FakePackageImporter.instances == [], "модель грузится лениво"

            manager.waveform("Привет")
            assert manager.is_loaded is True
            assert len(FakePackageImporter.instances) == 1

            manager.waveform("Ещё раз")
            assert len(FakePackageImporter.instances) == 1, "модель кэшируется"


def test_model_is_downloaded_once_when_file_missing() -> None:
    """Модель качается ровно тогда, когда файла нет."""
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        model_file = Path(tmp) / "v5_5_ru.pt"

        with fake_dependencies():
            manager = SileroManager(model_path=model_file)
            manager.load_model()

            assert FakeHub.downloads == [(MODEL_URL, str(model_file))]
            assert model_file.is_file()

            # Второй синтез ничего не качает.
            manager.waveform("Ещё")
            assert len(FakeHub.downloads) == 1


def test_model_file_is_reused_without_download() -> None:
    """Готовый файл модели используется как есть (без сети)."""
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        model_file = Path(tmp) / "v5_5_ru.pt"
        model_file.write_bytes(b"PT")

        with fake_dependencies():
            SileroManager(model_path=model_file).load_model()

            assert FakeHub.downloads == []
            assert FakePackageImporter.instances[0].path == str(model_file)


def test_broken_model_file_gives_readable_error() -> None:
    """Битый файл модели → SileroUnavailable с подсказкой удалить файл."""
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        model_file = Path(tmp) / "v5_5_ru.pt"
        model_file.write_bytes(b"PT")

        with fake_dependencies():
            FakePackageImporter.error = RuntimeError("broken pickle")

            manager = SileroManager(model_path=model_file)

            try:
                manager.load_model()
            except SileroUnavailable as ex:
                assert "Silero" in str(ex)
                assert "Удалите файл" in str(ex)
            else:  # pragma: no cover — ветка обязана бросать
                raise AssertionError("ожидалась SileroUnavailable")


#: Дословный текст предупреждения из модели `v5_5_ru.pt`
#: (`<torch_package_0>.multi_acc_v3_package.py:286`, torch 2.14 / Python 3.14).
FOREIGN_WARNING_TEXT = (
    '"\\^" is an invalid escape sequence. Such sequences will not work in the '
    'future. Did you mean "\\\\^"? A raw string is also an option.'
)


def test_foreign_syntax_warning_from_model_is_silenced() -> None:
    """Чужой SyntaxWarning из кода внутри модели не попадает в консоль ZERE.

    `v5_5_ru.pt` — torch.package-архив, и его `multi_acc_v3_package.py`
    собирает регулярку через `'\\^'`. Python 3.12+ компилирует этот файл при
    загрузке модели и печатает SyntaxWarning в консоль (реальный лог ZERE).
    Правкой кода это не убрать: файл внутри 145-МБ модели, которая качается
    заново, поэтому предупреждение гасится на время загрузки.
    """
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        model_file = Path(tmp) / "v5_5_ru.pt"
        model_file.write_bytes(b"PT")

        with fake_dependencies():
            FakePackageImporter.warnings_to_emit = [
                (FOREIGN_WARNING_TEXT, SyntaxWarning)
            ]

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                SileroManager(model_path=model_file).load_model()

    assert FakePackageImporter.instances, "модель всё-таки загружается"
    assert [w for w in caught if issubclass(w.category, SyntaxWarning)] == [], (
        "чужой SyntaxWarning из модели не должен попадать в консоль"
    )


def test_other_warnings_from_model_stay_visible() -> None:
    """Гасится только SyntaxWarning про escape-последовательности.

    Иначе «чистая консоль» означала бы, что мы прячем любые предупреждения
    чужого кода: предупреждения с другим текстом и другого класса остаются
    видимыми (их печатает консоль ZERE).
    """
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        model_file = Path(tmp) / "v5_5_ru.pt"
        model_file.write_bytes(b"PT")

        with fake_dependencies():
            FakePackageImporter.warnings_to_emit = [
                ("модель устарела", UserWarning),
                ("'is' with a literal. Did you mean '=='?", SyntaxWarning),
            ]

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                SileroManager(model_path=model_file).load_model()

    categories = [w.category for w in caught]

    assert UserWarning in categories, "чужие предупреждения видны в консоли"
    assert SyntaxWarning in categories, "гасится только текст про escape"


# ── Синтез ──────────────────────────────────────────────────────────


def test_synthesize_writes_wav_at_24khz() -> None:
    """WAV пишется на 24 кГц — как у ChatTTS, чтобы DSP/сайдкар не менялись."""
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "out.wav"

        with fake_dependencies():
            manager = SileroManager(model_path=Path(tmp) / "v5_5_ru.pt")
            manager.synthesize("Привет", str(target))

    assert FakeSoundfile.writes
    written_path, _samples, rate = FakeSoundfile.writes[-1]
    assert written_path == str(target)
    assert rate == SAMPLE_RATE == 24000


def test_sentences_are_split_and_silence_is_appended() -> None:
    """Каждое предложение — отдельный проход синтеза плюс тишина."""
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        with fake_dependencies() as model:
            manager = SileroManager(model_path=Path(tmp) / "v5_5_ru.pt")
            manager.set_inference_params(1.0, 0.5)  # 0.5 с тишины

            manager.synthesize_sentences("Раз. Два.", str(Path(tmp) / "out.wav"))

    assert [call[0] for call in model.calls] == ["Раз.", "Два."]
    assert all(call[2] == SAMPLE_RATE for call in model.calls), "частота синтеза"

    silence = int(0.5 * SAMPLE_RATE)
    assert FakeSoundfile.writes[-1][1] == 2 * (10 + silence)


def test_synthesize_rejects_empty_text() -> None:
    """Пустой текст не доходит до модели."""
    with tempfile.TemporaryDirectory() as tmp:
        manager = SileroManager(model_path=Path(tmp) / "v5_5_ru.pt")

        for text in ("", "   "):
            try:
                manager.synthesize_sentences(text, str(Path(tmp) / "out.wav"))
            except ValueError:
                pass
            else:  # pragma: no cover — ветка обязана бросать
                raise AssertionError("ожидался ValueError")


# ── Сервис (контракт ChatTtsService) ────────────────────────────────


def test_service_initialize_does_not_load_model() -> None:
    """initialize() — это проверка окружения, а не загрузка 145 МБ."""
    with mock.patch.object(
        SileroManager, "availability", return_value=(True, "Silero TTS доступен")
    ), mock.patch.object(SileroManager, "load_model") as load:
        service = SileroTtsService()

        assert service.initialize() is True
        assert service.is_loaded is True
        assert service.manager.is_loaded is False, "модель ещё не в памяти"
        load.assert_not_called()


def test_service_speak_strips_noise_and_returns_path() -> None:
    """speak() чистит текст и отдаёт путь к WAV, полученный от менеджера."""
    with mock.patch.object(
        SileroManager, "availability", return_value=(True, "Silero TTS доступен")
    ), mock.patch.object(
        SileroManager, "synthesize_sentences", return_value="/tmp/out.wav"
    ) as synth:
        service = SileroTtsService()
        assert service.initialize() is True

        assert service.speak("Привет 😊") == "/tmp/out.wav"

        spoken_text = synth.call_args[0][0]
        assert "😊" not in spoken_text
        assert spoken_text.startswith("Привет")


def test_service_speak_falls_back_to_text_without_engine() -> None:
    """Нет окружения — speak() отдаёт пустую строку (VoiceManager печатает текст)."""
    with mock.patch.object(
        SileroManager, "availability", return_value=(False, "нет модулей: torch")
    ):
        service = SileroTtsService()
        assert service.initialize() is False

        assert service.speak("Привет") == ""


def test_service_unavailable_reason_empty_when_engine_available() -> None:
    """Регрессия: причина не должна противоречить сама себе.

    На успешной проверке `availability()` возвращает пояснение «Silero
    доступен…» — оно не должно попадать в 503 «Синтез речи недоступен».
    """
    with mock.patch.object(
        SileroManager, "availability", return_value=(True, "Silero TTS доступен (модель качается)")
    ):
        service = SileroTtsService()  # initialize() не вызывался

        assert service.is_loaded is False
        assert service.unavailable_reason == ""


def test_service_speed_capability_is_honest() -> None:
    """У Silero v5 нет параметра темпа — панель не должна обещать настройку."""
    service = SileroTtsService()

    assert service.supports_speech_speed is False


def test_service_voice_is_sanitized() -> None:
    """service.initialize("zere-standard") не роняет движок и меняет голос."""
    with mock.patch.object(
        SileroManager, "availability", return_value=(True, "Silero TTS доступен")
    ):
        service = SileroTtsService()
        assert service.initialize("zere-standard") is True

        assert service.current_voice == DEFAULT_VOICE


# ── Маршрутизация VoiceManager ──────────────────────────────────────


def _import_voice_manager() -> Any:
    """VoiceManager с заглушкой sounddevice, если PortAudio/пакета нет."""
    try:
        import sounddevice  # noqa: F401
    except Exception:  # noqa: BLE001 — ImportError или OSError от PortAudio
        sys.modules.setdefault("sounddevice", types.ModuleType("sounddevice"))

    from zere.voice.voice_manager import VoiceManager

    return VoiceManager


def test_voice_manager_routes_tts_by_engine() -> None:
    """ttsEngine=silero → Silero, chattts (и «pocket» из C#) → ChatTTS."""
    VoiceManager = _import_voice_manager()

    with mock.patch.object(
        SileroManager, "availability", return_value=(True, "Silero TTS доступен")
    ):
        manager = VoiceManager()

        manager.config.tts_engine = "silero"
        assert manager.tts_engine == "silero"
        assert manager._active_tts.__class__.__name__ == "SileroTtsService"
        assert manager.supports_speech_speed is False

        assert manager.initialize("Casual") is True
        assert manager._active_tts.current_voice == "kseniya", "стиль → голос Silero"

        manager.config.tts_engine = "chattts"
        assert manager.tts_engine == "chattts"
        assert manager._active_tts.__class__.__name__ == "ChatTtsService"
        assert manager.supports_speech_speed is True

        # «pocket» — движок C#-редакции: в Python он означает ChatTTS.
        manager.config.tts_engine = "pocket"
        assert manager.tts_engine == "chattts"

    manager.close()


def test_voice_manager_silero_reason_is_honest() -> None:
    """Панель получает причину недоступности активного движка, а не ChatTTS."""
    VoiceManager = _import_voice_manager()

    with mock.patch.object(
        SileroManager, "availability", return_value=(False, "нет модулей: torch")
    ):
        manager = VoiceManager()
        manager.config.tts_engine = "silero"
        manager.initialize()

        assert manager.is_tts_available is False
        assert "torch" in manager.tts_unavailable_reason

    manager.close()


# ── Сайдкар для C#-редакции ─────────────────────────────────────────


def _load_server_module() -> Any:
    """Импортирует tools/zere_silero_server.py без запуска сервера."""
    path = ROOT / "tools" / "zere_silero_server.py"
    spec = importlib.util.spec_from_file_location("zere_silero_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sidecar_imports_without_torch() -> None:
    """Модуль сайдкара обязан импортироваться без torch (проверка --help в CI)."""
    module = _load_server_module()

    assert hasattr(module, "main")
    assert module.DEFAULT_PORT > 0


def test_sidecar_streams_pcm_s16le() -> None:
    """Сайдкар отдаёт PCM s16le 24 кГц — контракт C#-клиента."""
    module = _load_server_module()

    samples = FakeArray([0.0, 0.5, -0.5, 1.0, -1.0])
    pcm = module._to_pcm16(samples)

    assert len(pcm) == 2 * len(samples.data), "s16le: 2 байта на сэмпл"
    values = [
        int.from_bytes(pcm[i:i + 2], "little", signed=True)
        for i in range(0, len(pcm), 2)
    ]
    assert values == [0, 16383, -16383, 32767, -32767], values


def test_sidecar_health_reports_engine_state() -> None:
    """GET /health отдаёт статус движка для C#-холдера сайдкара."""
    module = _load_server_module()

    with mock.patch.object(
        SileroManager, "availability", return_value=(True, "Silero TTS доступен")
    ):
        payload = module._health_payload()

    assert payload["status"] in ("ready", "loading", "error"), payload
    assert json.dumps(payload)  # JSON-сериализуемо


def test_sidecar_rejects_unknown_command() -> None:
    """Неизвестная команда CLI → код возврата 2 (а не трейсбек)."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "zere_silero_server.py"), "--nope"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 2, result.stderr


# ── Текст: цифры и латиница (silero_text / russian_numbers) ─────────
#
# У русской модели v5_5_ru в наборе символов НЕТ ни цифр, ни латиницы, и
# `apply_tts` молча выбрасывает незнакомые символы: «В 2026 году» звучит как
# «В году», «GitHub» исчезает, а реплика целиком из латиницы падает с
# ValueError. Поэтому текст раскрывается в кириллицу ДО синтеза — этот
# контракт («на выходе нормализации нет латиницы и цифр») и проверяется.


def test_numbers_are_spelled_out_in_russian() -> None:
    """Кардиналы: род, разряды, «минус» (числа модель не читает вообще)."""
    assert integer_to_words(0) == "ноль"
    assert integer_to_words(7) == "семь"
    assert integer_to_words(21) == "двадцать один"
    assert integer_to_words(100) == "сто"
    assert integer_to_words(1001) == "тысяча один"
    assert integer_to_words(1500) == "тысяча пятьсот"
    assert integer_to_words(2026) == "две тысячи двадцать шесть"
    assert integer_to_words(1_000_000) == "миллион"
    assert integer_to_words(-7) == "минус семь"

    # Род: «одна минута», «две минуты» — иначе получилось бы «один минута».
    assert integer_to_words(1, feminine=True) == "одна"
    assert integer_to_words(2, feminine=True) == "две"


def test_agreement_picks_noun_form() -> None:
    """Согласование существительного с числом (1 / 2..4 / 5+)."""
    forms = ("процент", "процента", "процентов")

    assert [agree(n, forms) for n in (1, 2, 5)] == ["процент", "процента", "процентов"]
    assert agree(11, forms) == "процентов", "11..14 — всегда «процентов»"
    assert agree(21, forms) == "процент"
    assert agree(102, forms) == "процента"


def test_ordinal_years_decline_by_case() -> None:
    """Годы — порядковые: «в две тысячи двадцать шестом году»."""
    assert ordinal_to_words(2026) == "две тысячи двадцать шестой"
    assert ordinal_to_words(2026, "m", "pre") == "две тысячи двадцать шестом"
    assert ordinal_to_words(2026, "m", "gen") == "две тысячи двадцать шестого"

    # Круглые разряды — слитная форма («двухтысячный»), а не «две тысячи ноль».
    assert ordinal_to_words(2000) == "двухтысячный"
    assert ordinal_to_words(1000) == "тысячный"
    assert ordinal_to_words(100_000) == "стотысячный"

    # Составное числительное склоняет только последнее слово.
    assert ordinal_to_words(125) == "сто двадцать пятый"
    assert ordinal_to_words(125, "m", "gen") == "сто двадцать пятого"

    # Мягкое склонение («третий») и средний род для дат.
    assert ordinal_to_words(3, "f") == "третья"
    assert ordinal_to_words(3, "n") == "третье"
    assert ordinal_to_words(12, "n") == "двенадцатое"


def test_decimals_are_spelled_as_fractions() -> None:
    """«3,5» — «три целых пять десятых» (модель не читает ни цифр, ни точку)."""
    assert decimal_to_words("3,5") == "три целых пять десятых"
    assert decimal_to_words("0.5") == "ноль целых пять десятых"
    assert decimal_to_words("1.5") == "одна целая пять десятых"
    assert decimal_to_words("3.0") == "три", "нулевая дробь — просто целое"
    assert decimal_to_words("3.50") == "три целых пять десятых"


def test_normalize_expands_numbers_dates_and_units() -> None:
    """Даты, время, годы, проценты, единицы и порядковые — словами."""
    assert normalize("В 2026 году вышел Python") == "В две тысячи двадцать шестом году вышел Питон"
    assert normalize("С 2020 по 2024 год") == "с две тысячи двадцатого по две тысячи двадцать четвёртый год"
    assert normalize("5% и 1500 рублей") == "пять процентов и тысяча пятьсот рублей"
    assert normalize("3,5 ГБ") == "три целых пять десятых гигабайта"
    assert normalize("5 мс") == "пять миллисекунд"
    assert normalize("5-й пункт") == "пятый пункт"
    assert normalize("65 °C") == "шестьдесят пять градусов цельсия"
    assert normalize("минус 7 градусов") == "минус семь градусов"
    assert normalize("-7 °C") == "минус семь градусов цельсия"
    assert normalize("1 500 000 человек") == "миллион пятьсот тысяч человек"


def test_normalize_dates_and_times() -> None:
    """«12.05.2026» — дата, «13:45» — часы и минуты."""
    assert normalize("12.05.2026") == "двенадцатое мая две тысячи двадцать шестого года"
    assert normalize("13:45") == "тринадцать сорок пять"
    assert normalize("13:05") == "тринадцать ноль пять"

    # Две точки — не дата, а версия/техническое значение: «Python 3.12».
    assert normalize("Python 3.12") == "Питон три точка двенадцать"
    assert normalize("1.2.3") == "один точка два точка три"


def test_normalize_transliterates_english_words() -> None:
    """Латиница не выпадает из речи: словарь + правила транскрипции."""
    assert normalize("GitHub") == "Гитхаб"
    assert normalize("Открой Discord и Chrome") == "Открой Дискорд и Хром"
    assert normalize("ZERE слушает") == "Зере слушает"
    assert normalize("Hello, world!") == "хеллоу, уорлд!"

    # Сокращения читаются по буквам, а «mp3» — буквы плюс число.
    assert normalize("NASA и AI") == "Наса и эй-ай"
    assert normalize("CS2") == "си эс два"
    assert normalize("mp3") == "эм пи три"
    assert normalize("v5") == "ви пять"


def test_normalize_replaces_symbols_model_cannot_read() -> None:
    """«%», «№», «&», «@», «=» и валюты в наборе символов модели отсутствуют."""
    assert normalize("№ 5") == "номер пять"
    assert normalize("скидка 5%") == "скидка пять процентов"
    assert normalize("120000 ₽") == "сто двадцать тысяч рублей"
    assert normalize("2×3") == "два на три"
    assert normalize("1/2") == "одна вторая"
    assert normalize("user@mail.ru") == "юзер собака мейл.ру"

    # Длинного тире в наборе символов модели тоже нет: на его месте пауза,
    # иначе «привет—пока» склеилось бы в одно слово.
    assert normalize("Москва — столица") == "Москва, столица"


def test_normalize_leaves_no_latin_or_digits() -> None:
    """Гарантия контракта: модели не остаётся ничего непроизносимого.

    Это ровно та проверка, которой не хватало: раньше «В 2026 году» и
    «GitHub» проходили синтез БЕЗ ошибки, просто молча выпадали из речи.
    """
    corpus = [
        "Привет! Как дела?",
        "В 2026 году вышел Python 3.12 на 5 ГБ",
        "Открой GitHub и Discord, скачай Windows 11",
        "Цена 1500 рублей, скидка 5%, осталось 3,5 ГБ",
        "Встреча 12.05.2026 в 13:45, температура -7 °C",
        "iPhone 15 Pro Max и RTX 4090 стоят 120000 ₽",
        "ЗЕРЕ, включи музыку на 50%",
        "24/7 поддержка, 100% готово, версия 1.2.3",
    ]

    for text in corpus:
        normalized = normalize(text)

        assert normalized.strip(), f"нормализация не должна опустошать текст: {text!r}"

        leftover = [char for char in normalized if char.isascii() and char.isalnum()]

        assert leftover == [], (
            f"{text!r} → {normalized!r}: остались непроизносимые символы {leftover} "
            "(модель их молча выбросит)"
        )


def test_normalize_is_idempotent_and_keeps_russian() -> None:
    """Русский текст не портится, повторная нормализация ничего не меняет."""
    assert normalize("Привет, как дела?") == "Привет, как дела?"

    for text in ("В 2026 году вышел Python 3.12", "GitHub и 5%", "5-й пункт"):
        once = normalize(text)

        assert normalize(once) == once, f"нормализация не идемпотентна: {text!r}"


def test_manager_normalizes_text_before_synthesis() -> None:
    """Менеджер отдаёт модели уже кириллицу — иначе текст молча выпадет."""
    reset_fakes()

    with tempfile.TemporaryDirectory() as tmp:
        with fake_dependencies() as model:
            manager = SileroManager(model_path=Path(tmp) / "v5_5_ru.pt")
            manager.waveform("В 2026 году вышел GitHub 3.5")

    spoken = model.calls[0][0]

    assert "Гитхаб" in spoken
    assert "две тысячи двадцать шестом" in spoken
    assert [char for char in spoken if char.isascii() and char.isalnum()] == [], spoken


def test_normalization_does_not_break_empty_text() -> None:
    """Пустой/пробельный текст по-прежнему до модели не доходит."""
    assert normalize("") == ""
    assert normalize("   ") == ""
    assert normalize("🎵") == "", "эмодзи модель не читает — вырезаем"
    assert normalize("«Привет»") == "Привет", "кавычки модель не читает"


# ── Разбивка на предложения (регрессия: число рвалось по точке) ──────


def test_split_sentences_keeps_numbers_intact() -> None:
    """Точка между цифрами — не конец предложения.

    Раньше «Цена 3.5 рублей.» резалась на «Цена 3.» и «5 рублей.»: синтез
    читал «цена три» отдельной репликой, а число раскрывалось по частям.
    """
    assert split_sentences("Цена 3.5 рублей. Спасибо.") == [
        "Цена 3.5 рублей.",
        "Спасибо.",
    ]
    assert split_sentences("Встреча 12.05.2026 в 13:45. Не опаздывай!") == [
        "Встреча 12.05.2026 в 13:45.",
        "Не опаздывай!",
    ]
    assert split_sentences("Версия 1.2.3 вышла") == ["Версия 1.2.3 вышла"]
    assert split_sentences("Раз. Два.") == ["Раз.", "Два."]
    assert split_sentences("") == []


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов Silero TTS")


if __name__ == "__main__":
    sys.exit(main())
