"""MCP connection lifecycle manager.

Maintains an asyncio event loop in a dedicated thread, so sync workflow
code can dispatch async MCP calls into it without blocking. Holds long-
lived connections to multiple MCP servers, one connection per server.

Usage:
    manager = MCPConnectionManager({
        "filesystem": ["python", "-m", "scripts.run_filesystem_server"],
        "workorder":  ["python", "-m", "scripts.run_workorder_server"],
    })
    with manager:
        manager.call_tool("filesystem", "write_file", {"path": "x.txt", "content": "hi"})
"""
import asyncio
import threading
from concurrent.futures import Future
from contextlib import AsyncExitStack
from typing import Any

from src.mcp_clients.client import MCPClient
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MCPConnectionManager:
    """Manage long-lived connections to multiple MCP servers from sync code.

    Use as a context manager:
        with manager:
            ...

    On enter: starts a background event loop thread and connects to all
    configured servers. On exit: closes all connections and stops the loop.
    """

    def __init__(self, servers: dict[str, list[str]]) -> None:
        """
        Args:
            servers: Mapping of logical name -> subprocess command.
                Example: {"workorder": ["python", "-m", "scripts.run_workorder_server"]}
        """
        self.server_commands = servers
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stack: AsyncExitStack | None = None
        self._clients: dict[str, MCPClient] = {}
        self._ready = threading.Event()
        self._enabled = bool(servers)

    # ---------- Context manager interface ----------

    def __enter__(self) -> "MCPConnectionManager":
        if not self._enabled:
            logger.info("mcp.manager.disabled_no_servers")
            return self

        self._thread = threading.Thread(
            target=self._run_loop,
            name="mcp-event-loop",
            daemon=True,
        )
        self._thread.start()

        # Wait until the loop is up and connections are open.
        self._ready.wait()
        if self._stack is None:
            raise RuntimeError("MCP manager failed to initialize")
        logger.info("mcp.manager.ready", servers=list(self._clients.keys()))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._enabled or self._loop is None:
            return

        # Schedule teardown on the loop thread, then wait.
        future = asyncio.run_coroutine_threadsafe(self._teardown(), self._loop)
        try:
            future.result(timeout=10.0)
        except Exception as e:
            error_text = str(e)
            # The anyio "cancel scope" error is cosmetic: it complains because the
            # teardown task isn't the same task that opened the AsyncExitStack,
            # but the subprocesses still get cleaned up when the process exits.
            # See tech debt item #4. Proper fix would restructure lifecycle so
            # teardown happens entirely on the loop thread.
            if "cancel scope" in error_text:
                logger.debug("mcp.manager.teardown_anyio_warning", error=error_text[:200])
            else:
                logger.error("mcp.manager.teardown_failed", error=error_text[:200])

        # Stop the loop.
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info("mcp.manager.shutdown")

    # ---------- Public sync API ----------

    def call_tool(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any],
        timeout: float = 60.0,
    ) -> str:
        """Synchronously call a tool on a named MCP server.

        Blocks until the call completes or times out.
        Wrapped in a Langfuse span so each tool call appears in the trace.
        """
        if not self._enabled:
            raise RuntimeError("MCP manager has no servers configured")

        from src.tracing.setup import span_mcp_call

        with span_mcp_call(server=server, tool=tool, arguments=arguments) as span:
            future = self._submit(self._async_call_tool(server, tool, arguments))
            result = future.result(timeout=timeout)
            if span:
                # Truncate large results for the span output
                preview = result[:500] + "..." if len(result) > 500 else result
                span.update(output={"result": preview, "result_length": len(result)})
            return result

    def read_resource(
        self,
        server: str,
        uri: str,
        timeout: float = 30.0,
    ) -> str:
        """Synchronously read a resource from a named MCP server."""
        if not self._enabled:
            raise RuntimeError("MCP manager has no servers configured")

        from src.tracing.setup import span_mcp_call

        with span_mcp_call(server=server, tool=f"read_resource:{uri}") as span:
            future = self._submit(self._async_read_resource(server, uri))
            result = future.result(timeout=timeout)
            if span:
                preview = result[:500] + "..." if len(result) > 500 else result
                span.update(output={"result": preview, "result_length": len(result)})
            return result

    # ---------- Async internals (run on the loop thread) ----------

    def _run_loop(self) -> None:
        """Entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._startup())
            self._ready.set()
            self._loop.run_forever()
        except Exception as e:
            logger.error("mcp.manager.loop_crashed", error=str(e))
            self._ready.set()  # unblock waiters even on failure
        finally:
            self._loop.close()

    async def _startup(self) -> None:
        """Open connections to all configured servers."""
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            for name, cmd in self.server_commands.items():
                client = MCPClient(cmd)
                await stack.enter_async_context(client)
                self._clients[name] = client
                logger.info("mcp.manager.connected", server=name)
        except Exception:
            await stack.__aexit__(None, None, None)
            raise
        self._stack = stack

    async def _teardown(self) -> None:
        """Close all connections."""
        if self._stack is not None:
            await self._stack.__aexit__(None, None, None)
        self._stack = None
        self._clients.clear()

    async def _async_call_tool(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> str:
        client = self._get_client(server)
        return await client.call_tool(tool, arguments)

    async def _async_read_resource(self, server: str, uri: str) -> str:
        client = self._get_client(server)
        return await client.read_resource(uri)

    # ---------- Helpers ----------

    def _get_client(self, name: str) -> MCPClient:
        client = self._clients.get(name)
        if client is None:
            raise KeyError(f"MCP server {name!r} is not connected")
        return client

    def _submit(self, coro) -> Future:
        if self._loop is None:
            raise RuntimeError("MCP manager loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)