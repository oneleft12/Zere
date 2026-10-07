"""Тесты C#-озвучки: мост к ZERE.Speaker и откат на Python.

Проверяем, что Python-редакция отдаёт озвучку (DSP + вывод звука) C#-хелперу,
корректно говорит с ним по протоколу `host`, умеет обрывать фразу и **не
ломает голос**, если хелпер не собран или упал (тогда озвучивает Python).

Звуковые устройства тесты не трогают: вместо хелпера запускается
`tests/fake_speaker.py` (журнал команд + имитация задержки, без вывода звука),
а проверка настоящего хелпера идёт в режиме `dry` — DSP считается, звук не
играется.

Запуск: python3 tests/test_csharp_speaker.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import types
import wave
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# audio_recorder/audio_player требуют sounddevice (PortAudio) — на безголосых
# машинах (CI) достаточно заглушки, как в tests/test_stt_engine.py.
try:
    import sounddevice  # noqa: F401
except Exception:  # noqa: BLE001 — ImportError или OSError от PortAudio
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

from zere import paths  # noqa: E402
from zere.voice.audio.csharp_speaker import CSharpSpeaker  # noqa: E402

FAKE_SPEAKER = ROOT / "tests" / "fake_speaker.py"


def _windows_path(path: Path) -> str:
    """Путь, который сможет открыть Windows-хелпер.

    Под WSL хелпер — это Windows-процесс (.exe). Пути /tmp/... и UNC
    (\\wsl.localhost\...) ему недоступны: NAudio не откроет файл, DSP молча
    вернёт исходный WAV. Поэтому путь переводится в C:\... через wslpath;
    на Windows строка остаётся как есть.
    """
    if not sys.platform.startswith("linux") or not str(path).startswith("/"):
        return str(path)

    try:
        converted = subprocess.run(
            ["wslpath", "-w", str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return str(path)

    if not converted:
        return str(path)

    # wslpath отдаёт UNC для путей вне /mnt/<диск>; подменяем его на букву диска,
    # иначе Windows-хелпер файл не увидит.
    unc = re.match(r"^\\\\(?:wsl\.localhost|wsl\$)\\[^\\]+\\mnt\\([a-zA-Z])\\(.*)$", converted)
    if unc:
        drive, rest = unc.group(1).upper(), unc.group(2)
        return drive + ":\\" + rest

    return converted


def _linux_path(path: str) -> Path:
    """Ответ хелпера (C:\\...) → путь WSL, чтобы проверить файл из теста."""
    if sys.platform.startswith("linux") and len(path) > 2 and path[1] == ":":
        try:
            converted = subprocess.run(
                ["wslpath", "-u", path],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if converted:
                return Path(converted)
        except (OSError, subprocess.CalledProcessError):
            return Path(path)

    return Path(path)


def fake_command(log: Path, *, delay: float = 0.05, **flags: bool) -> list[str]:
    """Команда запуска фейкового хелпера вместо exe."""
    command = [
        sys.executable,
        str(FAKE_SPEAKER),
        "--log",
        str(log),
        "--delay",
        str(delay),
    ]

    for name, enabled in flags.items():
        if enabled:
            command.append("--" + name.replace("_", "-"))

    return command


def write_wav(path: Path, seconds: float = 0.2, rate: int = 16000) -> Path:
    """Короткий WAV для тестов (тишина: устройства не нужны)."""
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(np.zeros(int(rate * seconds), dtype=np.int16).tobytes())

    return path


def read_log(log: Path) -> list[dict]:
    if not log.is_file():
        return []

    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ── Протокол ─────────────────────────────────────────────────────────


def test_speak_sends_request_and_waits_for_done() -> None:
    """`speak` уходит в хелпер целиком (wav/volume/process/rate) и блокирует до конца."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "commands.jsonl"
        wav = write_wav(Path(tmp) / "voice.wav")

        speaker = CSharpSpeaker(command=fake_command(log, delay=0.3))

        try:
            assert speaker.available() is True

            started = time.monotonic()
            played = speaker.speak(wav, volume=0.4, process=True, rate=22050)
            elapsed = time.monotonic() - started
        finally:
            speaker.close()

        assert played is True, "хелпер ответил done — озвучка считается выполненной"
        assert elapsed >= 0.3, f"speak должен ждать конца звучания, прошло {elapsed:.2f} с"

        requests = read_log(log)
        assert len(requests) == 1, f"ожидалась одна команда, пришло {len(requests)}"

        request = requests[0]
        assert request["cmd"] == "speak"
        assert request["wav"] == str(wav)
        assert request["volume"] == 0.4
        assert request["process"] is True
        assert request["rate"] == 22050


