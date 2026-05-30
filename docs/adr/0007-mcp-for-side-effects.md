# ADR-0007: Use Model Context Protocol for side-effecting tools

**Status:** Accepted
**Date:** 2026-04-30
**Deciders:** Project author

## Context

Three categories of side effects need to happen from the workflow:

1. **Filesystem writes.** The documentation agent writes Markdown reports to `data/outputs/`. The filesystem agent (in the future) may read building-photos from arbitrary paths.
2. **Work-order creation.** A separate concern from the memory-persist database write. May eventually integrate with external ticketing systems (Jira, ServiceNow).
3. **Notification dispatch.** Slack, email, in-app. Each channel has different APIs.

Three options were considered:

1. **Direct Python calls.** Each agent imports the relevant library and calls it. Simple. Fast. But: every agent now has authentication state, every agent must be sandboxed against arbitrary filesystem writes, and swapping `slack-sdk` for a different chat API requires changes in the agent code.
2. **Internal tool abstraction.** Define a `Tool` protocol; each tool is a Python class. Each agent receives the tools it needs via constructor injection. Better, but: still in-process; no isolation; no language flexibility; testing the workflow requires mocking tools.
3. **Model Context Protocol (MCP).** Each tool is a separate process speaking JSON-RPC over stdio. Servers are loaded once at workflow boot via `MCPConnectionManager`. Agents call tools through the manager, which routes by server name. Each server can be written in any language.

## Decision

Implement three MCP servers, one per category:

- `src/mcp_servers/filesystem_server.py` — sandboxed file reads/writes, restricted to `data/outputs/` and read-only access to `data/sample_photos/`
- `src/mcp_servers/workorder_server.py` — work-order CRUD, currently backed by the same SQLite DB as memory
- `src/mcp_servers/notification_server.py` — notification dispatch (currently logs only; ready to integrate Slack/email)

Each server is spawned as a subprocess at API startup (see `src/api/app.py::lifespan`). The connection manager (`src/mcp_clients/manager.py`) maintains a single asyncio event loop in a background thread and routes synchronous calls into it via `asyncio.run_coroutine_threadsafe`.

A background health monitor pings each server every 30 seconds via `list_tools()` (a no-op MCP call). After 3 consecutive failures, the server is marked unhealthy. The `/health` endpoint aggregates per-server status, suitable for Kubernetes readiness probes.

## Consequences

**Positive:**
- **Sandboxing.** The filesystem server is the only process with filesystem write permission. The workflow can't accidentally write outside the allowed directory.
- **Language flexibility.** A notification server could be rewritten in Node.js (where Slack SDK support is more mature) without changing the workflow.
- **Process isolation.** A misbehaving server (crash, deadlock) doesn't kill the workflow. The health monitor catches it; the workflow logs the failure and continues with degraded functionality.
- **Observability.** Every MCP call is wrapped in a Langfuse span (`mcp.{server}.{tool}`), nested under the agent that initiated it. Trace tree shows tool calls in context.
- **Loose coupling.** The workflow doesn't import any tool implementations. The MCP protocol is the contract.

**Negative:**
- **Subprocess overhead.** Each server is a separate Python process with its own interpreter, modules loaded, etc. Cold-start time at API boot is ~2-3 seconds per server.
- **Async/sync bridge complexity.** MCP's reference SDK is async. The workflow is sync. The bridging code in `MCPConnectionManager` is non-trivial — see the comment about the "anyio cancel scope" warning during teardown.
- **JSON-RPC overhead per call.** Tool calls cost ~10-50ms vs direct in-process calls. Negligible for the use case but real.

**Neutral:**
- The MCP servers in this project happen to share a database with the memory layer. Production deployments would likely separate concerns: work-order server backed by a real ticketing system, notification server backed by external channels.

## See Also

- `src/mcp_clients/manager.py` — connection management and health monitoring
- `src/mcp_clients/connections.py` — singleton accessor
- `src/mcp_servers/*` — three server implementations
- ADR-0008 (correlation IDs) — MCP calls inherit the request-scoped correlation ID