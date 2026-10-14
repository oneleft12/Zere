"""Безопасность: права на файлы с секретами (см. file_access)."""

from __future__ import annotations

from zere.core.security.file_access import restrict_to_owner

__all__ = ["restrict_to_owner"]
