"""Профили браузеров для Playwright MCP.

Playwright MCP умеет два способа выбрать браузер:

- `--browser <channel>` — канал (`chrome`, `msedge`, `chromium`, `firefox`,
  `webkit`). Для `chrome` нужен установленный Chrome либо
  `npx playwright install chrome`;
- `--executable-path <путь>` — любой Chromium-совместимый исполняемый файл.
  Именно так подключается **Opera GX**: своего канала у Playwright для него
  нет, но как Chromium он управляется штатно.

Проверено на реальной Windows: Edge (канал и путь) — 1.2 с, Opera GX (путь) —
8.1 с, оба отдают 25 инструментов и успешно переходят на страницу.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class BrowserProfile:
    """Описание браузера, которым умеет управлять Playwright MCP."""

    id: str
    label: str
    #: Значение для `--browser` (канал Playwright). None — только путь.
    channel: Optional[str] = None
    #: Стандартные пути к исполняемому файлу, по порядку поиска.
    executable_paths: tuple[str, ...] = ()
    #: Что сказать пользователю, если браузер не найден.
    install_hint: str = ""
    #: Синонимы для команды «браузер выбери …».
    aliases: tuple[str, ...] = ()

    def matches(self, name: str) -> bool:
        normalized = normalize_name(name)

        return normalized in {normalize_name(self.id), normalize_name(self.label), *(
            normalize_name(alias) for alias in self.aliases
        )}


def normalize_name(name: str) -> str:
    """Приводит имя браузера к сравнимому виду: «Opera GX» → «operagx»."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


_ENV_PATTERN = re.compile(r"%([^%]+)%")


def _expand(path: str) -> str:
    """Разворачивает `%LOCALAPPDATA%` и подобное в путь — без учёта регистра.

    Регистр здесь принципиален: Windows хранит имена переменных в верхнем
    регистре (`PROGRAMFILES(X86)`), а в путях профилей они записаны как
    `%ProgramFiles(x86)%`. Сравнение «в лоб» не срабатывало, и Edge ошибочно
    помечался отсутствующим, хотя он есть на любой Windows.

    Своя реализация, а не `os.path.expandvars`: на Linux (где идут тесты)
    последняя `%VAR%` не трогает вообще.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)

        for key, value in os.environ.items():
            if key.lower() == name.lower():
                return value

        return match.group(0)

    return _ENV_PATTERN.sub(replace, path)


BROWSER_PROFILES: tuple[BrowserProfile, ...] = (
    BrowserProfile(
        id="edge",
        label="Microsoft Edge",
        channel="msedge",
        executable_paths=(
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        ),
        aliases=("msedge", "эдж", "едж"),
    ),
    BrowserProfile(
        id="chrome",
        label="Google Chrome",
        channel="chrome",
        executable_paths=(
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        ),
        install_hint=(
            "Chrome не найден. Установите его или выполните "
            "«npx playwright install chrome»."
        ),
        aliases=("google chrome", "гугл хром", "хром"),
    ),
    BrowserProfile(
        id="opera-gx",
        label="Opera GX",
        # Канала у Playwright нет — только явный путь к opera.exe.
        channel=None,
        executable_paths=(
            r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe",
            r"%ProgramFiles%\Opera GX\opera.exe",
            r"%ProgramFiles(x86)%\Opera GX\opera.exe",
        ),
        install_hint="Opera GX не найден. Установите его или укажите browserPath в config/mcp.json.",
        aliases=("opera", "opera gx", "опера", "опера gx", "gx"),
    ),
    BrowserProfile(
        id="chromium",
        label="Chromium (от Playwright)",
        channel="chromium",
        install_hint="Chromium не установлен: выполните «npx playwright install chromium».",
        aliases=("хромиум",),
    ),
)

#: Браузер по умолчанию: Edge есть на любой Windows, скачивать ничего не нужно.
DEFAULT_BROWSER_ID = "edge"


def find_profile(name: str) -> Optional[BrowserProfile]:
    """Профиль по имени или синониму («edge», «opera gx», «хром»)."""
    for profile in BROWSER_PROFILES:
        if profile.matches(name):
            return profile

    return None


def profile_by_id(browser_id: str) -> Optional[BrowserProfile]:
    normalized = normalize_name(browser_id)

    for profile in BROWSER_PROFILES:
        if normalize_name(profile.id) == normalized:
            return profile

    return None


def resolve_executable(profile: BrowserProfile) -> Optional[str]:
    """Первый существующий исполняемый файл профиля (или None)."""
    for candidate in profile.executable_paths:
        path = _expand(candidate)

        if Path(path).is_file():
            return path

    return None


def is_available(profile: BrowserProfile) -> bool:
    """Есть ли браузер на этой машине (по стандартным путям).

    Проверка приблизительная: канал Playwright может найти браузер и там,
    где мы не искали. Для списка этого достаточно.
    """
    if profile.executable_paths:
        return resolve_executable(profile) is not None

    return profile.channel in ("msedge",) and sys.platform == "win32"


def browser_args(
    profile: BrowserProfile,
    explicit_path: Optional[str] = None,
) -> list[str]:
    """Аргументы Playwright MCP для выбранного браузера.

    Порядок решений:
    1. явный путь из настроек (`browserPath`) — уважаем его;
    2. профиль только с путём (Opera GX) — ищем исполняемый файл;
    3. профиль с каналом — отдаём `--browser <канал>`.
    """
    if explicit_path:
        return ["--executable-path", explicit_path]

    if profile.channel is None:
        found = resolve_executable(profile)

        if found is None:
            raise BrowserNotInstalled(profile)

        return ["--executable-path", found]

    return ["--browser", profile.channel]


class BrowserNotInstalled(RuntimeError):
    """Браузер не найден, а канала у профиля нет (Opera GX)."""

    def __init__(self, profile: BrowserProfile) -> None:
        super().__init__(profile.install_hint or f"{profile.label} не найден.")
        self.profile = profile


def describe_available() -> list[tuple[BrowserProfile, bool]]:
    """Все профили с отметкой «есть на машине» — для команды «браузер список»."""
    return [(profile, is_available(profile)) for profile in BROWSER_PROFILES]


__all__ = [
    "BROWSER_PROFILES",
    "DEFAULT_BROWSER_ID",
    "BrowserNotInstalled",
    "BrowserProfile",
    "browser_args",
    "describe_available",
    "find_profile",
    "is_available",
    "normalize_name",
    "profile_by_id",
    "resolve_executable",
]
