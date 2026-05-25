"""Notification MCP server.

Routes notifications to one of several channel implementations (slack,
email, in_app, sms) and persists every dispatch to SQLite for audit.

Today the channel implementations are mocks that log to stderr. They
can be replaced with real Slack/SendGrid/Twilio calls without touching
the agents that depend on this server.

Run standalone:
    python -m scripts.run_notification_server
"""
import json
from datetime import datetime, timezone
from typing import Any

# Important: configure logging at module load time so the subprocess
# never leaks log output onto stdout (which carries the MCP JSON-RPC).
from src.utils.logging import configure_logging
configure_logging()

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, TextContent, Tool

from src.memory.repository import AssetRepository
from src.utils.logging import get_logger

logger = get_logger(__name__)

app = Server("infra-inspect-notification")

_repo: AssetRepository | None = None

# Valid enums - kept narrow so MCP clients (and LLMs) get clear options.
VALID_CHANNELS = {"slack", "email", "in_app", "sms"}
VALID_URGENCIES = {"normal", "high", "URGENT"}


def _get_repo() -> AssetRepository:
    global _repo
    if _repo is None:
        _repo = AssetRepository()
        logger.info("notification_server.repo_ready")
    return _repo


# ---------- Channel implementations (mocks today) ----------
# Each returns ("sent" | "failed", optional_extra_info).
# In production these would call real SDKs.

def _send_slack(audience: str, subject: str, body: str, urgency: str) -> tuple[str, str]:
    import os
    import json
    import urllib.request
    import urllib.error

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        # No webhook configured - fall back to mock behavior.
        logger.info("channel.slack.send.mock", audience=audience, urgency=urgency, subject=subject[:80])
        return ("sent", f"slack mock (no webhook configured) for #{audience}")

    urgency_emoji = {"URGENT": "🚨 *URGENT*", "high": "⚠️ High", "normal": "ℹ️"}.get(urgency, "ℹ️")
    payload = {
        "text": f"{urgency_emoji}: {subject}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": subject[:150]},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body[:2000]},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"audience: `{audience}`  urgency: `{urgency}`"},
                ],
            },
        ],
    }

    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5).read()
        logger.info("channel.slack.send", audience=audience, urgency=urgency, subject=subject[:80])
        return ("sent", "Slack webhook delivered")
    except urllib.error.HTTPError as e:
        logger.error("channel.slack.http_error", code=e.code, error=str(e))
        return ("failed", f"slack HTTP {e.code}")
    except Exception as e:
        logger.error("channel.slack.failed", error=str(e))
        return ("failed", f"slack error: {e}")


def _send_email(audience: str, subject: str, body: str, urgency: str) -> tuple[str, str]:
    logger.info(
        "channel.email.send",
        audience=audience,
        urgency=urgency,
        subject=subject[:80],
    )
    return ("sent", f"email to {audience}@example.com")


def _send_inapp(audience: str, subject: str, body: str, urgency: str) -> tuple[str, str]:
    logger.info(
        "channel.in_app.send",
        audience=audience,
        urgency=urgency,
        subject=subject[:80],
    )
    return ("sent", f"in-app notification for {audience}")


def _send_sms(audience: str, subject: str, body: str, urgency: str) -> tuple[str, str]:
    logger.info(
        "channel.sms.send",
        audience=audience,
        urgency=urgency,
        subject=subject[:80],
    )
    return ("sent", f"sms to {audience}'s phone")


_DISPATCHERS = {
    "slack": _send_slack,
    "email": _send_email,
    "in_app": _send_inapp,
    "sms": _send_sms,
}


