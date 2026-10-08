"""CLI роутера: `python3 -m zere.core.routing "закрой дискорд"`.

Отдельный вход нужен, чтобы `-m` не переисполнял модуль (иначе Python
предупреждает, что `zere.core.routing.jev_router` уже импортирован пакетом).
"""

from __future__ import annotations

from zere.core.routing.jev_router import main

if __name__ == "__main__":
    raise SystemExit(main())
