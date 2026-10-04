"""Тесты основного STT-движка GigaAM (отчёт docs/STT_ENGINE_RESEARCH.md, §5).

Проверяют согласованность констант (Python-сервис ↔ установщик ↔ C#),
значения по умолчанию конфигураций, роутинг gigaam→whisper с откатом
и (по возможности) живое распознавание.

Запуск: python3 tests/test_stt_engine.py
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Эталон (источник: GitHub release asr-models, SHA-256 вычислен при скачивании)
GIGAAM_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16.tar.bz2"
)
GIGAAM_SHA256 = "f9620a0099019c6afcee26525ef9ed3297fa50dd5691c1902af0c948fc1a470b"
GIGAAM_SIZE = 170197019
GIGAAM_DIR_NAME = "sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16"


def test_constants_match_installer_and_csharp() -> None:
    """Один URL/SHA-256/размер в Python-сервисе, install.ps1 и GigaAmService.cs."""
    from jarvis.voice.sherpa import gigaam_service as gs

    assert gs.MODEL_URL == GIGAAM_URL, "MODEL_URL не совпадает с эталоном"
    assert gs.MODEL_SHA256 == GIGAAM_SHA256, "MODEL_SHA256 не совпадает с эталоном"
    assert gs.MODEL_SIZE_BYTES == GIGAAM_SIZE, "MODEL_SIZE_BYTES не совпадает с эталоном"
    assert gs.MODEL_DIR_NAME == GIGAAM_DIR_NAME, "MODEL_DIR_NAME не совпадает с эталоном"

    ps1 = (ROOT / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
    block_m = re.search(r"GigaAm\s*=\s*@{(.*?)}", ps1, re.S)
    assert block_m, "install.ps1: нет артефакта GigaAm"
    block = block_m.group(1)
    assert GIGAAM_URL in block, "install.ps1: другой Url GigaAM"
    sha_m = re.search(r"Sha256\s*=\s*'([0-9a-f]{64})'", block)
    size_m = re.search(r"Size\s*=\s*(\d+)", block)
    assert sha_m and sha_m.group(1) == GIGAAM_SHA256, "install.ps1: другой Sha256 GigaAM"
    assert size_m and int(size_m.group(1)) == GIGAAM_SIZE, "install.ps1: другой Size GigaAM"

    cs = (ROOT / "JARVIS.Voice" / "Sherpa" / "GigaAmService.cs").read_text(encoding="utf-8")
    assert GIGAAM_SHA256 in cs, "GigaAmService.cs: другой Sha256"
    assert GIGAAM_DIR_NAME in cs, "GigaAmService.cs: другое имя папки модели"
    assert re.search(r"ModelSizeBytes\s*=\s*170197019", cs), (
        "GigaAmService.cs: другой размер архива"
    )


def test_config_defaults_gigaam() -> None:
    """stt_engine по умолчанию — gigaam во всех точках конфигурации."""
    from jarvis.core.configuration.jarvis_config import JarvisConfig
    from jarvis.voice.voice_config import VoiceConfig

    assert JarvisConfig().stt_engine == "gigaam"
    assert VoiceConfig().stt_engine == "gigaam"

    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    assert cfg.get("sttEngine") == "gigaam", "config/config.json: нет sttEngine"

    # PascalCase-алиас нужен, иначе save() выкинет ключ
    assert JarvisConfig()._PASCAL_ALIASES.get("SttEngine") == "stt_engine"

    cs = (ROOT / "JARVIS.Core" / "Configuration" / "JarvisConfig.cs").read_text(
        encoding="utf-8"
    )
    assert re.search(r'SttEngine\s*\{\s*get;\s*set;\s*\}\s*=\s*"gigaam"', cs), (
        "C# JarvisConfig.SttEngine по умолчанию не gigaam"
    )


def test_csharp_routing_wiring() -> None:
    """C#: маршрутизация STT включена (ISttService, ActiveStt, откат, PreloadStt)."""
    iface = (ROOT / "JARVIS.Voice" / "ISttService.cs").read_text(encoding="utf-8")
    assert "interface ISttService" in iface
    assert "TranscribeAsync" in iface

    vm = (ROOT / "JARVIS.Voice" / "VoiceManager.cs").read_text(encoding="utf-8")
    assert "ISttService ActiveStt" in vm, "нет маршрута ActiveStt"
    assert "TranscribeSttAsync" in vm, "нет отката STT (TranscribeSttAsync)"
    assert "void PreloadStt(" in vm, "нет PreloadStt"
    assert "_gigaam.Dispose()" in vm, "GigaAmService не освобождается в Dispose"
    # Wake word остаётся на Whisper (§5.3 отчёта)
    assert "WakeWordDetector(" in vm and "_whisper" in vm.split("WakeWordDetector(")[1][:200]

    program = (ROOT / "JARVIS.App" / "Program.cs").read_text(encoding="utf-8")
    assert "ConfigureStt" in program and "PreloadStt()" in program

    csproj = (ROOT / "JARVIS.Voice" / "JARVIS.Voice.csproj").read_text(encoding="utf-8")
    assert "org.k2fsa.sherpa.onnx" in csproj, "NuGet sherpa-onnx не подключён"


