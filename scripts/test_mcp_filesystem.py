"""End-to-end test for the filesystem MCP server.

Exercises tool listing, all four tools, and resource browsing.

Run:
    python -m scripts.test_mcp_filesystem
"""
import asyncio
import sys

from src.mcp_clients.client import MCPClient
from src.utils.logging import configure_logging


async def main() -> None:
    configure_logging()

    server_cmd = [sys.executable, "-m", "scripts.run_filesystem_server"]

    async with MCPClient(server_cmd) as client:
        # 1. List tools
        print("\nAvailable tools:")
        tools = await client.list_tools()
        for t in tools:
            print(f"  - {t.name}: {t.description[:80]}")

        # 2. List resources (any prior reports etc.)
        print("\nAvailable resources:")
        resources = await client.list_resources()
        for r in resources[:5]:  # cap for readability
            print(f"  - {r}")
        if len(resources) > 5:
            print(f"  ... and {len(resources) - 5} more")

        # 3. Write a file
        print("\nWriting test file...")
        result = await client.call_tool(
            "write_file",
            {
                "path": "mcp_smoke_test.txt",
                "content": "Hello from MCP! Test working.\n",
            },
        )
        print(f"  {result}")

        # 4. List directory
        print("\nListing root directory...")
        result = await client.call_tool("list_directory", {"path": ""})
        print(result)

        # 5. Read the file back
        print("\nReading test file back...")
        result = await client.call_tool(
            "read_file", {"path": "mcp_smoke_test.txt"}
        )
        print(f"  Content: {result!r}")

        # 6. Read same file as a resource (the other access pattern)
        print("\nReading same file via resource API...")
        text = await client.read_resource("file:///mcp_smoke_test.txt")
        print(f"  Content: {text!r}")

        # 7. Delete the file
        print("\nDeleting test file...")
        result = await client.call_tool(
            "delete_file", {"path": "mcp_smoke_test.txt"}
        )
        print(f"  {result}")

        # 8. Path traversal protection test
        print("\nTesting path traversal protection...")
        result = await client.call_tool(
            "read_file", {"path": "../../etc/passwd"}
        )
        print(f"  Response: {result[:120]!r}")

    print("\nMCP smoke test complete.")


if __name__ == "__main__":
    asyncio.run(main())