# Observability

How the system makes itself debuggable. Three components, deeply integrated: Langfuse traces, structured logs, and end-to-end correlation IDs.

For the correlation-ID architectural decision, see [ADR-0008](adr/0008-correlation-ids-end-to-end.md).

---

## Goals

When something goes wrong in production, an operator needs to answer:

- **What happened?** Which agent failed, which retrieval returned bad chunks, which LLM call hung.
- **Why?** The inputs to the failure, the state at that point, the error message and stack trace.
- **Who else is affected?** Other concurrent requests, downstream consumers.
- **When did it start?** Trend over time; is this the first failure or the hundredth.

These questions require three different lenses: per-request (traces), per-component (logs), and aggregate (metrics). This system implements the first two well; aggregate metrics are deferred.

---

## Three layers

### Layer 1: Langfuse traces

Every workflow run produces a tree of spans:
```
infra-inspect-workflow  [root trace, 3m 22s]
├── memory_recall  [45ms]
├── inspection  [5.2s]
│   └── llm.gemini.generation  [4.8s]
├── compliance  [1m 47s]
│   ├── rag.retrieve  [12.4s, finding 0]
│   │   └── reranker.cross_encode  [11.2s]
│   ├── rag.retrieve  [15.2s, finding 1]
│   ├── rag.retrieve  [11.8s, finding 2]
│   ├── rag.retrieve  [14.3s, finding 3]
│   ├── rag.retrieve  [10.6s, finding 4]
│   └── llm.gemini.generation  [28.4s]
├── risk  [7.1s]
│   └── llm.gemini.generation  [6.9s]
├── workorder  [5.8s]
│   └── llm.gemini.generation  [5.6s]
├── documentation  [15.4s]
│   ├── llm.gemini.generation  [12.1s]
│   └── mcp.filesystem.write_file  [1.2s]
├── followup  [18.2s]
│   ├── llm.gemini.generation  [10.5s]
│   ├── mcp.notification.send  [0.4s]  (×5)
│   └── mcp.workorder.create_work_order  [0.3s]  (×5)
└── memory_persist  [1.1s]
```
**Implementation:** `src/tracing/setup.py`

The setup module provides four context managers:

| Manager | When to use | What it does |
|---------|------------|--------------|
| `trace_workflow_run()` | Wraps the entire workflow invocation | Creates the root trace, tags with `session_id` and `request_id`, flushes on exit |
| `span_node()` | Wraps each LangGraph node | Creates a child span under the workflow trace, sets it as current for nested code |
| `span_retrieval()` | Wraps each RAG retrieval call | Creates a grandchild span under the active agent |
| `span_mcp_call()` | Wraps each MCP tool invocation | Creates a grandchild span under the active agent |
| `observe_llm()` | Wraps each LLM call | Creates a generation span (Langfuse-specific; carries cost/token info) |

The "current span" is held in a `ContextVar` (`_current_span`). When code beneath a span starts a new sub-span, it automatically nests under the parent without needing to thread the span object through call signatures.

**Configuration:**
```
LANGFUSE_PUBLIC_KEY=pk_...
LANGFUSE_SECRET_KEY=sk_...
LANGFUSE_HOST=https://jp.cloud.langfuse.com   # or your self-hosted URL
```
If credentials are absent, `get_langfuse()` returns `None` and all the context managers become no-ops. The workflow runs unchanged — Langfuse is graceful degradation, not a hard dependency.

**Session correlation:**

Every trace is tagged with `session_id = X-Request-ID`. In the Langfuse UI, filter `Sessions → portfolio-test-001` and all traces from that request appear together. This matters when a single API call produces multiple LLM calls — you want them grouped.

**Error tagging:**

If a span's code raises, the span's `level` is set to `ERROR` and the exception message is recorded in `status_message`. Failed spans render red in the Langfuse UI. Filtering by `level=ERROR` shows just the failures.

---

### Layer 2: Structured logs