def test_python_routing_and_fallback() -> None:
    """Python: выбор движка gigaam→whisper и откат при сбое gigaam."""
    # audio_player/audio_recorder требуют sounddevice (PortAudio) — на безголосых
    # машинах (CI) подменяем модуль, импорту достаточно заглушки.
    try:
        import sounddevice  # noqa: F401
    except Exception:  # noqa: BLE001 — ImportError или OSError от PortAudio
        sys.modules["sounddevice"] = types.ModuleType("sounddevice")

    from jarvis.voice.voice_manager import VoiceManager

    vm = VoiceManager()
    giga, whisper = vm._gigaam, vm._whisper

    # 1. gigaam запрошен и модель стоит → активен gigaam
    vm.config.stt_engine = "gigaam"
    with mock.patch.object(giga, "is_installed", return_value=True), \
         mock.patch.object(whisper, "is_installed", return_value=True):
        assert vm._active_stt is giga
        assert vm.is_voice_available is True

    # 2. gigaam запрошен, но модели нет → whisper
    with mock.patch.object(giga, "is_installed", return_value=False), \
         mock.patch.object(whisper, "is_installed", return_value=True):
        assert vm._active_stt is whisper

    # 3. явный whisper → whisper
    vm.config.stt_engine = "whisper"
    with mock.patch.object(giga, "is_installed", return_value=True), \
         mock.patch.object(whisper, "is_installed", return_value=True):
        assert vm._active_stt is whisper
    vm.config.stt_engine = "gigaam"

    # 4. ничего не установлено → последний вариант (gigaam)
    with mock.patch.object(giga, "is_installed", return_value=False), \
         mock.patch.object(whisper, "is_installed", return_value=False):
        assert vm._active_stt is giga
        assert vm.is_voice_available is False

    # 5. сбой gigaam при распознавании → откат на whisper
    with mock.patch.object(giga, "is_installed", return_value=True), \
         mock.patch.object(giga, "transcribe", side_effect=RuntimeError("битая модель")), \
         mock.patch.object(whisper, "is_installed", return_value=True), \
         mock.patch.object(whisper, "transcribe", return_value="текст с whisper") as w:
        assert vm._transcribe_stt("some.wav") == "текст с whisper"
        w.assert_called_once()

    # 6. сбой gigaam без whisper → ошибка не замалчивается
    with mock.patch.object(giga, "is_installed", return_value=True), \
         mock.patch.object(giga, "transcribe", side_effect=RuntimeError("boom")), \
         mock.patch.object(whisper, "is_installed", return_value=False):
        try:
            vm._transcribe_stt("some.wav")
        except RuntimeError:
            pass
        else:
            raise AssertionError("ошибка STT без whisper должна всплыть")


def test_panel_contract_stt_engine() -> None:
    """OpenAPI: sttEngine известен, но необязателен; сервер его валидирует."""
    yaml_text = (ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8")
    cfg_m = re.search(r"    Config:\n(.*?)(?=\n    \w)", yaml_text, re.S)
    assert cfg_m, "нет схемы Config"
    cfg_block = cfg_m.group(1)
    assert re.search(r"sttEngine:\s*\n\s*type: string\s*\n\s*enum: \[gigaam, whisper\]", cfg_block)
    required_m = re.search(r"required:\n((?:\s+- \w+\n)+)", cfg_block)
    assert required_m and "sttEngine" not in required_m.group(1), (
        "sttEngine не должен быть обязательным"
    )

    from jarvis.api.server import _validate_config_payload
    from jarvis.core.configuration.jarvis_config import JarvisConfig

    payload = JarvisConfig().to_camel_dict()
    assert payload.get("sttEngine") == "gigaam"
    assert _validate_config_payload(payload) is None, "валидный payload отклонён"

    old_client = {k: v for k, v in payload.items() if k != "sttEngine"}
    assert _validate_config_payload(old_client) is None, (
        "клиент без sttEngine должен проходить (необязательный ключ)"
    )

    bad = dict(payload)
    bad["sttEngine"] = "nemo"
    err = _validate_config_payload(bad)
    assert err and "sttEngine" in err, "значение вне enum должно отклоняться"


def test_model_files_and_live_decode() -> None:
    """Если модель GigaAM распакована — она полная; живое распознавание работает."""
    model_dir = ROOT / "JARVIS.Voice" / "Models" / GIGAAM_DIR_NAME
    if not model_dir.is_dir():
        print("  (модель GigaAM не распакована — скачается при установке/первом старте)")
        return

    for name in ("encoder.int8.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"):
        assert (model_dir / name).is_file(), f"модель неполная: нет {name}"

    wav = model_dir / "test_wavs" / "example.wav"
    if not wav.is_file():
        print("  (test_wavs/example.wav нет — живой прогон пропущен)")
        return

    from jarvis.voice.sherpa.gigaam_service import GigaamService

    svc = GigaamService()
    if not svc.is_installed():
        print("  (sherpa-onnx не установлен — живой прогон пропущен)")
        return

    text = svc.transcribe(str(wav))
    assert text.strip(), "GigaAM вернул пустой текст"
    assert any(c.isalpha() and "Ѐ" <= c <= "ӿ" for c in text), (
        f"ожидался русский текст, получено: {text!r}"
    )


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов STT-движка")


if __name__ == "__main__":
    sys.exit(main())
