"""End-to-end test for the notification MCP server.

Exercises tool listing, send across all four channels, query history,
and resource reads.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

from src.mcp_clients.client import MCPClient
from src.utils.logging import configure_logging


async def main() -> None:
    configure_logging()

    server_cmd = [sys.executable, "-m", "scripts.run_notification_server"]

    async with MCPClient(server_cmd) as client:
        # 1. Tools
        print("\nAvailable tools:")
        for t in await client.list_tools():
            print(f"  - {t.name}: {t.description[:80]}")

        # 2. Resources
        print("\nAvailable resources:")
        for r in await client.list_resources():
            print(f"  - {r}")

        # 3. Read global stats (probably empty if first run)
        print("\nReading global notification stats...")
        stats = await client.read_resource("notifications://stats/global")
        print(stats)

        # 4. Send across all four channels
        print("\nSending notifications across all four channels...")
        for channel, urgency in [
            ("slack", "URGENT"),
            ("email", "high"),
            ("in_app", "normal"),
            ("sms", "URGENT"),
        ]:
            result = await client.call_tool(
                "send_notification",
                {
                    "channel": channel,
                    "audience": "assigned_team" if channel != "email" else "building_manager",
                    "subject": f"[{urgency}] Day 13 smoke test via {channel}",
                    "body": f"This is a smoke-test notification on channel {channel} at urgency {urgency}.",
                    "urgency": urgency,
                    "building_id": "BLDG-001",
                },
            )
            print(f"  {channel:8s}: {result}")

        # 5. Send one tied to a work order
        print("\nSending notification tied to a specific work order...")
        result = await client.call_tool(
            "send_notification",
            {
                "channel": "email",
                "audience": "assigned_team",
                "subject": "Reminder: P1 work order due in 4 hours",
                "body": "Action required on electrical wiring repair work order.",
                "urgency": "URGENT",
                "building_id": "BLDG-001",
                "work_order_id": 3,
            },
        )
        print(f"  {result}")

        # 6. Query the log
        print("\nListing all notifications (limit 5)...")
        rows_json = await client.call_tool("list_notifications", {"limit": 5})
        rows = json.loads(rows_json)
        print(f"  Got {len(rows)} record(s):")
        for r in rows:
            print(f"    [{r['urgency']}] {r['channel']:8s} -> {r['audience']:20s}  {r['subject'][:70]}")

        # 7. Filter by URGENT
        print("\nListing only URGENT notifications...")
        rows_json = await client.call_tool(
            "list_notifications",
            {"urgency": "URGENT", "limit": 10},
        )
        rows = json.loads(rows_json)
        print(f"  Got {len(rows)} URGENT record(s)")
        for r in rows:
            print(f"    {r['channel']:8s} -> {r['audience']}  {r['subject'][:60]}")

        # 8. Filter by recent time
        five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        print(f"\nListing notifications since {five_min_ago}...")
        rows_json = await client.call_tool(
            "list_notifications",
            {"since": five_min_ago},
        )
        rows = json.loads(rows_json)
        print(f"  Got {len(rows)} recent record(s) (expect at least 5)")

        # 9. Read building-specific recent resource
        print("\nReading recent notifications for BLDG-001...")
        recent = await client.read_resource("notifications://recent/BLDG-001")
        recent_list = json.loads(recent)
        print(f"  {len(recent_list)} record(s) for BLDG-001")

        # 10. Read updated global stats
        print("\nReading updated global stats...")
        stats = await client.read_resource("notifications://stats/global")
        print(stats)

        # 11. Error handling: invalid channel
        print("\nError handling test: invalid channel...")
        result = await client.call_tool(
            "send_notification",
            {
                "channel": "carrier_pigeon",
                "audience": "anyone",
                "subject": "Test",
                "body": "Test",
            },
        )
        print(f"  Response: {result!r}")

        # 12. Error handling: missing required arg
        print("\nError handling test: missing arg...")
        result = await client.call_tool(
            "send_notification",
            {"channel": "slack", "audience": "team"},  # missing subject and body
        )
        print(f"  Response: {result!r}")

    print("\nDay 13 MCP notification smoke test complete.")


if __name__ == "__main__":
    asyncio.run(main())