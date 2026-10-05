"""Тесты выбора аудиоустройств: WASAPI + системный ресемплер, откат на MME.

Регрессия ошибки, которую видел пользователь в панели («Режим голоса →
Ошибка режима»):

    Error opening InputStream: Invalid sample rate [PaErrorCode -9997]

Причина: микрофон открывался в бэкенде WASAPI на 16 кГц (стандарт Whisper),
а WASAPI в shared-режиме принимает только частоту микшера Windows (живые
замеры на этой машине: WASAPI-микрофон Sennheiser — 48 кГц, WASAPI-вывод —
44.1 кГц). Лечится флагом `paWinWasapiAutoConvert` (`WasapiSettings
(auto_convert=True)`), а страховка — откат на устройство по умолчанию (MME),
где ресемплинг делает сам PortAudio.

Тесты детерминированные: sounddevice подменяется фейковыми устройствами,
воспроизводящими поведение PortAudio (`check_*_settings` падает с -9997 при
несовпадении частоты без auto_convert). Последний тест — живой: если в
системе есть микрофон, выбранный вариант реально открывается на 16 кГц.

Запуск: python3 tests/test_audio_device.py
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import types
import wave
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# audio_player/audio_recorder требуют sounddevice (PortAudio) — на безголосых
# машинах (CI) достаточно заглушки, как в tests/test_stt_engine.py.
try:
    import sounddevice as sd

    LIVE = hasattr(sd, "query_devices")
except Exception:  # noqa: BLE001 — ImportError или OSError от PortAudio
    sd = types.ModuleType("sounddevice")
    sys.modules["sounddevice"] = sd
    LIVE = False

from zere.core.console import configure_console_encoding  # noqa: E402
from zere.voice.audio import audio_device  # noqa: E402

# ── Фейковый звуковой тракт: как на машине пользователя ───────────────
# MME (индексы 0/1) и те же физические устройства в WASAPI (2/3). Микшерные
# частоты разные: у микрофона 48 кГц, у вывода 44.1 кГц — именно так на
# Windows 11 с Sennheiser USB headset (замеры в докстринге input_options).
WASAPI_INPUT_INDEX = 2
WASAPI_OUTPUT_INDEX = 3
INPUT_MIX_RATE = 48000
OUTPUT_MIX_RATE = 44100

DEVICES = [
    {
        "name": "Микрофон (Sennheiser USB headse",  # MME режет имя до 31 символа
        "hostapi": 0,
        "max_input_channels": 1,
        "max_output_channels": 0,
        "default_samplerate": 44100.0,
    },
    {
        "name": "Динамики (Sennheiser USB headse",
        "hostapi": 0,
        "max_input_channels": 0,
        "max_output_channels": 2,
        "default_samplerate": 44100.0,
    },
    {
        "name": "Микрофон (Sennheiser USB headset)",  # WASAPI отдаёт полное имя
        "hostapi": 1,
        "max_input_channels": 2,
        "max_output_channels": 0,
        "default_samplerate": 48000.0,
    },
    {
        "name": "Динамики (Sennheiser USB headset)",
        "hostapi": 1,
        "max_input_channels": 0,
        "max_output_channels": 2,
        "default_samplerate": 44100.0,
    },
]

HOSTAPIS = [{"name": "MME"}, {"name": "Windows WASAPI"}]


class FakePortAudioError(Exception):
    """Аналог sounddevice.PortAudioError — текст как в реальной ошибке."""


class FakeWasapiSettings:
    """Аналог sd.WasapiSettings: запоминает флаги."""

    def __init__(self, exclusive: bool = False, auto_convert: bool = False,
                 explicit_sample_format: bool = False) -> None:
        self.exclusive = exclusive
        self.auto_convert = auto_convert
        self.explicit_sample_format = explicit_sample_format


def _auto(extra_settings: object) -> bool:
    return bool(getattr(extra_settings, "auto_convert", False))


def fake_check_input_settings(
    *,
    device: object = None,
    samplerate: int = 16000,
    channels: int = 1,
    dtype: str = "int16",
    extra_settings: object = None,
) -> None:
    """PortAudio: WASAPI-устройство отдаёт только микшерную частоту.

    Без `auto_convert` любая другая частота — paInvalidSampleRate (-9997);
    устройство по умолчанию (MME, device=None) ресемплирует само.
    """
    if device is not None and samplerate != INPUT_MIX_RATE and not _auto(extra_settings):
        raise FakePortAudioError(
            "Error opening InputStream: Invalid sample rate [PaErrorCode -9997]"
        )


def fake_check_output_settings(
    *,
    device: object = None,
    samplerate: int = 44100,
    channels: int = 1,
    dtype: str = "float32",
    extra_settings: object = None,
) -> None:
    """То же для вывода: микшер 44.1 кГц, 22.05/48 кГц требуют auto_convert."""
    if device is not None and samplerate != OUTPUT_MIX_RATE and not _auto(extra_settings):
        raise FakePortAudioError(
            "Error opening OutputStream: Invalid sample rate [PaErrorCode -9997]"
        )


@contextlib.contextmanager
def fake_audio_environment(*, wasapi: bool = True):
    """Подменяет sounddevice фейковым трактом (устройства + проверки форматов)."""
    hostapis = HOSTAPIS if wasapi else [{"name": "MME"}]

    def query_devices(index: int | None = None) -> object:
        return DEVICES if index is None else DEVICES[index]

    def query_hostapis(index: int | None = None) -> object:
        return hostapis if index is None else hostapis[index]

    with contextlib.ExitStack() as stack:
        for name, value in (
            ("query_devices", query_devices),
            ("query_hostapis", query_hostapis),
            # MME-устройства по умолчанию: 0 — микрофон, 1 — динамики.
            ("default", types.SimpleNamespace(device=[0, 1])),
            ("check_input_settings", fake_check_input_settings),
            ("check_output_settings", fake_check_output_settings),
            ("WasapiSettings", FakeWasapiSettings),
        ):
            stack.enter_context(mock.patch.object(sd, name, value, create=True))
        yield


class FakeStream:
    """Заглушка sd.InputStream/sd.OutputStream: запоминает аргументы открытия."""

    created: list[dict] = []

    def __init__(self, **kwargs: object) -> None:
        FakeStream.created.append(dict(kwargs))
        self.kwargs = dict(kwargs)
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        pass

    def __enter__(self) -> "FakeStream":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def read(self, frames: int) -> tuple[np.ndarray, bool]:
        return np.zeros((frames, self.kwargs.get("channels", 1)), dtype=np.int16), False

    def write(self, data: object) -> None:
        pass


# ── Выбор устройства и частоты ───────────────────────────────────────


def test_input_options_use_wasapi_with_auto_convert() -> None:
    """Регрессия -9997: 16 кГц открываются только с auto_convert на WASAPI."""
    calls: list[dict] = []

    def spy_check(**kwargs: object) -> None:
        calls.append(kwargs)
        fake_check_input_settings(**kwargs)  # type: ignore[arg-type]

    with fake_audio_environment(), \
         mock.patch.object(sd, "check_input_settings", spy_check, create=True):
        options = audio_device.input_options(16000, channels=1, dtype="int16")

    # Порядок предпочтения: WASAPI как есть → WASAPI+авторесемплер → MME.
    assert calls[0]["device"] == WASAPI_INPUT_INDEX, (
        "WASAPI-устройство должно проверяться первым"
    )
    assert "extra_settings" not in calls[0], "сначала пробуем без ресемплера"
    assert calls[1]["device"] == WASAPI_INPUT_INDEX
    assert calls[1]["extra_settings"].auto_convert is True
    assert len(calls) == 2, "MME-откат не должен проверяться: WASAPI работает"

    assert options["device"] == WASAPI_INPUT_INDEX
    assert options["extra_settings"].auto_convert is True, (
        "без auto_convert WASAPI отклоняет 16 кГц (paInvalidSampleRate -9997)"
    )


def test_input_options_prefer_native_rate_without_resampler() -> None:
    """Если частота совпала с микшерной, системный ресемплер не подключается."""
    with fake_audio_environment():
        options = audio_device.input_options(INPUT_MIX_RATE)

    assert options == {"device": WASAPI_INPUT_INDEX}, (
        "на родной частоте обходимся без extra_settings (короче тракт)"
    )


def test_input_options_fall_back_to_default_device() -> None:
    """WASAPI-вариант не поддержан (микшер упрямится) → устройство по умолчанию."""

    def refuse_everything(**kwargs: object) -> None:
        raise FakePortAudioError(
            "Error opening InputStream: Invalid sample rate [PaErrorCode -9997]"
        )

    with fake_audio_environment(), \
         mock.patch.object(sd, "check_input_settings", refuse_everything, create=True):
        options = audio_device.input_options(16000)

    assert options == {"device": None}, "должен остаться MME-откат без extra_settings"


def test_input_options_without_wasapi_use_default_device() -> None:
    """WASAPI-бэкенда нет вовсе → обычное поведение sounddevice (device=None)."""
    with fake_audio_environment(wasapi=False):
        options = audio_device.input_options(16000)

    assert options == {"device": None}


def test_input_options_survive_missing_wasapi_settings() -> None:
    """Старый sounddevice без WasapiSettings: без флага → откат на MME, без падения."""
    with fake_audio_environment(), \
         mock.patch.object(sd, "WasapiSettings", None, create=True):
        options = audio_device.input_options(16000)

    assert options == {"device": None}, "без auto_convert 16 кГц на WASAPI не открыть"


def test_output_options_use_wasapi_with_auto_convert() -> None:
    """Вывод: частота WAV может не совпадать с микшером — та же страховка."""
    calls: list[dict] = []

    def spy_check(**kwargs: object) -> None:
        calls.append(kwargs)
        fake_check_output_settings(**kwargs)  # type: ignore[arg-type]

    with fake_audio_environment(), \
         mock.patch.object(sd, "check_output_settings", spy_check, create=True):
        options = audio_device.output_options(22050, channels=1, dtype="int16")

    assert calls[0]["device"] == WASAPI_OUTPUT_INDEX, "сначала без ресемплера"
    assert "extra_settings" not in calls[0]
    assert options["device"] == WASAPI_OUTPUT_INDEX
    assert options["extra_settings"].auto_convert is True


def test_output_options_prefer_native_rate_without_resampler() -> None:
    """Озвучка в 44.1 кГц (частота микшера) играет без системного ресемплера."""
    with fake_audio_environment():
        options = audio_device.output_options(OUTPUT_MIX_RATE)

    assert options == {"device": WASAPI_OUTPUT_INDEX}


def test_output_options_matching_rate_without_wasapi() -> None:
    """Без WASAPI вывод идёт на устройство по умолчанию (как было до правок)."""
    with fake_audio_environment(wasapi=False):
        options = audio_device.output_options(44100)

    assert options == {"device": None}


# ── Подключение: рекордеры и плеер реально просят auto_convert ───────


def test_continuous_recorder_opens_wasapi_with_auto_convert() -> None:
    """Непрерывная запись (wake word) — тот самый поток из ошибки в панели."""
    from zere.voice.audio.continuous_audio_recorder import ContinuousAudioRecorder

    FakeStream.created.clear()

    with fake_audio_environment(), \
         mock.patch.object(sd, "InputStream", FakeStream, create=True):
        recorder = ContinuousAudioRecorder()

        try:
            recorder.start_continuous_recording(buffer_seconds=1)
        finally:
            recorder.close()

    opened = FakeStream.created[-1]
    assert opened["samplerate"] == 16000
    assert opened["device"] == WASAPI_INPUT_INDEX
    assert opened["extra_settings"].auto_convert is True


def test_recorders_open_input_with_auto_convert() -> None:
    """AudioRecorder.record и record_with_vad — тоже 16 кГц на WASAPI."""
    from zere.voice.audio.audio_recorder import AudioRecorder

    FakeStream.created.clear()
    recorded: list[dict] = []

    def fake_rec(frames: int, **kwargs: object) -> np.ndarray:
        recorded.append(kwargs)
        return np.zeros((frames, 1), dtype=np.int16)

    with tempfile.TemporaryDirectory() as tmp:
        with fake_audio_environment(), \
             mock.patch.object(sd, "InputStream", FakeStream, create=True), \
             mock.patch.object(sd, "rec", fake_rec, create=True), \
             mock.patch.object(sd, "wait", lambda: None, create=True), \
             mock.patch.object(
                 AudioRecorder, "_input_folder",
                 staticmethod(lambda: Path(tmp)),
             ):
            recorder = AudioRecorder()
            recorder.record(seconds=1)
            recorder.record_with_vad(max_seconds=0)

    assert recorded[-1]["samplerate"] == 16000
    assert recorded[-1]["device"] == WASAPI_INPUT_INDEX
    assert recorded[-1]["extra_settings"].auto_convert is True

    opened = FakeStream.created[-1]
    assert opened["samplerate"] == 16000
    assert opened["device"] == WASAPI_INPUT_INDEX
    assert opened["extra_settings"].auto_convert is True


def test_audio_player_plays_through_wasapi_with_auto_convert() -> None:
    """Озвучка: Piper отдаёт 22.05 кГц, микшер вывода — 44.1 кГц."""
    from zere.voice.audio.audio_player import AudioPlayer

    played: list[dict] = []

    def fake_play(data: object, **kwargs: object) -> None:
        played.append(kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        wav_file = Path(tmp) / "voice.wav"

        with wave.open(str(wav_file), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(22050)
            writer.writeframes(np.zeros(2205, dtype=np.int16).tobytes())

        with fake_audio_environment(), \
             mock.patch.object(sd, "play", fake_play, create=True), \
             mock.patch.object(sd, "wait", lambda: None, create=True):
            AudioPlayer().play(str(wav_file), volume=1.0)

    assert played[-1]["samplerate"] == 22050
    assert played[-1]["device"] == WASAPI_OUTPUT_INDEX
    assert played[-1]["extra_settings"].auto_convert is True


# ── Живая проверка на реальном железе ────────────────────────────────


def _input_devices() -> list[dict]:
    return [d for d in sd.query_devices() if d["max_input_channels"] > 0]


def test_live_input_options_open_16k() -> None:
    """Живой тест: выбранный вариант действительно открывает 16 кГц.

    До правки здесь была ошибка «Invalid sample rate [PaErrorCode -9997]»:
    устройство WASAPI без auto_convert не принимает 16 кГц.

    Тест трогает **реальную звуковую карту** (микрофон пользователя), поэтому
    по умолчанию выключен: запускается только с `ZERE_LIVE_AUDIO=1`.
    Все остальные тесты файла работают на фейковом тракте и устройств не
    касаются.
    """
    if os.environ.get("ZERE_LIVE_AUDIO") != "1":
        print(
            "\n[пропущено] живой микрофон не трогаем "
            "(включить: ZERE_LIVE_AUDIO=1)"
        )
        return

    if not LIVE:
        print("\n[пропущено] живого PortAudio нет: sounddevice недоступен")
        return

    try:
        inputs = _input_devices()
    except Exception as ex:  # noqa: BLE001 — нет PortAudio/аудио-подсистемы
        print(f"\n[пропущено] PortAudio недоступен: {ex}")
        return

    if not inputs:
        print("\n[пропущено] в системе нет устройств ввода")
        return

    options = audio_device.input_options(16000, channels=1, dtype="int16")

    try:
        with sd.InputStream(
            samplerate=16000, channels=1, dtype="int16", **options
        ) as stream:
            data, _ = stream.read(1600)
    except Exception as ex:  # noqa: BLE001 — это и есть проверяемая регрессия
        raise AssertionError(
            f"16 кГц не открылись (options={options}): {ex}"
        ) from ex

    assert len(data) == 1600, "прочитано меньше сэмплов, чем запрошено"


def main() -> None:
    # Как в main.py: эмодзи в принтах рекордера иначе падают с UnicodeEncodeError
    # на cp866/cp1251 (перенаправленный вывод) и выглядят как сбой микрофона.
    configure_console_encoding()

    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов звуковых устройств")


if __name__ == "__main__":
    sys.exit(main())
