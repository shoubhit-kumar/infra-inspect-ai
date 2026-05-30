# Workflow Walkthrough

A node-by-node walk through the eight-node LangGraph workflow. For each node: what it reads, what it does, what it writes, what can go wrong, and where to look in the code.

For the high-level architecture, see [`architecture.md`](architecture.md). For the orchestration choice, see [ADR-0001](adr/0001-langgraph-over-langchain-pipelines.md).

---

## State

All nodes share a single `AgentState` instance, defined in `src/schemas/state.py`. It is a Pydantic model. Nodes read fields they need, mutate the instance, and return it. LangGraph handles the immutability semantics under the hood.

Key state fields:

| Field | Type | Set by | Used by |
|-------|------|--------|---------|
| `building_id` | str | caller | all |
| `photo_paths` | list[str] | caller | inspection |
| `inspector_notes` | str | caller | inspection, documentation |
| `request_id` | str | API caller (or "") | all (auto-propagated to logs) |
| `asset_memory` | dict | memory_recall | inspection, risk |
| `inspection_reports` | list[InspectionReport] | inspection | all downstream |
| `finding_classifications` | list[dict] | inspection | risk, documentation |
| `compliance_violations` | list[dict] | compliance | risk, workorder, documentation |
| `compliance_status` | ComplianceStatus | compliance | documentation |
| `risk_assessment` | dict | risk | workorder, documentation |
| `work_orders` | list[dict] | workorder | followup, memory_persist, documentation |
| `document` | dict | documentation | (terminal) |
| `report_path` | str | documentation | (returned to caller) |
| `followup_plan` | dict | followup | (terminal) |
| `memory_run_id` | int | memory_persist | (returned to caller) |
| `errors` | list[str] | any node | (returned to caller) |
| `trace` | Langfuse trace object | caller | all nodes (for span nesting) |

---

## Node 1: memory_recall

**Purpose:** Load any prior history for this building before inspection runs.

**Reads:** `state.building_id`
**Writes:** `state.asset_memory` (an `AssetMemory.model_dump()`)
**External calls:** SQLite via `AssetRepository.get_asset_memory()`
**Failure mode:** New building (no prior runs) → returns an empty `AssetMemory` with `total_inspections=0`. Not an error.

The returned memory snapshot includes:

- `summary`: total inspections, last inspection at, open/closed work-order counts, longest open issue age
- `recent_findings`: last 20 findings, ordered most-recent-first
- `open_work_orders`: oldest-first, for SLA breach detection
- `recently_closed_work_orders`: last 10 closed, for trend awareness

The Inspection Agent and Risk Agent both incorporate this into their prompts. The Risk Agent particularly uses "currently-open work orders from prior runs" to avoid duplicate work-order creation.

**Code:** `src/graph/workflow.py::memory_recall_node`
**Schema:** `src/schemas/memory.py::AssetMemory`

---

## Node 2: inspection

**Purpose:** Vision-LLM extraction of findings from each photo, plus classification of those findings against historical findings.

**Reads:** `state.photo_paths`, `state.inspector_notes`, `state.asset_memory`
**Writes:** `state.inspection_reports`, `state.finding_classifications`
**External calls:** Vision LLM (default Gemini), BGE embeddings (for change detection)
**Failure mode:** Per-photo errors are caught; the failing photo is skipped, other photos continue. Errors recorded in `state.errors`.

For each photo, the Inspection Agent:

1. Builds a prompt with the photo, inspector notes, and a compact history snippet
2. Calls the vision LLM with structured output (Pydantic `InspectionReport`)
3. Validates the response; retries up to 3 times on parse failure
4. Appends the validated report to `state.inspection_reports`

After all photos are processed, `_classify_against_history()` runs:

1. Embeds all new findings + historical findings using BGE (one batched call each)
2. For each new finding, finds the best-matching historical finding above the cosine threshold (0.65) and category gate
3. Classifies the result as `new`, `persisting`, `worsening`, or `improving` based on severity comparison
4. Falls back to word-overlap matching if embeddings fail to load

**Code:** `src/graph/workflow.py::inspection_node`, `src/agents/inspection.py`
**Schema:** `src/schemas/inspection.py`
**Related:** [ADR-0006: BGE semantic change detection](adr/0006-bge-semantic-change-detection.md)

---

## Conditional edge: should_run_compliance

**Purpose:** Skip compliance entirely if no findings were produced.

**Reads:** `state.inspection_reports`
**Returns:** `"compliance"` if any report has findings, otherwise `"memory_persist"`

Pure function. Unit-tested in `tests/test_workflow_helpers.py`.

**Rationale:** A photo with no findings (e.g., a clearly-OK exterior shot) needs no compliance check. Skipping saves an LLM call and the downstream RAG retrieval cycle.

---

## Node 3: compliance

**Purpose:** Ground each finding against actual building-code passages, producing citations with source and page.

