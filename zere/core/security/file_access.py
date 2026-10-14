"""Права «только владелец» на файлы с секретами.

Зачем отдельный модуль: `config/ai.json` (ключ облачной модели) и
`config/panel.token` (токен панели) лежат вне git, но `os.chmod` на
Windows меняет лишь флаг «только чтение» и ACL **не трогает**. Файлы
наследовали права папки, а это `BUILTIN\\Пользователи: Read` и
`Authenticated Users: Modify` — то есть ключ мог прочитать и подменить
любой локальный пользователь, хотя `docs/AI_PROVIDERS.md` и `AGENTS.md`
обещают 0600. Проверено на боевом файле 14.10.2026 через Get-Acl.

Windows-аналог 0600 — не `chmod`, а `icacls`: снять наследование
(`/inheritance:r`) и выдать полный доступ только текущему пользователю
(`/grant:r`). POSIX-ветка остаётся обычным `chmod 0600`.

Ошибки прав намеренно проглатываются: недоступность `icacls` или чужой
файловой системы не должна ломать сохранение настроек — прежнее поведение
(`except OSError: pass`) сохранено.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

#: Сколько ждём icacls: утилита локальная и быстрая, зависание — сбой среды.
_ICACLS_TIMEOUT_SECONDS = 15


def _windows_principals() -> list[str]:
    """Кандидаты имени текущего пользователя для icacls, от точного к простому.

    Для доменной учётки нужно `ДОМЕН\\пользователь`, для локальной хватает
    имени. Для учётной записи Microsoft форма `ИМЯ_ПК\\пользователь` может
    не разрешиться — поэтому кандидатов несколько и берётся первый, который
    icacls принял.
    """
    user = os.environ.get("USERNAME", "").strip()
    domain = os.environ.get("USERDOMAIN", "").strip()

    candidates: list[str] = []

    if user and domain:
        candidates.append(f"{domain}\\{user}")
    if user:
        candidates.append(user)

    return candidates


def _icacls_path() -> Path:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return Path(system_root) / "System32" / "icacls.exe"


def _restrict_windows(path: Path) -> None:
    """Оставляет на файле полный доступ только текущему пользователю."""
    icacls = _icacls_path()

    if not icacls.is_file():
        return

    for principal in _windows_principals():
        try:
            result = subprocess.run(
                [
                    str(icacls),
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{principal}:F",
                ],
                check=False,
                capture_output=True,
                timeout=_ICACLS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            continue

        if result.returncode == 0:
            return


def restrict_to_owner(path: Path) -> None:
    """Сужает права файла до владельца (POSIX 0600 / Windows owner-only ACL)."""
    if os.name == "nt":
        _restrict_windows(path)
        return

    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
