"""Filesystem MCP server.

Exposes file read/write/list/delete operations as MCP tools, and the
data/outputs directory as browsable MCP resources. Communicates over
stdio (stdin/stdout JSON-RPC).

Launched as a subprocess by an MCP client (our agents).

Run standalone for testing:
    python -m scripts.run_filesystem_server
"""
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, TextContent, Tool


# ---------- Configuration ----------
# Restrict file operations to this base directory for safety.
# Read from env var, fallback to data/outputs.
ROOT_DIR = Path(os.environ.get("MCP_FS_ROOT", "data/outputs")).resolve()
ROOT_DIR.mkdir(parents=True, exist_ok=True)


# ---------- Server instance ----------
app = Server("infra-inspect-filesystem")


# ---------- Helpers ----------

def _resolve_safe(path_str: str) -> Path:
    """Resolve path and ensure it stays within ROOT_DIR.

    Path-traversal protection. ../etc/passwd-style attacks are blocked.
    """
    candidate = (ROOT_DIR / path_str).resolve()
    try:
        candidate.relative_to(ROOT_DIR)
    except ValueError as e:
        raise PermissionError(
            f"Path {path_str!r} escapes server root {ROOT_DIR}"
        ) from e
    return candidate


# ---------- Tool registry ----------

@app.list_tools()
async def list_tools() -> list[Tool]:
    """Tell clients what tools this server exposes."""
    return [
        Tool(
            name="write_file",
            description=(
                "Write text content to a file under the server's root directory. "
                "Creates parent directories as needed. Overwrites if file exists."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from server root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text content to write.",
                    },
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="read_file",
            description="Read a text file under the server's root directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="list_directory",
            description="List files (and subdirectories) under a path relative to server root.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path. Empty string = server root.",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="delete_file",
            description="Delete a file under the server's root directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool by name. Returns one or more content blocks."""
    if name == "write_file":
        target = _resolve_safe(arguments["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(arguments["content"], encoding="utf-8")
        return [TextContent(type="text", text=f"Wrote {len(arguments['content'])} chars to {target.relative_to(ROOT_DIR)}")]

    if name == "read_file":
        target = _resolve_safe(arguments["path"])
        if not target.exists():
            return [TextContent(type="text", text=f"ERROR: file not found: {arguments['path']}")]
        text = target.read_text(encoding="utf-8")
        return [TextContent(type="text", text=text)]

    if name == "list_directory":
        target = _resolve_safe(arguments["path"] or ".")
        if not target.exists() or not target.is_dir():
            return [TextContent(type="text", text=f"ERROR: not a directory: {arguments['path']}")]
        entries: list[str] = []
        for item in sorted(target.iterdir()):
            kind = "dir " if item.is_dir() else "file"
            size = item.stat().st_size if item.is_file() else 0
            entries.append(f"  {kind}  {size:>10}  {item.relative_to(ROOT_DIR)}")
        body = "\n".join(entries) or "(empty)"
        return [TextContent(type="text", text=body)]

    if name == "delete_file":
        target = _resolve_safe(arguments["path"])
        if not target.exists():
            return [TextContent(type="text", text=f"ERROR: file not found: {arguments['path']}")]
        target.unlink()
        return [TextContent(type="text", text=f"Deleted {arguments['path']}")]

    return [TextContent(type="text", text=f"ERROR: unknown tool: {name}")]


# ---------- Resource registry ----------

@app.list_resources()
async def list_resources() -> list[Resource]:
    """Expose every file in the server root as a browsable resource.

    Clients can list these and read them by URI without needing to know
    a tool name. Resources are the 'data side' of MCP, vs Tools which are
    the 'action side.'
    """
    resources: list[Resource] = []
    for path in sorted(ROOT_DIR.rglob("*")):
        if path.is_file():
            rel = path.relative_to(ROOT_DIR)
            resources.append(
                Resource(
                    uri=f"file:///{rel.as_posix()}",
                    name=str(rel),
                    description=f"File at {rel}, {path.stat().st_size} bytes",
                    mimeType="text/plain",
                )
            )
    return resources


@app.read_resource()
async def read_resource(uri) -> str:
    """Return the text content of a resource by URI.

    The MCP SDK may pass `uri` as either a string or a Pydantic AnyUrl object,
    depending on version. Normalize to string first.
    """
    uri_str = str(uri)
    if not uri_str.startswith("file:///"):
        raise ValueError(f"Unsupported URI scheme: {uri_str}")
    rel = uri_str[len("file:///"):]
    target = _resolve_safe(rel)
    if not target.exists():
        raise FileNotFoundError(uri_str)
    return target.read_text(encoding="utf-8")


# ---------- Entry point ----------

async def main() -> None:
    """Run the server over stdio.

    Blocks reading from stdin and writing to stdout until the client
    closes the connection.
    """
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())