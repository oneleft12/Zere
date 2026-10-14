"""MCP (Model Context Protocol): клиент и настройки серверов.

Модуль даёт ZERE инструменты внешних MCP-серверов (браузер, заметки и др.)
без tool calling: плагины-обработчики сами разбирают фразу и вызывают нужный
инструмент. См. docs/MCP_PLUGINS.md.
"""

from __future__ import annotations

from zere.core.mcp.client import (
    PROTOCOL_VERSION,
    McpError,
    McpStdioClient,
    McpTool,
    McpToolResult,
    resolve_command,
    tool_result_text,
)
from zere.core.mcp.config import (
    McpServerSettings,
    load_mcp_config,
    load_server,
)

__all__ = [
    "PROTOCOL_VERSION",
    "McpError",
    "McpServerSettings",
    "McpStdioClient",
    "McpTool",
    "McpToolResult",
    "load_mcp_config",
    "load_server",
    "resolve_command",
    "tool_result_text",
]
