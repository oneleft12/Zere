"""Информация о процессе (порт Windows/ProcessInfo.cs)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProcessInfo:
    id: int = 0
    name: str = ""
    memory_mb: float = 0.0
    responding: bool = False
