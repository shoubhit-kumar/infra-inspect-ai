import os
import sys

# Add the project root directory to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

"""Launch the filesystem MCP server over stdio.

Used by:
- The MCP client test script (test_mcp_filesystem.py) as a subprocess
- Agent runtime as a subprocess
- Manual exploration (mcp inspector etc.)
"""
import asyncio

from src.mcp_servers.filesystem_server import main

if __name__ == "__main__":
    asyncio.run(main())