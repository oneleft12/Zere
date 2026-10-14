"""Мостик к настройкам ИИ: «готова ли модель» и подпись модели для заметки.

Нужен обоим входам конспектора — обработчику конвейера (чат, панель) и CLI.
Дублировать разбор `AiService.status()` в двух местах нельзя: расхождение
означало бы, что чат отказывает, а CLI работает (или наоборот).

`AiService.generate` при отсутствии провайдера **не бросает исключение**, а
возвращает текст («Введите API-ключ…»). Поэтому до работы модели есть явная
проверка `preflight`: иначе этот текст лёг бы в заметку как конспект.
"""

from __future__ import annotations

from typing import Any, Optional


def preflight(ai: Any) -> Optional[str]:
    """Причина, по которой конспект невозможен (None — модель готова).

    Объект без `status()` (фейк в тестах, чужой клиент) считается готовым:
    проверка — удобство, а не контракт.
    """
    status = getattr(ai, "status", None)

    if status is None:
        return None

    try:
        state = status()
    except Exception as ex:  # noqa: BLE001 — состояние ИИ не должно ломать конспект
        return f"Не удалось определить состояние ИИ: {ex}"

    if not isinstance(state, dict):
        return None

    if state.get("ready"):
        return None

    return str(
        state.get("message")
        or "ИИ не настроен: введите API-ключ или установите локальную модель."
    )


def model_label(ai: Any) -> str:
    """Подпись модели: «облачно · openai/gpt-…» или «локально · qwen3.5:4b»."""
    status = getattr(ai, "status", None)

    if status is None:
        return ""

    try:
        state = status()
    except Exception:  # noqa: BLE001 — подпись не стоит сбоя операции
        return ""

    if not isinstance(state, dict):
        return ""

    provider = state.get("activeProvider")

    if provider == "cloud":
        cloud = state.get("cloud") or {}
        provider_name = cloud.get("provider", "")
        model_name = cloud.get("model", "")

        return f"облако · {provider_name}/{model_name}".strip(" ·/")

    if provider == "local":
        local = state.get("local") or {}

        return f"локально · {local.get('model', '')}".strip(" ·")

    return ""


__all__ = ["model_label", "preflight"]
