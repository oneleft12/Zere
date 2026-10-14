"""Встроенные MCP-плагины ZERE: браузер (Playwright) и заметки (Obsidian)."""

from __future__ import annotations

from zere.core.plugins.builtin.mcp.mcp_command import (
    McpCommand,
    McpCommandParseError,
    McpCommandRouter,
)
from zere.core.plugins.builtin.mcp.mcp_plugin_base import McpPluginBase
from zere.core.plugins.builtin.mcp.obsidian_plugin import ObsidianMcpPlugin
from zere.core.plugins.builtin.mcp.playwright_plugin import PlaywrightMcpPlugin

__all__ = [
    "McpCommand",
    "McpCommandParseError",
    "McpCommandRouter",
    "McpPluginBase",
    "ObsidianMcpPlugin",
    "PlaywrightMcpPlugin",
]