# ---------- Tool registry ----------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="send_notification",
            description=(
                "Send a notification through a channel and persist the record. "
                "Channels: slack, email, in_app, sms. "
                "Urgencies: normal, high, URGENT. "
                "Returns the new notification's id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "enum": list(VALID_CHANNELS),
                    },
                    "audience": {
                        "type": "string",
                        "description": "Who receives it. E.g. 'assigned_team', 'building_manager', 'executive'.",
                    },
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "urgency": {
                        "type": "string",
                        "enum": list(VALID_URGENCIES),
                        "default": "normal",
                    },
                    "building_id": {
                        "type": "string",
                        "description": "Optional building id this notification is about.",
                    },
                    "work_order_id": {
                        "type": "integer",
                        "description": "Optional work order id this notification is about.",
                    },
                },
                "required": ["channel", "audience", "subject", "body"],
            },
        ),
        Tool(
            name="list_notifications",
            description=(
                "Query the notification log with optional filters. "
                "Returns a JSON array of dispatched notifications."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "building_id": {"type": "string"},
                    "since": {
                        "type": "string",
                        "description": "Optional ISO datetime. Only notifications dispatched at or after this time.",
                    },
                    "channel": {
                        "type": "string",
                        "enum": list(VALID_CHANNELS),
                    },
                    "urgency": {
                        "type": "string",
                        "enum": list(VALID_URGENCIES),
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 200,
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        repo = _get_repo()

        if name == "send_notification":
            channel = arguments["channel"]
            if channel not in VALID_CHANNELS:
                return [TextContent(
                    type="text",
                    text=f"ERROR: invalid channel '{channel}'. Use one of: {sorted(VALID_CHANNELS)}",
                )]
            urgency = arguments.get("urgency", "normal")
            if urgency not in VALID_URGENCIES:
                return [TextContent(
                    type="text",
                    text=f"ERROR: invalid urgency '{urgency}'. Use one of: {sorted(VALID_URGENCIES)}",
                )]

            dispatcher = _DISPATCHERS[channel]
            audience = arguments["audience"]
            subject = arguments["subject"]
            body = arguments["body"]

            try:
                status, info = dispatcher(audience, subject, body, urgency)
            except Exception as e:
                logger.error("dispatcher.failed", channel=channel, error=str(e))
                status = "failed"
                info = f"dispatcher error: {e}"

            new_id = repo.record_notification(
                channel=channel,
                audience=audience,
                subject=subject,
                body=body,
                urgency=urgency,
                building_id=arguments.get("building_id"),
                work_order_id=arguments.get("work_order_id"),
                delivery_status=status,
            )
            return [TextContent(
                type="text",
                text=f"id={new_id} status={status} info={info}",
            )]

        if name == "list_notifications":
            since_str = arguments.get("since")
            since_dt = None
            if since_str:
                try:
                    since_dt = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
                    if since_dt.tzinfo is None:
                        since_dt = since_dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    return [TextContent(
                        type="text",
                        text=f"ERROR: invalid 'since' datetime: {since_str}",
                    )]

            rows = repo.list_notifications(
                building_id=arguments.get("building_id"),
                since=since_dt,
                channel=arguments.get("channel"),
                urgency=arguments.get("urgency"),
                limit=int(arguments.get("limit", 50)),
            )
            return [TextContent(type="text", text=json.dumps(rows, indent=2))]

        return [TextContent(type="text", text=f"ERROR: unknown tool: {name}")]

    except KeyError as e:
        return [TextContent(type="text", text=f"ERROR: missing argument: {e}")]
    except Exception as e:
        logger.error("notification_server.tool_failed", tool=name, error=str(e))
        return [TextContent(type="text", text=f"ERROR: {e}")]


# ---------- Resource registry ----------

@app.list_resources()
async def list_resources() -> list[Resource]:
    repo = _get_repo()
    resources: list[Resource] = [
        Resource(
            uri="notifications://stats/global",
            name="global notification stats",
            description="Aggregate counts across all buildings, by channel and urgency.",
            mimeType="application/json",
        ),
    ]
    for a in repo.list_assets():
        resources.append(
            Resource(
                uri=f"notifications://recent/{a.building_id}",
                name=f"{a.building_id} recent notifications",
                description=f"Last 20 notifications dispatched for {a.building_id}",
                mimeType="application/json",
            )
        )
    return resources


@app.read_resource()
async def read_resource(uri) -> str:
    uri_str = str(uri)
    if not uri_str.startswith("notifications://"):
        raise ValueError(f"Unsupported URI scheme: {uri_str}")

    rest = uri_str[len("notifications://"):]
    parts = rest.split("/", 1)
    if len(parts) < 1:
        raise ValueError(f"Malformed URI: {uri_str}")
    kind = parts[0]
    repo = _get_repo()

    if kind == "stats" and len(parts) == 2 and parts[1] == "global":
        return json.dumps(repo.notification_stats(), indent=2)

    if kind == "recent" and len(parts) == 2:
        rows = repo.list_notifications(building_id=parts[1], limit=20)
        return json.dumps(rows, indent=2)

    raise ValueError(f"Unknown resource URI: {uri_str}")


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