"""Introspect all configured MCP servers.

Opens each MCP server, lists its tools and resources, and prints a
combined inventory. Read-only - no side effects on data.

Run:
    python -m scripts.inspect_mcp
"""
import asyncio
import sys

from src.config.settings import get_settings
from src.mcp_clients.client import MCPClient
from src.utils.logging import configure_logging


async def _inspect_one(name: str, cmd: list[str]) -> None:
    print(f"\n{'=' * 72}")
    print(f"MCP server: {name}")
    print(f"  command: {' '.join(cmd)}")
    print("=" * 72)

    try:
        async with MCPClient(cmd) as client:
            tools = await client.list_tools()
            print(f"\nTools ({len(tools)}):")
            for t in tools:
                print(f"  - {t.name}")
                desc = (t.description or "").strip()
                if desc:
                    print(f"      {desc[:100]}")
                required = t.input_schema.get("required", [])
                if required:
                    print(f"      required args: {required}")

            resources = await client.list_resources()
            print(f"\nResources ({len(resources)}):")
            limit = 10
            for r in resources[:limit]:
                print(f"  - {r}")
            if len(resources) > limit:
                print(f"  ... and {len(resources) - limit} more")
    except Exception as e:
        print(f"  FAILED to connect: {e}")


async def main() -> None:
    configure_logging()
    settings = get_settings()

    servers = {
        "filesystem":   settings.mcp_filesystem_command,
        "workorder":    settings.mcp_workorder_command,
        "notification": settings.mcp_notification_command,
    }

    print(f"\nInspecting {len(servers)} MCP server(s)...")
    for name, cmd in servers.items():
        await _inspect_one(name, cmd)

    print(f"\n{'=' * 72}")
    print("Inspection complete.")


if __name__ == "__main__":
    asyncio.run(main())