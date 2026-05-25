import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

"""Launch the work-order MCP server over stdio."""
import asyncio

from src.mcp_servers.workorder_server import main

if __name__ == "__main__":
    asyncio.run(main())