def test_stop_interrupts_playback() -> None:
    """`stop` доходит до хелпера и разблокирует ожидание озвучки."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "commands.jsonl"
        wav = write_wav(Path(tmp) / "voice.wav", seconds=30)

        speaker = CSharpSpeaker(command=fake_command(log, delay=5.0))
        result: list[bool] = []

        def run() -> None:
            result.append(speaker.speak(wav, volume=1.0))

        try:
            assert speaker.available() is True

            worker = threading.Thread(target=run, daemon=True)
            worker.start()

            time.sleep(0.6)  # хелпер уже получил speak и «играет»
            speaker.stop()
            worker.join(timeout=5.0)

            assert not worker.is_alive(), "stop не разбудил ожидание озвучки"
        finally:
            speaker.close()

        assert result == [True], "обрыв фразы — не ошибка озвучки"
        commands = [request["cmd"] for request in read_log(log)]
        assert "stop" in commands, f"хелпер не получил stop: {commands}"


def test_helper_crash_falls_back_to_python() -> None:
    """Крах хелпера не подвешивает озвучку: speak возвращает False (путь Python)."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "commands.jsonl"
        wav = write_wav(Path(tmp) / "voice.wav")

        speaker = CSharpSpeaker(command=fake_command(log, die_on_speak=True))

        try:
            started = time.monotonic()
            played = speaker.speak(wav, volume=1.0)
            elapsed = time.monotonic() - started

            assert played is False, "после краха хелпера озвучку берёт на себя Python"
            assert elapsed < 10.0, "ожидание не должно зависать"
            assert speaker.available() is False, "упавший хелпер больше не пытаемся поднять"
        finally:
            speaker.close()


def test_missing_helper_is_not_available() -> None:
    """Хелпер не собран — C#-озвучка не предлагается (голос остаётся на Python)."""
    with mock.patch.dict("os.environ", {"ZERE_SPEAKER_EXE": "/nope/ZERE.Speaker.exe"}):
        speaker = CSharpSpeaker()

        assert speaker.executable() is None
        assert speaker.available() is False

        with tempfile.TemporaryDirectory() as tmp:
            assert speaker.speak(write_wav(Path(tmp) / "voice.wav")) is False


def test_speaker_can_be_disabled_by_env() -> None:
    """ZERE_SPEAKER=python — принудительная озвучка на Python (отладка)."""
    with mock.patch.dict("os.environ", {"ZERE_SPEAKER": "python"}):
        speaker = CSharpSpeaker()

        assert speaker.executable() is None
        assert speaker.available() is False


# ── Настоящий хелпер (режим dry: звук не играется) ───────────────────


