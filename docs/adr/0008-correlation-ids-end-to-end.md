# ADR-0008: Propagate X-Request-ID through every layer

**Status:** Accepted
**Date:** 2026-05-26
**Deciders:** Project author

## Context

The system has multiple layers that produce observability output: HTTP request/response logs, structured application logs, Langfuse trace spans, MCP tool calls, and SQLite inspection-run rows. When something goes wrong with a specific request, an operator needs to:

1. Find the relevant log lines (filtered from concurrent requests)
2. Find the corresponding Langfuse trace
3. Find the DB row for the inspection run
4. Find the response that was sent to the client

Without a shared identifier across these layers, this requires manual correlation by timestamp — which is error-prone under concurrent load and unreliable across distributed components.

Three options were considered:

1. **No correlation.** Operators correlate manually. Acceptable for single-developer demos. Fails under any operational pressure.
2. **Log timestamps only.** Better than nothing but loses fidelity under concurrent requests. Two requests arriving in the same millisecond are indistinguishable.
3. **Explicit correlation ID propagated through all layers.** Industry standard. Cost is moderate; payoff is significant.

## Decision

Implement end-to-end correlation IDs using the `X-Request-ID` HTTP header convention.

The implementation has five layers:

1. **Middleware.** FastAPI middleware (`src/api/app.py`) reads `X-Request-ID` from the request; if absent, generates `req_<12-hex>`. Sets a `ContextVar` (`src/api/request_context.py::request_id_var`). Mirrors the ID back in the response header.

2. **Logging.** A structlog processor (`src/utils/logging.py::_add_request_id`) reads the ContextVar and injects `request_id` into every log line emitted during the request. No per-call-site change is needed in 50+ existing log statements.

3. **Background task propagation.** FastAPI's `BackgroundTasks` runs work in a thread, and ContextVars don't auto-propagate to threads. The route handler captures the ID synchronously and passes it to the background function, which re-sets it on the worker thread. See `src/api/routes/inspections.py::_run_workflow_job`.

4. **Workflow state.** The `AgentState` schema gains a `request_id: str = ""` field. The route handler initializes it from the captured ID. Workflow nodes read it from state when needed.

5. **Downstream.** The Langfuse trace is tagged with `session_id=<request_id>` so all spans for a request can be filtered together in the Langfuse UI. The inspection-run DB row stores `request_id` in a dedicated column for SQL-based audit.

The result: one HTTP header lets an operator trace any request through logs, traces, database, and back to the original response.

## Consequences

**Positive:**
- **Cross-layer correlation.** `grep request_id=req_abc123 logs/*` returns all log lines for that request. `WHERE request_id = 'req_abc123'` returns the DB row. Langfuse UI filter on `session_id=req_abc123` shows all spans. Same ID throughout.
- **Client-side tracing.** Clients that supply their own `X-Request-ID` (for distributed tracing across services) preserve it. The system never overwrites a client-supplied ID.
- **Graceful for non-API runs.** CLI/script invocations produce `request_id=""`, which the logging processor cleanly skips (no spurious `request_id=""` in CLI logs). The DB column allows NULL for these.
- **Zero per-call-site cost.** Once the middleware and processor are in place, no existing code needs to change to start emitting correlated logs.

**Negative:**
- **The background-task propagation is subtle.** ContextVars are a Python idiom many engineers don't recognize. The "ContextVars don't cross thread boundaries" gotcha is documented in code comments but is easy to forget.
- **Manual DB migration.** Adding the `request_id` column to an existing SQLite DB requires `ALTER TABLE`. For fresh DBs, SQLAlchemy creates it via `create_all`. The migration is documented in the README.

**Neutral:**
- **Distributed tracing potential.** This system runs in one process today. If split into multiple services, the same correlation ID could propagate through gRPC headers, message-queue metadata, etc. The pattern scales.

## See Also

- `src/api/app.py` — middleware
- `src/api/request_context.py` — ContextVar
- `src/utils/logging.py::_add_request_id` — structlog processor
- `src/api/routes/inspections.py::_run_workflow_job` — background task propagation
- `src/tracing/setup.py::trace_workflow_run` — Langfuse session_id tagging
- `docs/observability.md` — full observability deep-dive