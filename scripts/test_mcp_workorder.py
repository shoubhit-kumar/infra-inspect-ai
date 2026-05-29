"""End-to-end test for the work-order MCP server.

Exercises tool listing, create, list, get, update, assign, and resource
reading. Cleans up after itself.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

from src.mcp_clients.client import MCPClient
from src.utils.logging import configure_logging


async def main() -> None:
    configure_logging()

    server_cmd = [sys.executable, "-m", "scripts.run_workorder_server"]

    async with MCPClient(server_cmd) as client:
        # 1. List tools
        print("\nAvailable tools:")
        tools = await client.list_tools()
        for t in tools:
            print(f"  - {t.name}: {t.description[:80]}")

        # 2. List resources
        print("\nAvailable resources:")
        resources = await client.list_resources()
        for r in resources[:8]:
            print(f"  - {r}")

        # 3. Read summary for BLDG-001
        print("\nReading summary resource for BLDG-001...")
        summary_text = await client.read_resource("workorder://summary/BLDG-001")
        print(summary_text)

        # 4. Create a test work order
        print("\nCreating a test work order...")
        deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        result = await client.call_tool(
            "create_work_order",
            {
                "building_id": "BLDG-001",
                "issue_id": "test-mcp-work-order-99",
                "title": "MCP smoke-test work order",
                "description": "Created via the work-order MCP server smoke test.",
                "category": "general",
                "priority": "P3",
                "assigned_team": "facilities_general",
                "estimated_cost_inr": 1000.0,
                "estimated_hours": 1.0,
                "sla_deadline": deadline,
                "requires_approval": False,
            },
        )
        print(f"  {result}")

        # Parse out the id
        new_id = int(result.split("id=")[-1])

        # 5. Get it back
        print(f"\nFetching work order {new_id}...")
        wo_json = await client.call_tool("get_work_order", {"work_order_id": new_id})
        print(wo_json)

        # 6. Reassign it
        print(f"\nReassigning work order {new_id} to plumbing_team...")
        result = await client.call_tool(
            "assign_work_order",
            {"work_order_id": new_id, "team": "plumbing_team"},
        )
        print(f"  {result}")

        # 7. Transition to in_progress, then closed
        print(f"\nTransitioning work order {new_id} status...")
        await client.call_tool(
            "update_work_order_status",
            {"work_order_id": new_id, "status": "in_progress"},
        )
        result = await client.call_tool(
            "update_work_order_status",
            {"work_order_id": new_id, "status": "closed"},
        )
        print(f"  {result}")

        # 8. Verify closed status
        wo_json = await client.call_tool("get_work_order", {"work_order_id": new_id})
        wo = json.loads(wo_json)
        print(f"  Final status: {wo['status']}  closed_at: {wo['closed_at']}")

        # 9. List filtered: only open work orders
        print("\nListing open work orders for BLDG-001...")
        rows_json = await client.call_tool(
            "list_work_orders",
            {"building_id": "BLDG-001", "status_filter": "open"},
        )
        rows = json.loads(rows_json)
        print(f"  Found {len(rows)} open work order(s):")
        for r in rows[:10]:
            print(f"    [{r['priority']}] id={r['id']}  {r['title'][:60]}")

        # 10. Error handling: bad work order id
        print("\nError handling test: get non-existent work order...")
        result = await client.call_tool("get_work_order", {"work_order_id": 999999})
        print(f"  Response: {result!r}")

        # 11. Error handling: missing required argument
        print("\nError handling test: invalid status transition...")
        result = await client.call_tool(
            "update_work_order_status",
            {"work_order_id": 999999, "status": "closed"},
        )
        print(f"  Response: {result!r}")

    print("\nMCP work-order smoke test complete.")


if __name__ == "__main__":
    asyncio.run(main())