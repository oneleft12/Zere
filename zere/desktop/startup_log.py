"""Журнал сбоев старта ZERE — тех, что иначе пропадают у pythonw.

`zere.exe` запускает приложение через `pythonw.exe`, а у него stdout и stderr
равны `None`. Подмена потоков (`zere.desktop.stdio.ensure_std_streams`) стоит
уже внутри `main()`, поэтому сбой импорта тяжёлых зависимостей (битый пакет,
несовместимая версия, нехватка DLL) не печатался никуда: лаунчер показывал
«ZERE завершился с ошибкой (код 1)», а в `logs\\desktop.log` была только
строка запуска.

Функция пишет traceback туда же, откуда окно лаунчера берёт конец журнала,
и никогда не бросает исключений: журнал не должен мешать падению.
"""

from __future__ import annotations

import traceback
from pathlib import Path

__all__ = ["DEFAULT_DESKTOP_LOG", "log_startup_failure"]

#: Корень установки: zere/desktop/startup_log.py → parents[2]
DEFAULT_DESKTOP_LOG = Path(__file__).resolve().parents[2] / "logs" / "desktop.log"

_HEADER = "\n=== СБОЙ ЗАПУСКА (импорт) ===\n"


def log_startup_failure(exc: BaseException, log_path: Path | None = None) -> Path | None:
    """Дописать traceback `exc` в журнал; вернуть путь или None при сбое."""
    target = Path(log_path) if log_path is not None else DEFAULT_DESKTOP_LOG
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(_HEADER)
            handle.write(
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            )
            handle.write("\n")
        return target
    except Exception:  # noqa: BLE001 — журнал не должен мешать падению
        return None
