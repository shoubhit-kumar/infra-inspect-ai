"""Agent-facing MCP accessor.

We use a process-global manager so agents don't need to receive an MCP
manager parameter through every layer. The workflow opens the manager at
start, agents call get_mcp() to fetch it, and it closes at end.
"""
from src.mcp_clients.manager import MCPConnectionManager
from src.utils.logging import get_logger

logger = get_logger(__name__)

_manager: MCPConnectionManager | None = None


def set_mcp_manager(manager: MCPConnectionManager | None) -> None:
    """Install a global MCP manager. Pass None to clear it."""
    global _manager
    _manager = manager


def get_mcp() -> MCPConnectionManager | None:
    """Fetch the global MCP manager, or None if MCP is disabled or not yet open."""
    return _manager