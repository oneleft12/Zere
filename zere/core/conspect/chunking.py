"""Чанкование материала под жёсткое окно модели.

Почему это отдельный модуль, а не «обрезать текст»: `num_ctx = 2048` в
`OllamaClient` (`zere/ai/ollama_client.py`) — окно всей модели, включая
system-промпт, инструкцию и ответ. Часовая лекция (~40 000 символов) туда
не входит: llama.cpp отбросил бы начало и модель увидела бы хвост, а
пользователь получил бы «конспект» последних двух минут.

Поэтому текст режется по границам абзацев, а внутри слишком крупного
абзаца — по границам предложений. Части перекрываются: мысль на стыке
двух частей остаётся хотя бы в одной.

Оценка токенов нарочно пессимистичная (2.5 символа на токен для русского
текста): лучше сделать на часть больше, чем упереться в окно и потерять
конец части.
"""

from __future__ import annotations

import re
from typing import Iterable, List

#: Символов на токен для русского текста (Qwen3-подобные токенизаторы).
#: Занижено осознанно — оценка должна быть сверху, а не снизу.
CHARS_PER_TOKEN = 2.5

#: Параграфы: одна или несколько пустых строк.
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")

#: Конец предложения: знак + пробел (не трогаем «3.5» и «12.05.2026»).
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def estimate_tokens(text: str) -> int:
    """Оценка числа токенов (сверху) — по символам, без токенизатора."""
    if not text:
        return 0

    return int(len(text) / CHARS_PER_TOKEN) + 1


def split_sentences(text: str) -> List[str]:
    """Делит текст на предложения, сохраняя разделители внутри них."""
    parts = [part for part in _SENTENCE_SPLIT.split(text) if part.strip()]

    return parts or ([text] if text.strip() else [])


def _split_long_block(block: str, chunk_chars: int) -> List[str]:
    """Режет блок, который сам больше части: сначала предложения, затем жёстко."""
    pieces: List[str] = []
    buffer = ""

    for sentence in split_sentences(block):
        # Само предложение больше части (например, список без точек) —
        # режем его посимвольно, иначе часть никогда не станет короткой.
        if len(sentence) > chunk_chars:
            if buffer.strip():
                pieces.append(buffer.strip())
                buffer = ""

            pieces.extend(
                sentence[offset : offset + chunk_chars]
                for offset in range(0, len(sentence), chunk_chars)
            )
            continue

        if buffer and len(buffer) + 1 + len(sentence) > chunk_chars:
            pieces.append(buffer.strip())
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip() if buffer else sentence

    if buffer.strip():
        pieces.append(buffer.strip())

    return pieces


def _tail(text: str, overlap: int) -> str:
    """Хвост предыдущей части для перекрытия — по границе слова."""
    if overlap <= 0 or not text:
        return ""

    tail = text[-overlap:]
    space = tail.find(" ")

    return tail[space + 1 :] if space != -1 and space + 1 < len(tail) else tail


def chunk_text(text: str, chunk_chars: int, overlap: int = 0) -> List[str]:
    """Делит текст на части не длиннее `chunk_chars` (плюс перекрытие).

    Пустой текст или неположительный размер части → пустой список: вызывающий
    сам решает, что это за ошибка («источник пуст»), а не получает одну
    пустую часть.
    """
    if not text or not text.strip() or chunk_chars <= 0:
        return []

    if overlap >= chunk_chars:
        overlap = max(0, chunk_chars // 4)

    blocks: List[str] = []

    for paragraph in _PARAGRAPH_SPLIT.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) <= chunk_chars:
            blocks.append(paragraph)
        else:
            blocks.extend(_split_long_block(paragraph, chunk_chars))

    chunks: List[str] = []
    current = ""

    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block

        if current and len(candidate) > chunk_chars:
            chunks.append(current)
            prefix = _tail(current, overlap)
            current = f"{prefix}\n\n{block}" if prefix else block
        else:
            current = candidate

        # Перекрытие может сделать часть длиннее лимита — тогда режем её
        # ещё раз, чтобы каждая часть гарантированно влезала в окно.
        while len(current) > chunk_chars + overlap:
            chunks.append(current[:chunk_chars])
            current = current[chunk_chars - overlap :]

    if current.strip():
        chunks.append(current)

    return [chunk.strip() for chunk in chunks if chunk.strip()]


def chunk_stats(chunks: Iterable[str]) -> dict[str, int]:
    """Сводка по частям — для ответа пользователю и журнала."""
    items = list(chunks)

    return {
        "parts": len(items),
        "chars": sum(len(item) for item in items),
        "tokens": sum(estimate_tokens(item) for item in items),
        "maxPartTokens": max((estimate_tokens(item) for item in items), default=0),
    }


__all__ = [
    "CHARS_PER_TOKEN",
    "chunk_stats",
    "chunk_text",
    "estimate_tokens",
    "split_sentences",
]
