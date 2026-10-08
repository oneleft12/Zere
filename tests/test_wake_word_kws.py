"""Тесты стримингового KWS-детектора слова-триггера (docs/WAKE_WORD.md).

Проверяется всё, что не требует микрофона и настоящей модели: кольцевой
буфер, манифест модели, сглаживание/порог/cooldown, энергетическая отсечка
тишины и выбор движка фабрикой. Микрофон и ONNX-сессия подменяются
заглушками (микрофона в CI нет, а веса модели — gitignored ≥ 1 МБ).

Запуск: python3 tests/test_wake_word_kws.py
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# audio_recorder тянет sounddevice (PortAudio) — на безголосых машинах
# (CI) достаточно заглушки, как в tests/test_wake_word.py.
try:
    import sounddevice  # noqa: F401
except Exception:  # noqa: BLE001 — ImportError или OSError от PortAudio
    sys.modules.setdefault("sounddevice", types.ModuleType("sounddevice"))


# ── Заглушки ────────────────────────────────────────────────


class _FakeRecorder:
    """Рекордер-заглушка: кормит слушателя блоками в фоновом потоке."""

    def __init__(self, amplitude: float = 0.05, block: int = 640) -> None:
        self.listener = None
        self.stopped = 0
        self.closed = 0
        self.amplitude = amplitude
        self.block = block
        self._alive = False
        self._thread: threading.Thread | None = None
        self._rng = np.random.default_rng(0)

    def start_continuous_recording(self, buffer_seconds: int = 10, sample_rate: int = 16000) -> None:
        self._alive = True

    def add_listener(self, listener) -> None:
        self.listener = listener
        self._thread = threading.Thread(target=self._feed, daemon=True)
        self._thread.start()

    def _feed(self) -> None:
        while self._alive and self.listener is not None:
            block = (self._rng.standard_normal(self.block) * self.amplitude).astype(np.float32)
            self.listener(block)
            time.sleep(0.004)

    def remove_listener(self, listener) -> None:
        self._alive = False
        self.listener = None

    def stop_continuous_recording(self) -> None:
        self.stopped += 1
        self._alive = False

    def close(self) -> None:
        self.closed += 1
        self._alive = False


class _ScriptedSession:
    """ONNX-сессия-заглушка: отдаёт заранее заданные вероятности по порядку."""

    def __init__(self, scores: list[float]) -> None:
        self.scores = list(scores) or [0.0]
        self.calls = 0
        self.windows: list[int] = []

    def run(self, output_names, feeds):  # noqa: ANN001, ANN201 — контракт ORT
        index = min(self.calls, len(self.scores) - 1)
        self.calls += 1
        window = next(iter(feeds.values()))
        self.windows.append(int(np.asarray(window).shape[-1]))
        return [np.array([[self.scores[index]]], dtype=np.float32)]


def _cancel_after(seconds: float) -> threading.Event:
    """Событие отмены, которое взводится через N секунд (защита от зависания)."""
    event = threading.Event()
    timer = threading.Timer(seconds, event.set)
    timer.daemon = True
    timer.start()
    return event


def _detector(
    scores: list[float],
    *,
    cancel_after: float = 1.5,
    amplitude: float = 0.05,
    model_dir: Path | None = None,
    **config_overrides: object,
):
    """Детектор с заглушками: своя модель-пустышка и поддельный микрофон."""
    from zere.voice.voice_config import VoiceConfig
    from zere.voice.wakeword import kws_detector

    config = VoiceConfig(**config_overrides)  # type: ignore[arg-type]
    session = _ScriptedSession(scores)
    recorder = _FakeRecorder(amplitude=amplitude)

    model_path = (model_dir or Path(tempfile.gettempdir())) / "wake_test.onnx"

    with mock.patch.object(kws_detector, "ContinuousAudioRecorder", lambda: recorder):
        detector = kws_detector.KwsWakeWordDetector(
            config,
            model_path=model_path,
            session_factory=lambda _path: session,
        )

    return detector, session, recorder


# ── Имена файлов и манифест ─────────────────────────────────


def test_transliterate_and_model_paths() -> None:
    """Слово-триггер → имя файла модели; не-буквы отбрасываются."""
    from zere.voice.wakeword.kws_detector import model_path_for, transliterate

    assert transliterate("зере") == "zere"
    assert transliterate("Зере") == "zere"
    assert transliterate("эй, зере") == "eyzere"
    assert transliterate("") == "wake"
    assert model_path_for("зере").name == "wake_zere.onnx"


def test_ring_buffer_returns_last_samples() -> None:
    """Кольцевой буфер: последние N сэмплов и корректная работа по кругу."""
    from zere.voice.wakeword.kws_detector import _RingBuffer

    ring = _RingBuffer(10)
    ring.write(np.arange(6, dtype=np.float32))
    assert ring.written == 6
    assert ring.read_last(4).tolist() == [2.0, 3.0, 4.0, 5.0]
    # Меньше записано, чем просим — отдаём сколько есть
    assert ring.read_last(100).tolist() == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]

    ring.write(np.arange(6, 14, dtype=np.float32))  # перезапись по кругу
    assert ring.written == 14
    assert ring.read_last(10).tolist() == [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0]


def test_manifest_defaults_and_overrides() -> None:
    """Манифест рядом с моделью переопределяет дефолты; битый — не ломает."""
    from zere.voice.wakeword.kws_detector import load_manifest

    with tempfile.TemporaryDirectory() as tmp:
        model = Path(tmp) / "wake_zere.onnx"
        model.write_bytes(b"")

        defaults = load_manifest(model)
        assert defaults["threshold"] == 0.7
        assert defaults["hop_samples"] == 640

        model.with_suffix(".json").write_text(
            '{"threshold": 0.91, "min_consecutive": 3, "cooldown_ms": 500}',
            encoding="utf-8",
        )
        custom = load_manifest(model)
        assert custom["threshold"] == 0.91
        assert custom["min_consecutive"] == 3
        assert custom["cooldown_ms"] == 500
        assert custom["sample_rate"] == 16000  # остальное — из дефолтов

        model.with_suffix(".json").write_text("{не json", encoding="utf-8")
        assert load_manifest(model)["threshold"] == 0.7


# ── Логика срабатывания ─────────────────────────────────────


def test_detector_fires_on_confident_scores() -> None:
    """Уверенные кадры подряд → срабатывание и возврат слова."""
    detector, session, recorder = _detector([0.9], cancel_after=2.0)
    started = time.monotonic()
    result = detector.wait_for_wake_word(_cancel_after(2.0))
    elapsed = time.monotonic() - started

    assert result == "зере", f"ожидалось слово, получено {result!r}"
    assert elapsed < 1.0, f"срабатывание слишком долгое: {elapsed:.2f} с"
    assert session.calls >= 2, "сглаживание не потребовало нескольких кадров"
    assert all(length == 16000 for length in session.windows), "окно не 1 с"
    detector.close()
    assert recorder.closed == 1


def test_detector_ignores_single_high_score() -> None:
    """Один высокий кадр (щелчок/шум) не будит: сглаживание важнее recall."""
    # Первый кадр 0.99, дальше тишина по вероятности → сглаживание не наберётся
    detector, session, _ = _detector([0.99, 0.05], cancel_after=1.0)
    result = detector.wait_for_wake_word(_cancel_after(1.0))

    assert result == ""
    assert session.calls >= 2
    detector.close()


def test_detector_returns_empty_on_cancel() -> None:
    """Отмена (выключение режима) не даёт ложного срабатывания."""
    detector, _, recorder = _detector([0.0], cancel_after=0.6)
    assert detector.wait_for_wake_word(_cancel_after(0.6)) == ""
    # Отмена — запись останавливаем (в отличие от срабатывания)
    assert recorder.stopped >= 1
    detector.close()


def test_config_threshold_overrides_manifest() -> None:
    """Порог из конфига (wake_threshold) перекрывает значение манифеста."""
    detector, _, _ = _detector([0.9], cancel_after=1.0, wake_threshold=0.95)
    assert detector.wait_for_wake_word(_cancel_after(1.0)) == ""
    detector.close()

    fired, _, _ = _detector([0.9], cancel_after=2.0, wake_threshold=0.5)
    assert fired.wait_for_wake_word(_cancel_after(2.0)) == "зере"
    fired.close()


def test_energy_gate_skips_inference_in_silence() -> None:
    """В тишине модель не запускается вовсе (отсечка по RMS)."""
    gated, gated_session, _ = _detector([0.9], cancel_after=0.6, amplitude=0.0)
    assert gated.wait_for_wake_word(_cancel_after(0.6)) == ""
    assert gated_session.calls == 0, "в тишине инференс не должен запускаться"
    gated.close()

    # Тот же вход с выключенной отсечкой — модель вызывается (значит,
    # пропуск выше дала именно отсечка, а не что-то ещё).
    ungated, ungated_session, _ = _detector(
        [0.0], cancel_after=0.6, amplitude=0.0, wake_energy_gate=False
    )
    assert ungated.wait_for_wake_word(_cancel_after(0.6)) == ""
    assert ungated_session.calls > 0
    ungated.close()


def test_cooldown_prevents_immediate_refire() -> None:
    """После срабатывания cooldown не даёт мгновенно сработать снова."""
    detector, _, _ = _detector([0.9], cancel_after=2.0, wake_cooldown_ms=5000)
    assert detector.wait_for_wake_word(_cancel_after(2.0)) == "зере"

    # Второй вызов сразу же: пока cooldown не истёк — не срабатывает
    assert detector.wait_for_wake_word(_cancel_after(0.4)) == ""
    detector.close()


# ── Выбор движка ────────────────────────────────────────────


def test_detect_wake_engine_without_model_is_whisper() -> None:
    """Нет модели → фабрика и статус честно показывают прежний движок."""
    from zere.voice.voice_config import VoiceConfig
    from zere.voice.wakeword import detect_wake_engine, kws_detector

    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(kws_detector, "MODEL_DIR", Path(tmp) / "нет-моделей"):
            assert detect_wake_engine(VoiceConfig()) == "whisper"
            assert detect_wake_engine(VoiceConfig(wake_engine="kws")) == "whisper"
            assert detect_wake_engine(VoiceConfig(wake_engine="whisper")) == "whisper"


def test_detect_wake_engine_with_model_is_kws() -> None:
    """Есть модель + onnxruntime → движок onnx-kws."""
    from zere.voice.voice_config import VoiceConfig
    from zere.voice.wakeword import detect_wake_engine, kws_detector

    factory_ns = sys.modules["zere.voice.wakeword"]

    with tempfile.TemporaryDirectory() as tmp:
        model_dir = Path(tmp) / "models"
        model_dir.mkdir()
        (model_dir / "wake_zere.onnx").write_bytes(b"onnx")

        with mock.patch.object(kws_detector, "MODEL_DIR", model_dir):
            with mock.patch.object(factory_ns, "onnx_available", lambda: True):
                assert detect_wake_engine(VoiceConfig()) == "onnx-kws"
                assert detect_wake_engine(VoiceConfig(wake_engine="whisper")) == "whisper"


def test_factory_falls_back_to_stt_detector() -> None:
    """Фабрика: без модели (или при engine=whisper) — прежний детектор на STT."""
    from zere.voice.voice_config import VoiceConfig
    from zere.voice.wakeword import create_wake_detector, kws_detector
    from zere.voice.wakeword import wake_word_detector as stt_module

    fake_stt = mock.Mock(name="WakeWordDetector")

    with tempfile.TemporaryDirectory() as tmp:
        # Патчим имя в пространстве самой фабрики — она импортирует класс к себе.
        with mock.patch.object(kws_detector, "MODEL_DIR", Path(tmp) / "нет-моделей"):
            with mock.patch.object(stt_module, "WakeWordDetector", fake_stt):
                factory_ns = sys.modules["zere.voice.wakeword"]
                with mock.patch.object(factory_ns, "WakeWordDetector", fake_stt):
                    assert (
                        create_wake_detector(VoiceConfig(), whisper=mock.Mock())
                        is fake_stt.return_value
                    )
                    assert (
                        create_wake_detector(VoiceConfig(wake_engine="kws"), whisper=mock.Mock())
                        is fake_stt.return_value
                    )


def test_factory_uses_kws_with_model() -> None:
    """Есть модель → фабрика отдаёт KWS-детектор (без onnxruntime — откат)."""
    from zere.voice.voice_config import VoiceConfig
    from zere.voice.wakeword import create_wake_detector, kws_detector

    with tempfile.TemporaryDirectory() as tmp:
        model_dir = Path(tmp) / "models"
        model_dir.mkdir()
        (model_dir / "wake_zere.onnx").write_bytes(b"onnx")

        factory_ns = sys.modules["zere.voice.wakeword"]

        # Сессию подменяем заглушкой: настоящих весов в репозитории нет.
        with mock.patch.object(kws_detector, "MODEL_DIR", model_dir):
            with mock.patch.object(factory_ns, "onnx_available", lambda: True):
                with mock.patch.object(
                    kws_detector,
                    "default_session_factory",
                    lambda _path: _ScriptedSession([0.0]),
                ):
                    detector = create_wake_detector(VoiceConfig())
                    try:
                        assert isinstance(detector, kws_detector.KwsWakeWordDetector)
                        assert detector.engine == "onnx-kws"
                        assert detector.model_path.name == "wake_zere.onnx"
                        assert detector.is_ready, "warmup не создал сессию"
                    finally:
                        detector.close()


def test_factory_falls_back_when_model_is_broken() -> None:
    """Битая модель (сессия не создалась) → откат на STT, а не мёртвый режим."""
    from zere.voice.voice_config import VoiceConfig
    from zere.voice.wakeword import create_wake_detector, kws_detector
    from zere.voice.wakeword import wake_word_detector as stt_module

    fake_stt = mock.Mock(name="WakeWordDetector")

    with tempfile.TemporaryDirectory() as tmp:
        model_dir = Path(tmp) / "models"
        model_dir.mkdir()
        (model_dir / "wake_zere.onnx").write_bytes(b"not an onnx model")

        def broken_factory(_path):
            raise ValueError("invalid onnx")

        factory_ns = sys.modules["zere.voice.wakeword"]

        with mock.patch.object(kws_detector, "MODEL_DIR", model_dir):
            with mock.patch.object(factory_ns, "onnx_available", lambda: True):
                with mock.patch.object(factory_ns, "WakeWordDetector", fake_stt):
                    with mock.patch.object(
                        kws_detector, "default_session_factory", broken_factory
                    ):
                        assert (
                            create_wake_detector(VoiceConfig(), whisper=mock.Mock())
                            is fake_stt.return_value
                        )


def test_explicit_model_path_wins() -> None:
    """config.wake_model_path задаёт модель явно (своя папка/своё слово)."""
    from zere.voice.voice_config import VoiceConfig
    from zere.voice.wakeword.kws_detector import resolve_model_path

    with tempfile.TemporaryDirectory() as tmp:
        model = Path(tmp) / "my_wake.onnx"
        model.write_bytes(b"onnx")

        assert resolve_model_path(VoiceConfig(wake_model_path=str(model))) == model
        assert resolve_model_path(VoiceConfig(wake_model_path=str(tmp) + "/нет.onnx")) is None


# ── Паритет с C#-редакцией ──────────────────────────────────


def test_csharp_has_same_wake_settings() -> None:
    """C#-редакция знает те же ключи конфига (общий config.json)."""
    import re

    voice_cs = (ROOT / "ZERE.Voice" / "VoiceConfig.cs").read_text(encoding="utf-8")
    core_cs = (ROOT / "ZERE.Core" / "Configuration" / "ZereConfig.cs").read_text(
        encoding="utf-8"
    )
    py_core = (ROOT / "zere" / "core" / "configuration" / "zere_config.py").read_text(
        encoding="utf-8"
    )

    assert re.search(r'WakeEngine\s*\{[^}]*\}\s*=\s*"auto"', voice_cs), "C#: нет WakeEngine=auto"
    assert "WakeModelPath" in voice_cs, "C#: нет WakeModelPath"
    assert re.search(r"WakeEnergyGate\s*\{[^}]*\}\s*=\s*true", voice_cs), "C#: нет WakeEnergyGate"
    assert "WakeThreshold" in voice_cs and "WakeCooldownMs" in voice_cs

    # Ключи config.json одинаковы в обеих редакциях (camelCase у C#,
    # snake_case у Python — читаются взаимно).
    assert "WakeEngine" in core_cs and "WakeModelPath" in core_cs, "C#: нет ключей wake"
    assert "wake_engine" in py_core and "wake_model_path" in py_core, "Python: нет ключей wake"


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов KWS-детектора")


if __name__ == "__main__":
    sys.exit(main())
