"""Work-order MCP server.

Exposes SQLite-backed work-order CRUD as MCP tools. Acts as a thin
adapter over AssetRepository. Replaces direct DB access from the
WorkOrderAgent in Day 14.

Run standalone:
    python -m scripts.run_workorder_server
"""
import json
from typing import Any

# CRITICAL: MCP stdio servers MUST keep stdout pure for JSON-RPC.
# configure_logging() routes all output to stderr via _console.
from src.utils.logging import configure_logging

configure_logging()

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, TextContent, Tool

from src.memory.repository import AssetRepository
from src.utils.logging import get_logger

logger = get_logger(__name__)

app = Server("infra-inspect-workorder")

# Lazy-initialized repository so subprocess startup is cheap.
_repo: AssetRepository | None = None


def _get_repo() -> AssetRepository:
    global _repo
    if _repo is None:
        _repo = AssetRepository()
        logger.info("workorder_server.repo_ready")
    return _repo


# ---------- Tool registry ----------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_work_order",
            description=(
                "Create a new work order for a building. Returns the new work order's id. "
                "All cost values are in INR. Priorities: P1 (urgent, 4h), P2 (24h), P3 (1 week), P4 (1 month). "
                "sla_deadline must be ISO 8601 datetime."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "building_id": {"type": "string"},
                    "issue_id": {
                        "type": "string",
                        "description": "Stable issue id, kebab-case (e.g. 'electrical-wiring-degradation-01').",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["fire_safety", "electrical", "structural", "plumbing", "hvac", "general"],
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["P1", "P2", "P3", "P4"],
                    },
                    "assigned_team": {"type": "string"},
                    "estimated_cost_inr": {"type": "number"},
                    "estimated_hours": {"type": "number"},
                    "sla_deadline": {
                        "type": "string",
                        "description": "ISO 8601 datetime (UTC recommended).",
                    },
                    "requires_approval": {"type": "boolean", "default": False},
                },
                "required": [
                    "building_id", "issue_id", "title", "category",
                    "priority", "assigned_team", "estimated_cost_inr",
                    "estimated_hours", "sla_deadline",
                ],
            },
        ),
        Tool(
            name="update_work_order_status",
            description=(
                "Transition a work order to a new status. "
                "Valid statuses: open, in_progress, closed, verified, cancelled. "
                "Statuses closed/verified/cancelled also set closed_at."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "work_order_id": {"type": "integer"},
                    "status": {
                        "type": "string",
                        "enum": ["open", "in_progress", "closed", "verified", "cancelled"],
                    },
                },
                "required": ["work_order_id", "status"],
            },
        ),
        Tool(
            name="assign_work_order",
            description="Change the team assigned to a work order.",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_order_id": {"type": "integer"},
                    "team": {"type": "string"},
                },
                "required": ["work_order_id", "team"],
            },
        ),
        Tool(
            name="list_work_orders",
            description=(
                "List work orders for a building. Optional filters by status and priority. "
                "Returns a JSON array of work orders ordered by creation time desc."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "building_id": {"type": "string"},
                    "status_filter": {
                        "type": "string",
                        "enum": ["open", "in_progress", "closed", "verified", "cancelled"],
                    },
                    "priority_filter": {
                        "type": "string",
                        "enum": ["P1", "P2", "P3", "P4"],
                    },
                },
                "required": ["building_id"],
            },
        ),
        Tool(
            name="get_work_order",
            description="Get a single work order by its internal id. Returns a JSON object or 'NOT FOUND'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_order_id": {"type": "integer"},
                },
                "required": ["work_order_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch a tool call. All tool errors are returned as ERROR text so the
    client sees them in the response rather than crashing the server."""
    try:
        repo = _get_repo()

        if name == "create_work_order":
            building_id = arguments["building_id"]
            wo_dict = {k: v for k, v in arguments.items() if k != "building_id"}
            new_id = repo.create_standalone_work_order(building_id, wo_dict)
            return [TextContent(type="text", text=f"Created work order id={new_id}")]

        if name == "update_work_order_status":
            repo.update_work_order_status(
                arguments["work_order_id"],
                arguments["status"],
            )
            return [TextContent(
                type="text",
                text=f"Work order {arguments['work_order_id']} -> {arguments['status']}",
            )]

        if name == "assign_work_order":
            repo.reassign_work_order(
                arguments["work_order_id"],
                arguments["team"],
            )
            return [TextContent(
                type="text",
                text=f"Work order {arguments['work_order_id']} reassigned to {arguments['team']}",
            )]

        if name == "list_work_orders":
            rows = repo.list_work_orders_for_building(
                building_id=arguments["building_id"],
                status_filter=arguments.get("status_filter"),
                priority_filter=arguments.get("priority_filter"),
            )
            return [TextContent(type="text", text=json.dumps(rows, indent=2))]

        if name == "get_work_order":
            wo = repo.get_work_order_by_id(arguments["work_order_id"])
            if wo is None:
                return [TextContent(type="text", text="NOT FOUND")]
            return [TextContent(type="text", text=json.dumps(wo, indent=2))]

        return [TextContent(type="text", text=f"ERROR: unknown tool: {name}")]

    except KeyError as e:
        return [TextContent(type="text", text=f"ERROR: missing argument: {e}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"ERROR: {e}")]
    except Exception as e:
        logger.error("workorder_server.tool_failed", tool=name, error=str(e))
        return [TextContent(type="text", text=f"ERROR: {e}")]


# ---------- Resource registry ----------
# URI scheme: workorder://{kind}/{building_id}[/{filter}]
# Examples:
#   workorder://summary/BLDG-001
#   workorder://open/BLDG-001
#   workorder://history/BLDG-001

@app.list_resources()
async def list_resources() -> list[Resource]:
    repo = _get_repo()
    assets = repo.list_assets()
    resources: list[Resource] = []
    for a in assets:
        bid = a.building_id
        resources.extend([
            Resource(
                uri=f"workorder://summary/{bid}",
                name=f"{bid} summary",
                description=f"Summary of work orders for {bid}",
                mimeType="application/json",
            ),
            Resource(
                uri=f"workorder://open/{bid}",
                name=f"{bid} open work orders",
                description=f"All open work orders for {bid}",
                mimeType="application/json",
            ),
            Resource(
                uri=f"workorder://history/{bid}",
                name=f"{bid} full history",
                description=f"All work orders ever recorded for {bid}",
                mimeType="application/json",
            ),
        ])
    return resources


@app.read_resource()
async def read_resource(uri) -> str:
    """Resolve a workorder:// URI to JSON content."""
    uri_str = str(uri)
    if not uri_str.startswith("workorder://"):
        raise ValueError(f"Unsupported URI scheme: {uri_str}")

    # Parse "kind/building_id[/extra]"
    rest = uri_str[len("workorder://"):]
    parts = rest.split("/", 2)
    if len(parts) < 2:
        raise ValueError(f"Malformed URI: {uri_str}")
    kind, building_id = parts[0], parts[1]

    repo = _get_repo()

    if kind == "summary":
        mem = repo.get_asset_memory(building_id)
        return json.dumps(mem.summary.model_dump(mode="json"), indent=2)

    if kind == "open":
        rows = repo.list_work_orders_for_building(building_id, status_filter="open")
        return json.dumps(rows, indent=2)

    if kind == "history":
        rows = repo.list_work_orders_for_building(building_id)
        return json.dumps(rows, indent=2)

    raise ValueError(f"Unknown resource kind: {kind}")


# ---------- Entry point ----------

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())