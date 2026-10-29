"""Ротация журналов: старые сессии не копятся, errors.log не растёт вечно."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from zere import paths
from zere.core.logging import log_service as module


@pytest.fixture
def logs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path)
    return tmp_path


def _touch(folder: Path, name: str, age_seconds: float) -> Path:
    path = folder / name
    path.write_text("x\n", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def test_old_session_logs_are_pruned(logs_dir: Path) -> None:
    for index in range(30):
        _touch(logs_dir, f"zere_2026-01-{index + 1:02d}_00-00-00.log", 10_000 - index)

    module.LogService()

    remaining = sorted(logs_dir.glob("zere_*.log"))
    assert len(remaining) == module._MAX_SESSION_LOG_FILES - 1
    # Остались самые свежие: самый старый удалён.
    assert not (logs_dir / "zere_2026-01-01_00-00-00.log").exists()


def test_unrelated_logs_are_kept(logs_dir: Path) -> None:
    _touch(logs_dir, "desktop.log", 1)
    _touch(logs_dir, "errors.log", 1)
    for index in range(25):
        _touch(logs_dir, f"zere_{index:02d}.log", 1000 - index)

    module.LogService()

    assert (logs_dir / "desktop.log").exists()
    assert (logs_dir / "errors.log").exists()


def test_errors_log_rotates_at_limit(logs_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_ERRORS_MAX_BYTES", 100)
    errors = logs_dir / "errors.log"
    errors.write_text("x" * 150, encoding="utf-8")

    module.log_error("Test", "ошибка после ротации")

    assert (logs_dir / "errors.log.1").exists()
    text = errors.read_text(encoding="utf-8")
    assert "ошибка после ротации" in text
    assert len(text) < 150


def test_old_error_archive_is_replaced(logs_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_ERRORS_MAX_BYTES", 10)
    (logs_dir / "errors.log").write_text("старое", encoding="utf-8")
    (logs_dir / "errors.log.1").write_text("ещё старее", encoding="utf-8")

    module.log_error("Test", "новое")

    assert (logs_dir / "errors.log.1").read_text(encoding="utf-8").startswith("старое")
