"""Reusable MCP stdio client.

Spawns an MCP server as a subprocess (over stdio) and exposes a clean
async API: list_tools, call_tool, list_resources, read_resource.

Usage:
    async with MCPClient(["python", "-m", "scripts.run_filesystem_server"]) as client:
        tools = await client.list_tools()
        result = await client.call_tool("write_file", {"path": "x.txt", "content": "hi"})
"""
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolInfo:
    """Lightweight info about a tool offered by an MCP server."""
    name: str
    description: str
    input_schema: dict[str, Any]


class MCPClient:
    """Async context manager around an MCP stdio client.

    Spawns the server as a subprocess on __aenter__, tears it down on __aexit__.
    """

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.env = env
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None

    async def __aenter__(self) -> "MCPClient":
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        params = StdioServerParameters(
            command=self.command[0],
            args=self.command[1:],
            env=self.env,
        )
        read_stream, write_stream = await self._stack.enter_async_context(
            stdio_client(params)
        )
        self.session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()
        logger.info("mcp.client.initialized", command=" ".join(self.command))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc, tb)
        self._stack = None
        self.session = None

    # ---------- Public API ----------

    async def list_tools(self) -> list[ToolInfo]:
        assert self.session, "MCPClient must be used as async context manager"
        resp = await self.session.list_tools()
        return [
            ToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {},
            )
            for t in resp.tools
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Call a tool and return its text output joined."""
        assert self.session, "MCPClient must be used as async context manager"
        result = await self.session.call_tool(name, arguments=arguments)
        # MCP returns a list of content blocks; we flatten the text ones.
        parts: list[str] = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)

    async def list_resources(self) -> list[str]:
        assert self.session, "MCPClient must be used as async context manager"
        resp = await self.session.list_resources()
        return [r.uri for r in resp.resources]

    async def read_resource(self, uri: str) -> str:
        assert self.session, "MCPClient must be used as async context manager"
        resp = await self.session.read_resource(uri)
        # Each resource read returns a list of contents; we join text.
        parts: list[str] = []
        for c in resp.contents:
            text = getattr(c, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)