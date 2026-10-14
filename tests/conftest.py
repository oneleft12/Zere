"""Общая изоляция тестов от боевых данных ZERE.

Зачем: тесты поднимают панель и обработчики прямо в процессе pytest, а те
пишут ошибки в `logs/errors.log` (`log_error`) и создают файлы сессий
`logs/zere_*.log` (`LogService`). Без изоляции каждый прогон тестов
засорял боевой журнал: замер до правки — прогон
`tests/test_voice_mode.py tests/test_panel_api.py` дописывал 11 строк в
настоящий `logs/errors.log`, а полный прогон — около 40. Из-за этого
журнал перестаёт быть сигналом: половина строк в нём — шум тестов.
Хуже того, фикстура `seeded_logs` восстанавливает `errors.log` из снимка,
то есть могла затирать реальные записи, появившиеся во время теста.

Как: подменяем путь журнала на временный каталог — ровно тем же приёмом,
что уже применён к `config_path()` в `test_panel_api.py` и
`test_ai_providers.py` (секреты не должны утекать из песочницы в
настоящий `config/`). Патчится `zere.paths.LOGS_DIR`, потому что его
читают оба потребителя: `log_service.log_error()` через `logs_dir()` и
`GET /api/logs` в `zere/api/server.py` напрямую.

Внешний режим (`ZERE_PANEL_EXTERNAL=1`) не изолируется: там панель —
отдельный процесс со своим настоящим журналом, и подмена пути в процессе
тестов на него не влияет.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

# pytest может запускаться и как `pytest tests/` (без cwd в sys.path),
# поэтому корень репозитория добавляем сами — до импорта zere.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from zere import paths  # noqa: E402  (импорт после правки sys.path)

EXTERNAL = os.environ.get("ZERE_PANEL_EXTERNAL") == "1"


@pytest.fixture(scope="session", autouse=True)
def isolate_logs_dir() -> Iterator[None]:
    """Уводит журнал ZERE в tmp-каталог на время всего прогона.

    `LOGS_DIR` восстанавливается в finally, поэтому подмена не «протекает»
    в другие процессы и в повторные запуски в одном интерпретаторе.
    """
    if EXTERNAL:
        # Панель снаружи: логи у неё настоящие, подменять нечего.
        yield
        return

    original_logs_dir = paths.LOGS_DIR

    with tempfile.TemporaryDirectory(prefix="zere-test-logs-") as tmp:
        paths.LOGS_DIR = Path(tmp)
        try:
            yield
        finally:
            paths.LOGS_DIR = original_logs_dir