**Reads:** `state.inspection_reports`
**Writes:** `state.compliance_violations`, `state.compliance_status` (via `_derive_status`)
**External calls:** RAG retrieval (FAISS + BM25 + reranker), LLM
**Failure mode:** Per-finding retrieval errors are caught; the finding gets no chunks (effectively zero violations attributed to it). Compliance call failure is logged and the agent continues.

For each finding:

1. Build a query string: `{category} {issue} {visual_evidence[:120]}`
2. Run the hybrid retriever (`src/rag/retriever.py::CodeRetriever.search()`):
   - FAISS dense retrieval → top 20
   - BM25 sparse retrieval → top 20
   - RRF fusion (k=60) → top 20
   - Cross-encoder reranking → top 5 with reranker score
3. Filter by `MIN_RETRIEVAL_SCORE` (empirically tuned to 0.05)
4. Pass retrieved chunks to the compliance LLM with the finding
5. LLM produces zero or more `ComplianceViolation`s, each citing one chunk

After all findings are processed:

- `_derive_status(state)` returns the overall ComplianceStatus:
  - UNKNOWN if no inspection reports
  - COMPLIANT if no violations
  - NON_COMPLIANT if any critical violation
  - PARTIAL if violations but none critical

**Code:** `src/graph/workflow.py::compliance_node`, `src/agents/compliance.py`
**Schema:** `src/schemas/compliance.py`
**Related:** [ADR-0003: Hybrid retrieval](adr/0003-hybrid-rag-with-rrf-and-reranker.md), [ADR-0004: Empirical threshold tuning](adr/0004-empirical-threshold-tuning.md)

---

## Conditional edge: should_run_risk

**Purpose:** Skip risk assessment if there are no findings to assess.

**Reads:** `state.inspection_reports`
**Returns:** `"risk"` if any findings exist, otherwise `"memory_persist"`

Same shape as `should_run_compliance`. Pure function, unit-tested.

---

## Node 4: risk

**Purpose:** Deduplicate findings (multiple photos may surface the same physical issue), assign severity-aware priorities, compute risk scores.

**Reads:** `state.inspection_reports`, `state.compliance_violations`, `state.asset_memory`, `state.finding_classifications`
**Writes:** `state.risk_assessment`
**External calls:** LLM
**Failure mode:** Errors caught, logged, appended to `state.errors`. Workflow continues with no risk assessment; workorder agent will skip.

The Risk Agent:

1. Formats findings, violations, and historical context into a single prompt
2. Calls the LLM to produce a `RiskAssessment` with a list of deduplicated `RiskedIssue` records
3. Defensively recomputes `risk_score = impact_score × probability_score` for each issue (logs warning if LLM math drifted)
4. Computes `highest_risk_category` server-side from the issues list (sum of risk_score per category, tie-break by issue count)
5. Tags the assessment with the actual model used (`"gemini:default"`, etc.)

The server-side `highest_risk_category` computation replaces a previous LLM-populated field that was unreliable. See [ADR-0005](adr/0005-server-side-aggregation-over-llm.md).

**Code:** `src/graph/workflow.py::risk_node`, `src/agents/risk.py`
**Schema:** `src/schemas/risk.py`

---

## Node 5: workorder

**Purpose:** Translate risk-prioritized issues into actionable work orders with team routing, cost estimates, and SLA deadlines.

**Reads:** `state.risk_assessment`
**Writes:** `state.work_orders`, `state.workorder_summary`
**External calls:** LLM
**Failure mode:** Errors caught. No work orders created. Follow-up agent will skip.

The Work Order Agent:

1. Reads each `RiskedIssue` from the risk assessment
2. Maps category → assigned team via static mapping (`electrical` → `electrical_team`, etc.)
3. Maps priority (P1/P2/P3/P4) → SLA hours (4/24/168/720)
4. Has the LLM estimate cost in INR and hours
5. Marks `requires_approval=True` for P1 work orders above a cost threshold

The work orders are not yet persisted at this stage. Persistence happens in `memory_persist`, optionally via the work-order MCP server.

**Code:** `src/graph/workflow.py::workorder_node`, `src/agents/workorder.py`
**Schema:** `src/schemas/workorder.py`

---

## Node 6: documentation

**Purpose:** Compose a polished Markdown audit report.

**Reads:** Full state
**Writes:** `state.document`, `state.report_path`
**External calls:** LLM, MCP filesystem server (for file write)
**Failure mode:** Errors caught. Workflow continues; consumer sees `state.report_path` is None and `state.errors` populated.

The Documentation Agent:

1. Builds context: building ID, audience, findings, violations, risk assessment, work orders, memory summary
2. Calls the LLM to produce an `InspectionDocument` with executive summary, sections, and detailed findings
3. Renders to Markdown with proper headings and tables
4. Writes the file via MCP filesystem server (sandboxed to `data/outputs/`)
5. Records the path on state

