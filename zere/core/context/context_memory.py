"""Порт ZERE.Core/Context/ContextMemory.cs."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import List, Optional

from zere.core.context.context_item import ContextItem
from zere.core.context.context_type import ContextType


class ContextMemory:
    def __init__(self) -> None:
        self._items: List[ContextItem] = []
        self._lock = threading.Lock()

    def remember(self, type_: ContextType, name: str, value: str) -> None:
        with self._lock:
            self._items.insert(
                0,
                ContextItem(
                    type=type_,
                    name=name,
                    value=value,
                    time=datetime.now(),  # DateTime.Now
                ),
            )

            if len(self._items) > 10:
                del self._items[len(self._items) - 1]

    def last(self, type_: ContextType) -> Optional[ContextItem]:
        with self._lock:
            for item in self._items:
                if item.type == type_:
                    return item
            return None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def get_all(self) -> List[ContextItem]:
        with self._lock:
            return list(self._items)