Every log line is a JSON-renderable structured event, not a string. Implemented with `structlog`.

**Implementation:** `src/utils/logging.py`

The processor chain:

```python
processors=[
    structlog.contextvars.merge_contextvars,
    _add_request_id,                                # injects request_id from ContextVar
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.dev.ConsoleRenderer(colors=True),     # for stdout (Rich-colored)
]
```

For production, swap the final `ConsoleRenderer` with `structlog.processors.JSONRenderer()` to emit machine-readable JSON to stdout. A log shipper (Fluent Bit, Vector, etc.) picks up stdout, ships to Loki/CloudWatch/Datadog, and operators can query.

**Example log lines:**
```
[10:35:30] INFO  memory.engine_ready     path=data\memory\asset_memory.sqlite
[10:35:32] INFO  memory.recall           building_id=BLDG-001 open_work_orders=82 total_inspections=109 request_id=portfolio-test-001
[10:35:34] INFO  llm.init                provider=gemini temperature=0.1 request_id=portfolio-test-001
[10:35:35] INFO  inspection.start        photo=data\sample_photos\electrical_panel_unsafe.png request_id=portfolio-test-001
[10:35:42] INFO  inspection.done         findings_count=5 photo=... request_id=portfolio-test-001
[10:35:42] INFO  classification.done     persisting=5 request_id=portfolio-test-001
```
Every line during a request carries `request_id`. The auto-injection happens in the `_add_request_id` processor, which reads from `src.api.request_context.get_request_id()`. No per-call-site change needed in 50+ existing log statements.

**Naming convention:**

Log event names use dot-namespacing: `module.action`. Examples:

- `memory.engine_ready`
- `compliance.start`
- `compliance.retrieved`
- `compliance.done`
- `mcp.manager.ready`
- `mcp.health.status_change`

Standardizing names makes log filtering reliable: `grep "compliance\." logs/*.log` shows all compliance-related events across the system.

---

### Layer 3: Correlation IDs

The thread that ties Layer 1 and Layer 2 together.

**The header:** `X-Request-ID` (the de facto standard).

**The flow:**

1. Client (or middleware) supplies `X-Request-ID: req_abc123` on the HTTP request.
2. `src/api/app.py::correlation_id_middleware` reads the header (or generates one), sets `request_id_var.set(rid)` (a `ContextVar`).
3. All code in the request scope reads from this ContextVar:
   - The structlog processor (Layer 2) auto-injects it.
   - The Langfuse `trace_workflow_run` (Layer 1) tags it as `session_id` and `metadata.request_id`.
4. FastAPI's `BackgroundTasks` runs the workflow in a thread. ContextVars do NOT auto-propagate to threads. The route handler captures the rid synchronously and passes it to `_run_workflow_job`, which re-sets it on the worker thread.
5. The workflow propagates rid through `AgentState.request_id`.
6. `memory_persist_node` writes rid to the `inspection_runs.request_id` column.
7. Response headers include `X-Request-ID: req_abc123`, so the client can store it.

**The result:** One header lets you trace any failed request through:

- `grep "request_id=req_abc123" logs/*.log` — every log line
- Langfuse UI → filter session=req_abc123 — every span
- `SELECT * FROM inspection_runs WHERE request_id='req_abc123'` — the DB row
- Response header on the original 200/202 reply

**Why the background-thread re-set?**

`asyncio.create_task` inherits ContextVars from the caller's context. `threading.Thread` does not. FastAPI's `BackgroundTasks` uses threads. So the explicit re-set in `_run_workflow_job` is required. The code comment documents this gotcha.

---

## Health monitoring

Independent of per-request observability, the system continuously monitors the three MCP servers.

**Implementation:** `src/mcp_clients/manager.py`

A background thread runs a ping loop every 30 seconds:

```python
while not self._ping_stop.is_set():
    for name in list(self._health.keys()):
        self._ping_one(name)
    self._ping_stop.wait(timeout=HEALTH_CHECK_INTERVAL_SEC)
```

