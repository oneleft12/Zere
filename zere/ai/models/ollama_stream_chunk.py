"""Порт ZERE.AI/Models/OllamaStreamChunk.cs — DTO строки NDJSON-стрима Ollama."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class OllamaStreamChunk:
    """Свойства именованы 1:1 как в C# (response, done) — так же называются поля в JSON."""

    response: Optional[str] = None
    done: bool = False