The audience parameter (`ReportAudience.OPERATIONAL` by default) shifts the tone: operational reports include cost/SLA details; executive reports emphasize risk and compliance status.

**Code:** `src/graph/workflow.py::documentation_node`, `src/agents/documentation.py`
**Schema:** `src/schemas/documentation.py`

---

## Node 7: followup

**Purpose:** Decide who needs to be notified and what re-inspections to schedule.

**Reads:** Full state
**Writes:** `state.followup_plan`
**External calls:** LLM, MCP notification server (for dispatch)
**Failure mode:** No work orders → skip entirely with `followup.skip` log. Errors during dispatch caught, recorded.

The Follow-up Agent:

1. For each work order, decides notification audience and urgency:
   - P1 + assigned team → Slack URGENT
   - P1 + building manager → email URGENT
   - P1 + executive → in-app notification
   - P2/P3 → email normal
   - All work orders → summary email to compliance officer
2. Dispatches each notification via the MCP notification server
3. Records each dispatched notification in the memory store
4. Plans scheduled re-inspections based on SLA deadlines

Returned `FollowUpPlan` contains `notifications: list[Notification]` and `scheduled_tasks: list[ScheduledTask]`.

**Code:** `src/graph/workflow.py::followup_node`, `src/agents/followup.py`
**Schema:** `src/schemas/followup.py`

---

## Node 8: memory_persist

**Purpose:** Record the entire run in the asset memory database. Future inspections of this building will see this run.

**Reads:** Full state
**Writes:** `state.memory_run_id`
**External calls:** SQLite via `AssetRepository.record_inspection_run`, MCP work-order server (for WO persistence)
**Failure mode:** Persistence errors are logged with ERROR. `memory_run_id` remains None.

The persistence is a single SQLAlchemy transaction:

1. Flatten `inspection_reports` into a list of `FindingRecord` dicts (one row per finding)
2. Insert into `inspection_runs` with `building_id`, counts, status, `request_id` (from state)
3. Insert each finding linked to the new run
4. For each work order: try MCP work-order server first; fall back to direct `repo.create_standalone_work_order()` if MCP fails
5. Return the new `run_id`

The `request_id` from state is stored on the row, enabling SQL queries like `SELECT * FROM inspection_runs WHERE request_id = 'req_xyz'`.

**Code:** `src/graph/workflow.py::memory_persist_node`
**Schema:** `src/schemas/memory.py`
**Related:** [ADR-0008: Correlation IDs](adr/0008-correlation-ids-end-to-end.md)

---

## Routing helpers

Two pure functions decide conditional edges. Both are tested in `tests/test_workflow_helpers.py`.

```python
def should_run_compliance(state: AgentState) -> str:
    return "compliance" if any(r.findings for r in state.inspection_reports) else "memory_persist"

def should_run_risk(state: AgentState) -> str:
    has_any = bool(state.inspection_reports) and any(
        r.findings for r in state.inspection_reports
    )
    return "risk" if has_any else "memory_persist"
```

Pure functions like these are the testability win of LangGraph. Without conditional edges as first-class citizens, the same logic would be tangled inside node code.

---

## Tracing

Each node is wrapped in a `span_node` context manager from `src/tracing/setup.py`. The span:

- Starts when the node begins
- Inherits from the workflow's root trace
- Records the node's input data (compact summary)
- Updates with output data when the node completes
- Marks `level="ERROR"` if an exception fires

Retrieval calls within `compliance` are wrapped in `span_retrieval`. MCP calls within `documentation`, `followup`, and `memory_persist` are wrapped in `span_mcp_call`. LLM calls within each agent are wrapped in `observe_llm`. All these spans nest under the parent agent's span automatically.

The result is a tree like the one in the README hero image: the workflow span has 8 children (one per node), each of which has 1+ grandchildren (LLM call, RAG retrieval, MCP tool call).

---

## What happens when something goes wrong

The error-handling philosophy is: **a failure in one node doesn't kill the workflow**. Each node catches its own exceptions, logs them, appends to `state.errors`, and returns. Downstream nodes adapt to missing inputs.

Examples:

- Inspection agent fails on photo 2 of 5 → other photos still processed; 4 reports in state
- Compliance LLM rate-limits → no violations produced; `compliance_status` falls through to UNKNOWN; risk agent runs on findings alone
- MCP notification server crashes → notification call raises; followup_node catches, logs `followup.notify_failed`, continues with remaining notifications
- Memory persist fails → `memory_run_id` is None; workflow returns with errors; client sees both the result and the persistence failure

This is appropriate for an inspection system where partial information is better than total failure. A different domain (e.g., financial transactions) would require all-or-nothing semantics.

---

## See also

- [`architecture.md`](architecture.md) — high-altitude system view
- [`rag-pipeline.md`](rag-pipeline.md) — retrieval architecture deep-dive
- [`observability.md`](observability.md) — tracing, logging, correlation IDs
- ADR index — design decisions