Each `_ping_one` calls `client.list_tools()` (the cheapest possible MCP call) with a 15-second timeout. The result updates the per-server `ServerHealth` dataclass:

- `status`: `healthy` / `degraded` / `unhealthy` / `unknown`
- `last_check_at`, `last_success_at`: ISO timestamps
- `last_error`: most recent error message
- `consecutive_failures`: counter; resets on success
- `total_pings`: cumulative

**Status transitions:**

- One failure → `degraded`, log `WARNING`
- 3 consecutive failures → `unhealthy`, log `ERROR`
- Recovery (success after failures) → `healthy`, log `INFO`

**Exposure:**

The `/health` endpoint returns the snapshot:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "workflow_loaded": true,
  "mcp_servers_connected": ["filesystem", "workorder", "notification"],
  "mcp_servers": [
    {
      "name": "filesystem",
      "status": "healthy",
      "last_check_at": "2026-05-29T03:21:53.747Z",
      "last_success_at": "2026-05-29T03:21:53.747Z",
      "last_error": null,
      "consecutive_failures": 0,
      "total_pings": 47
    }
  ]
}
```

**Aggregate status:**

The top-level `status` field rolls up:
- `ok` — all servers healthy or unknown (boot state)
- `degraded` — any server is degraded
- `unhealthy` — any server is unhealthy

A Kubernetes readiness probe pointing at `/health` and looking for `status == "ok"` will route traffic away from a degraded instance. A liveness probe might use a stricter check (e.g., reject if any server is `unhealthy`).

---

## Practical operator playbook

**Symptom:** A user reports their inspection at 14:32 IST produced wrong work orders.

**With this system:**

1. Get the `X-Request-ID` from the user's response header. Suppose it's `req_a4f78e3edbbf`.
2. Filter logs: `grep "request_id=req_a4f78e3edbbf" logs/api.log` → every log line in chronological order.
3. Open Langfuse UI, search sessions for `req_a4f78e3edbbf` → full trace tree.
4. Query DB: `SELECT * FROM inspection_runs WHERE request_id = 'req_a4f78e3edbbf';` → the persisted state.
5. Inspect agent prompts and LLM responses in the Langfuse trace's generation spans.
6. If the LLM was at fault, look at the input prompt and the model's actual output text.

**Without this system:**

1. Try to correlate timestamps. Multiple requests at 14:32 — which logs belong to this one?
2. No trace tree. Try to assemble the agent flow from sequential log lines.
3. No persisted state link. Hope the DB row is identifiable by timestamp.

The difference is hours vs. minutes of debugging time.

---

## What's not implemented

**Metrics.** No counters or histograms emitted. Cost: adding Prometheus would require ~50 lines of decoration. Not yet done because the system isn't aggregating yet — single instance, no historical comparison need.

**Distributed tracing.** Langfuse correlates within a process. If the system were split into multiple services (e.g., a separate vector-store service), traces would need to propagate via OTEL or similar. The pattern would extend cleanly; not yet needed.

**Log aggregation.** Logs go to stdout. In production, a log shipper would forward to Loki/Datadog/CloudWatch. Not yet configured — for the portfolio demo, terminal-visible logs are sufficient.

**Alerting.** No PagerDuty, no Slack alerts on errors. The /health endpoint exists to support orchestrator-level alerting (Kubernetes restart on probe failure). Application-level alerting deferred.

---

## See also

- [ADR-0008: Correlation IDs](adr/0008-correlation-ids-end-to-end.md)
- `src/api/request_context.py` — ContextVar
- `src/api/app.py::correlation_id_middleware` — middleware
- `src/utils/logging.py::_add_request_id` — structlog processor
- `src/tracing/setup.py` — Langfuse helpers
- `src/mcp_clients/manager.py` — health monitor
- `src/api/routes/health.py` — `/health` endpoint