def test_real_helper_dry_run_processes_wav() -> None:
    """Собранный ZERE.Speaker: DSP на C# работает (проверка без вывода звука).

    Тест пропускается, если хелпер не собран.
    """
    executable = paths.speaker_executable()

    if executable is None:
        print("\n[пропущено] ZERE.Speaker не собран (нет exe — только Python-озвучка)")
        return

    # dir=ROOT: на WSL /tmp недоступен Windows-процессу (см. _windows_path).
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        wav = write_wav(Path(tmp) / "voice.wav", seconds=0.3, rate=22050)

        process = subprocess.Popen(
            [executable, "host"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

        def exchange(request: dict) -> dict:
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            return json.loads(process.stdout.readline())

        try:
            assert process.stdout is not None

            # Хелпер сам представляется при старте — забираем ready.
            started = json.loads(process.stdout.readline())
            assert started.get("event") == "ready", started
            assert started.get("version") == "1", "версия протокола хелпера"

            assert exchange({"cmd": "ping"}).get("event") == "pong"

            reply = exchange({
                "cmd": "speak",
                "wav": _windows_path(wav),
                "volume": 1.0,
                "process": True,
                "rate": 44100,
                "dry": True,  # звук не выводим: устройства не трогаем
            })
            assert reply.get("event") == "done", reply
            assert reply.get("played") is False

            processed = _linux_path(reply["file"])
            assert processed.is_file(), "C#-DSP должен был создать обработанный WAV"
            assert processed.name.startswith("processed_")

            with wave.open(str(processed), "rb") as reader:
                assert reader.getframerate() == 44100, "ресемплинг под частоту устройства"

            processed.unlink()
        finally:
            try:
                exchange({"cmd": "quit"})
            except Exception:  # noqa: BLE001 — процесс мог уже выйти
                pass

            process.wait(timeout=10)


# ── Подключение к VoiceManager (озвучка, файлы, откат) ───────────────


class FakeSpeaker:
    """Замена CSharpSpeaker: пишет вызовы, отвечает заданным результатом."""

    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[dict] = []
        self.stopped = 0
        self.closed = 0

    def available(self) -> bool:
        return True

    def speak(self, wav_file: str, **kwargs: object) -> bool:
        self.calls.append({"wav": wav_file, **kwargs})
        return self.result

    def stop(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        self.closed += 1


def _voice_manager_with(speaker: FakeSpeaker, chattts_wav: Path):
    """VoiceManager с фейковым ChatTTS и подменённым хелпером (без устройств)."""
    from zere.voice.voice_manager import VoiceManager

    manager = VoiceManager()
    manager._speaker = speaker  # noqa: SLF001 — подмена тракта озвучки в тесте
    manager._chattts = mock.Mock()  # noqa: SLF001
    manager._chattts.is_loaded = True
    manager._chattts.speak.return_value = str(chattts_wav)
    return manager


def test_voice_manager_speaks_through_csharp() -> None:
    """Основной путь: синтез ChatTTS → озвучка C# (DSP и вывод), Python не играет."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = write_wav(Path(tmp) / "chattts.wav", rate=24000)
        speaker = FakeSpeaker(result=True)
        manager = _voice_manager_with(speaker, wav)
        manager._player = mock.Mock()  # noqa: SLF001

        try:
            manager.speak("проверка озвучки")
        finally:
            manager.close()

        assert len(speaker.calls) == 1, "озвучка должна уйти в C#-хелпер"
        call = speaker.calls[0]
        assert call["wav"] == str(wav)
        assert call["volume"] == manager.config.volume
        assert call["process"] == manager.config.audio_processing
        assert call["rate"] > 0, "частота устройства передаётся для ресемплинга"

        manager._player.play.assert_not_called()  # noqa: SLF001
        assert not wav.exists(), "временный WAV синтеза удаляется после озвучки"


def test_voice_manager_falls_back_to_python_player() -> None:
    """Хелпер не сработал — озвучка идёт прежним путём (sounddevice)."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = write_wav(Path(tmp) / "chattts.wav", rate=24000)
        speaker = FakeSpeaker(result=False)
        manager = _voice_manager_with(speaker, wav)
        manager._player = mock.Mock()  # noqa: SLF001

        with mock.patch(
            "zere.voice.voice_manager.AudioProcessor.process",
            side_effect=lambda path, rate: path,
        ):
            try:
                manager.speak("проверка отката")
            finally:
                manager.close()

        assert len(speaker.calls) == 1, "сначала пробуем C#"
        manager._player.play.assert_called_once()  # noqa: SLF001


def test_stop_speaking_stops_both_paths() -> None:
    """StopSpeaking гасит и C#-хелпер, и Python-плеер."""
    manager = _voice_manager_with(FakeSpeaker(), Path("unused.wav"))
    manager._player = mock.Mock()  # noqa: SLF001

    manager.stop_speaking()

    assert manager._speaker.stopped == 1  # noqa: SLF001
    manager._player.stop.assert_called_once()  # noqa: SLF001


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов C#-озвучки")


if __name__ == "__main__":
    sys.exit(main())
