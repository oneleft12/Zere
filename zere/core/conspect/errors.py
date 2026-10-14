"""Ошибки конспектора: код + русский текст для пользователя.

Код нужен вызывающему (обработчик, CLI, тесты), текст — пользователю: он же
уходит в озвучку, поэтому формулировки короткие и без служебных подробностей.
Такой же приём, как `AiError` в `zere/ai/cloud_client.py` и `McpError` в
MCP-клиенте: конвейер не должен ловить голые исключения без объяснения.
"""

from __future__ import annotations

#: Источник не найден (файла нет).
SOURCE_NOT_FOUND = "CONSPECT_SOURCE_NOT_FOUND"
#: Источник есть, но текст из него не извлекается (PDF без парсера, бинарный файл).
SOURCE_UNSUPPORTED = "CONSPECT_SOURCE_UNSUPPORTED"
#: Из источника не вышло текста.
SOURCE_EMPTY = "CONSPECT_SOURCE_EMPTY"
#: Материал слишком большой.
SOURCE_TOO_LARGE = "CONSPECT_SOURCE_TOO_LARGE"
#: Страница не скачалась (сеть, таймаут, код ответа).
DOWNLOAD_FAILED = "CONSPECT_DOWNLOAD_FAILED"
#: Адрес ведёт на локальный/приватный хост — по умолчанию запрещено.
URL_FORBIDDEN = "CONSPECT_URL_FORBIDDEN"
#: Материал длиннее, чем можно обработать в чате.
TOO_LONG_FOR_CHAT = "CONSPECT_TOO_LONG_FOR_CHAT"
#: Модель недоступна (нет ключа и нет локальной модели).
AI_UNAVAILABLE = "CONSPECT_AI_UNAVAILABLE"
#: Модель не дала ни одного осмысленного ответа по частям.
AI_FAILED = "CONSPECT_AI_FAILED"
#: Не задано хранилище заметок.
VAULT_NOT_CONFIGURED = "CONSPECT_VAULT_NOT_CONFIGURED"
#: Заметку не удалось записать (права, диск, недопустимый путь).
WRITE_FAILED = "CONSPECT_WRITE_FAILED"
#: Настройки конспектора выключены.
DISABLED = "CONSPECT_DISABLED"


class ConspectError(Exception):
    """Ошибка конспектора с кодом и готовым текстом для пользователя."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:  # pragma: no cover — тривиально
        return self.message


__all__ = [
    "AI_FAILED",
    "AI_UNAVAILABLE",
    "DISABLED",
    "DOWNLOAD_FAILED",
    "SOURCE_EMPTY",
    "SOURCE_NOT_FOUND",
    "SOURCE_TOO_LARGE",
    "SOURCE_UNSUPPORTED",
    "TOO_LONG_FOR_CHAT",
    "URL_FORBIDDEN",
    "VAULT_NOT_CONFIGURED",
    "WRITE_FAILED",
    "ConspectError",
]
