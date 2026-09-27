"""Токен локальной панели (docs/GUI_DEVELOPMENT_PLAN.md §6).

32 байта в hex; создаётся при первом старте, хранится в config/panel.token
(файл попадает в .gitignore — токен не должен быть в репозитории).
"""

from __future__ import annotations

import secrets
from pathlib import Path

from jarvis import paths

TOKEN_FILE_NAME = "panel.token"
_TOKEN_LENGTH = 64  # 32 байта в hex


def token_path() -> Path:
    return paths.config_path().parent / TOKEN_FILE_NAME


def load_or_create_token() -> str:
    """Возвращает токен панели, создавая файл при первом обращении."""
    path = token_path()

    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) == _TOKEN_LENGTH and all(c in "0123456789abcdef" for c in token):
            return token

    token = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")

    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows не поддерживает POSIX-права — не критично

    return token
