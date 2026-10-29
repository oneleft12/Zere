"""Регрессия: sherpa-onnx и системный onnxruntime.dll (Windows 11).

На Windows 11 в `C:\\Windows\\System32` лежит ONNX Runtime 1.17.1 (Windows ML).
sherpa-onnx собран против 1.28 и при инициализации GigaAM просит API 28:
Windows отдаёт системную 1.17.1, печатает «requested API version [28]…» и
**падает с access violation** в `_sherpa_onnx*.pyd`. В приложении это
выглядело как «zere.exe запустился и молча умер»; в консоли — исчезновение
процесса после предзагрузки STT.

Лечение в коде: `preload_bundled_onnxruntime()` грузит копию ORT из пакета
sherpa по полному пути до `import sherpa_onnx`/`import onnxruntime`.

Тесты не требуют ни sherpa, ни onnxruntime: проверяют порядок «сначала
предзагрузка, потом импорт» и безопасность вызова без пакета.

Запуск: python tests/test_onnx_preload.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zere.voice.sherpa import gigaam_service  # noqa: E402


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self) -> bool:
        self.calls.append("preload")
        return True


def test_sherpa_import_preloads_ort_first() -> None:
    """Перед `import sherpa_onnx` обязательно грузится своя копия ORT."""
    recorder = _Recorder()
    original_preload = gigaam_service.preload_bundled_onnxruntime
    original_import = sys.modules.get("sherpa_onnx")

    fake_module = types.ModuleType("sherpa_onnx")
    sys.modules["sherpa_onnx"] = fake_module
    gigaam_service.preload_bundled_onnxruntime = recorder  # type: ignore[assignment]

    try:
        result = gigaam_service._try_import_sherpa()  # noqa: SLF001 — проверяем порядок
        assert result is fake_module
        assert recorder.calls == ["preload"], "ORT не загружен до импорта sherpa"
    finally:
        gigaam_service.preload_bundled_onnxruntime = original_preload  # type: ignore[assignment]
        if original_import is None:
            sys.modules.pop("sherpa_onnx", None)
        else:
            sys.modules["sherpa_onnx"] = original_import


def test_preload_is_safe_without_sherpa() -> None:
    """Без пакета sherpa предзагрузка не бросает и не мешает старту."""
    original = sys.modules.pop("sherpa_onnx", None)

    try:
        assert gigaam_service.preload_bundled_onnxruntime() in (True, False)
    finally:
        if original is not None:
            sys.modules["sherpa_onnx"] = original


def test_preload_is_idempotent() -> None:
    """Повторный вызов не грузит библиотеку заново (кэш в модуле)."""
    sentinel: Any = object()
    original = gigaam_service._PRELOADED_ONNX_RUNTIME  # noqa: SLF001 — внутренний кэш
    gigaam_service._PRELOADED_ONNX_RUNTIME = sentinel  # noqa: SLF001

    try:
        assert gigaam_service.preload_bundled_onnxruntime() is True
        assert gigaam_service._PRELOADED_ONNX_RUNTIME is sentinel  # noqa: SLF001
    finally:
        gigaam_service._PRELOADED_ONNX_RUNTIME = original  # noqa: SLF001


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов предзагрузки onnxruntime")


if __name__ == "__main__":
    sys.exit(main())
