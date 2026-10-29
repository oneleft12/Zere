"""Тесты ZereEngine: сохранение истории, ответы и устойчивость к сбоям.

До этих тестов `engine.py` имел покрытие 0 %: панель и консоль вызывают
`process()`, но ни один тест не проверял, что история сохраняется и что сбой
обработчика не уносит приложение.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from zere.core.engine import ZereEngine


class FakePipeline:
    def __init__(self, answer: Optional[str] = "ответ", error: Optional[Exception] = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[str] = []

    def handle(self, message: str) -> Optional[str]:
        self.calls.append(message)
        if self.error is not None:
            raise self.error
        return self.answer


class FakeExtractor:
    def __init__(self, error: Optional[Exception] = None) -> None:
        self.calls: list[str] = []
        self.error = error

    def try_extract(self, message: str) -> None:
        self.calls.append(message)
        if self.error is not None:
            raise self.error


class FakeConversations:
    def __init__(self, error: Optional[Exception] = None) -> None:
        self.saved: list[tuple[str, str]] = []
        self.error = error

    def save(self, user_message: str, answer: str) -> None:
        if self.error is not None:
            raise self.error
        self.saved.append((user_message, answer))


def make_engine(pipeline=None, extractor=None, conversations=None) -> tuple[ZereEngine, FakePipeline, FakeExtractor, FakeConversations]:
    pipeline = pipeline or FakePipeline()
    extractor = extractor or FakeExtractor()
    conversations = conversations or FakeConversations()
    engine = ZereEngine(pipeline, extractor, None, conversations)  # type: ignore[arg-type]
    return engine, pipeline, extractor, conversations


def test_process_returns_pipeline_answer_and_saves_history() -> None:
    engine, pipeline, extractor, conversations = make_engine()

    assert engine.process("привет") == "ответ"
    assert pipeline.calls == ["привет"]
    assert extractor.calls == ["привет"]
    assert conversations.saved == [("привет", "ответ")]


def test_unrecognized_command_is_reported_and_saved() -> None:
    engine, _, _, conversations = make_engine(pipeline=FakePipeline(answer=None))

    assert engine.process("что-то") == "Команда не распознана."
    assert conversations.saved == [("что-то", "Команда не распознана.")]


def test_pipeline_error_does_not_propagate() -> None:
    engine, _, _, conversations = make_engine(
        pipeline=FakePipeline(error=RuntimeError("сломалось"))
    )

    answer = engine.process("привет")

    assert answer.startswith("Произошла ошибка: сломалось")
    # Ошибочный ход не пишется в историю: диалог остаётся чистым.
    assert conversations.saved == []


def test_extractor_error_does_not_propagate() -> None:
    engine, pipeline, _, _ = make_engine(extractor=FakeExtractor(error=ValueError("плохой факт")))

    answer = engine.process("запомни что-нибудь")

    assert answer.startswith("Произошла ошибка: плохой факт")
    assert pipeline.calls == []


def test_history_failure_does_not_break_answer() -> None:
    engine, _, _, _ = make_engine(conversations=FakeConversations(error=OSError("диск занят")))

    assert engine.process("привет") == "ответ"


def test_plugin_manager_is_exposed() -> None:
    marker = object()
    engine = ZereEngine(FakePipeline(), FakeExtractor(), marker, FakeConversations())  # type: ignore[arg-type]

    assert engine.plugin_manager is marker
    assert engine.pipeline is not None


def test_process_is_serialized_between_threads() -> None:
    """Две одновременные реплики не должны исполняться параллельно."""
    state = {"active": 0, "max": 0}

    class SlowPipeline:
        def handle(self, message: str) -> str:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            time.sleep(0.05)
            state["active"] -= 1
            return message

    engine = ZereEngine(SlowPipeline(), FakeExtractor(), None, FakeConversations())  # type: ignore[arg-type]
    threads = [
        threading.Thread(target=engine.process, args=(f"m{index}",))
        for index in range(4)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert state["max"] == 1
