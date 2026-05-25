"""Streamlit UI for infra-inspect-ai.

Talks to the FastAPI backend (run with `python -m scripts.run_api`).
Three tabs:
  1. Run Inspection  - upload photos, submit job, poll until done, show results
  2. Building History - recall memory + past inspections for a building ID
  3. About            - what is this thing

Usage:
    streamlit run app.py
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

# ---------- Config ----------
API_BASE = "http://127.0.0.1:8000"
POLL_INTERVAL_SEC = 3
POLL_TIMEOUT_SEC = 600  # 10 minutes
UPLOAD_DIR = Path("data/incoming_uploads")


st.set_page_config(
    page_title="infra-inspect-ai",
    page_icon="🏢",
    layout="wide",
)


# ============================================================================
# API client helpers
# ============================================================================

def api_health() -> dict | None:
    """Return health payload or None if API is down."""
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def api_submit_inspection(building_id: str, photo_paths: list[str], notes: str) -> dict:
    """Submit an inspection job. Returns {job_id, status, poll_url}."""
    r = requests.post(
        f"{API_BASE}/inspections",
        json={
            "building_id": building_id,
            "photo_paths": photo_paths,
            "inspector_notes": notes,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def api_get_job(job_id: str) -> dict:
    r = requests.get(f"{API_BASE}/jobs/{job_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def api_get_memory(building_id: str) -> dict:
    r = requests.get(f"{API_BASE}/buildings/{building_id}/memory", timeout=10)
    r.raise_for_status()
    return r.json()


def api_list_inspections(building_id: str, limit: int = 20) -> dict:
    r = requests.get(
        f"{API_BASE}/buildings/{building_id}/inspections",
        params={"limit": limit},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# ============================================================================
# File handling
# ============================================================================

def save_uploaded_files(uploaded_files: list, batch_id: str) -> list[str]:
    """Persist uploaded files to disk, return server-relative paths."""
    target_dir = UPLOAD_DIR / batch_id
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []
    for uf in uploaded_files:
        path = target_dir / uf.name
        path.write_bytes(uf.getvalue())
        # Use forward slashes for path portability
        saved_paths.append(str(path).replace("\\", "/"))
    return saved_paths


# ============================================================================
# UI - Sidebar
# ============================================================================

with st.sidebar:
    st.title("infra-inspect-ai")
    st.caption("AI building inspection workflow")

    health = api_health()
    if health is None:
        st.error("API unreachable\nStart it: `python -m scripts.run_api`")
    else:
        st.success("API healthy")
        st.caption(f"MCP servers: {', '.join(health['mcp_servers_connected'])}")
        st.caption(f"Version: {health['version']}")

    st.divider()
    st.markdown(
        "**Stack**  \n"
        "Gemini, LangGraph, FastAPI, FAISS+BM25 hybrid RAG, MCP, SQLite memory, Langfuse traces"
    )


# ============================================================================
# UI - Tabs
# ============================================================================

tab_run, tab_history, tab_about = st.tabs([
    "Run Inspection",
    "Building History",
    "About",
])


# ----------------------------------------------------------------------------
# Tab 1: Run Inspection
# ----------------------------------------------------------------------------

with tab_run:
    st.header("Run a new inspection")
    st.caption("Upload photos, identify the building, submit. Workflow runs in the background.")

    col1, col2 = st.columns([1, 2])
    with col1:
        building_id = st.text_input("Building ID", value="BLDG-001")
        notes = st.text_area("Inspector notes (optional)", value="", height=100)

    with col2:
        uploaded = st.file_uploader(
            "Photos",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            help="Drop or browse to select inspection photos.",
        )
        if uploaded:
            st.caption(f"{len(uploaded)} photo(s) selected")
            preview_cols = st.columns(min(len(uploaded), 4))
            for i, uf in enumerate(uploaded[:4]):
                with preview_cols[i]:
                    st.image(uf, caption=uf.name, width="stretch")
            if len(uploaded) > 4:
                st.caption(f"(+ {len(uploaded) - 4} more)")

    submit_disabled = not (uploaded and building_id and health)
    if st.button("Run Inspection", type="primary", disabled=submit_disabled):
        with st.status("Submitting job...", expanded=True) as status:
            batch_id = f"upload_{uuid.uuid4().hex[:10]}"
            paths = save_uploaded_files(uploaded, batch_id)
            st.write(f"Saved {len(paths)} photo(s) to {UPLOAD_DIR / batch_id}")

            job = api_submit_inspection(building_id, paths, notes)
            job_id = job["job_id"]
            st.write(f"Job submitted: `{job_id}`")
            status.update(label=f"Job {job_id} running...", state="running")

            # Poll until done or timeout
            start = time.time()
            result = None
            while time.time() - start < POLL_TIMEOUT_SEC:
                resp = api_get_job(job_id)
                state = resp["status"]

                elapsed = int(time.time() - start)
                if state == "succeeded":
                    status.update(label=f"Completed in {elapsed}s", state="complete")
                    result = resp["result"]
                    break
                if state == "failed":
                    status.update(label=f"Job failed: {resp.get('error', '')}", state="error")
                    break

                st.write(f"  [{elapsed:>3}s] status: {state}")
                time.sleep(POLL_INTERVAL_SEC)

            else:
                status.update(label="Polling timed out", state="error")

        if result:
            st.success(f"Inspection complete for {result['building_id']}")

            # ---- Summary metrics ----
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Photos analyzed", result["photos_analyzed"])
            m2.metric("Findings", result["findings_count"])
            m3.metric("Violations", result["violations_count"])
            m4.metric("Risk issues", result["risk_issues_count"])
            m5.metric("Work orders", len(result["work_orders"]))

            badge_color = "red" if result["compliance_status"] == "non_compliant" else "green"
            st.markdown(
                f"**Compliance status:** :{badge_color}[{result['compliance_status']}]"
            )

            # ---- Work orders ----
            if result["work_orders"]:
                st.subheader("Work orders")
                wo_data = [
                    {
                        "Priority": w["priority"],
                        "Title": w["title"],
                        "Team": w["assigned_team"],
                        "Cost (INR)": f"₹{int(w['estimated_cost_inr']):,}",
                        "Approval?": "yes" if w["requires_approval"] else "",
                        "SLA": w["sla_deadline"],
                    }
                    for w in result["work_orders"]
                ]
                st.dataframe(wo_data, hide_index=True, width="stretch")

            # ---- Report download ----
            if result.get("report_path"):
                report_path = Path(result["report_path"])
                if report_path.exists():
                    st.download_button(
                        label="Download full report (Markdown)",
                        data=report_path.read_text(encoding="utf-8"),
                        file_name=report_path.name,
                        mime="text/markdown",
                    )
                else:
                    st.warning(f"Report file not found at {report_path}")

            # ---- Errors ----
            if result.get("errors"):
                with st.expander("Non-fatal errors during run"):
                    for e in result["errors"]:
                        st.code(e, language=None)


# ----------------------------------------------------------------------------
# Tab 2: Building History
# ----------------------------------------------------------------------------

with tab_history:
    st.header("Building history")
    st.caption("Asset memory and past inspections")

    bid = st.text_input("Building ID", value="BLDG-001", key="history_bid")
    if st.button("Look up", disabled=not (bid and health)):
        with st.spinner("Recalling memory..."):
            memory = api_get_memory(bid)
            history = api_list_inspections(bid, limit=20)

        # ---- Memory summary ----
        st.subheader("Memory summary")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total inspections", memory["total_inspections"])
        c2.metric("Open work orders", memory["open_work_orders"])
        c3.metric("Closed", memory["closed_work_orders"])
        c4.metric("Oldest open (days)", memory["longest_open_issue_days"])

        if memory["last_inspection_at"]:
            st.caption(f"Last inspection: {memory['last_inspection_at']}")

        # ---- Recent findings ----
        if memory["recent_findings"]:
            with st.expander(f"Recent findings ({len(memory['recent_findings'])})"):
                rows = [
                    {
                        "When": f.get("inspected_at", ""),
                        "Issue": f.get("issue", ""),
                        "Severity": f.get("severity", ""),
                        "Category": f.get("category", ""),
                    }
                    for f in memory["recent_findings"]
                ]
                st.dataframe(rows, hide_index=True, width="stretch")

        # ---- Past inspections ----
        st.subheader(f"Past {history['total']} inspection runs")
        if history["inspections"]:
            rows = [
                {
                    "Run ID": r["run_id"],
                    "Started": r["started_at"],
                    "Status": r["compliance_status"],
                    "Findings": r["finding_count"],
                    "Violations": r["violation_count"],
                }
                for r in history["inspections"]
            ]
            st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.info("No inspections recorded for this building.")


# ----------------------------------------------------------------------------
# Tab 3: About
# ----------------------------------------------------------------------------

with tab_about:
    st.header("About this project")
    st.markdown(
        """
**infra-inspect-ai** is a production-grade demonstration of agentic AI for
building inspection workflows.

**Six-agent workflow (LangGraph)**
1. **Inspection** — vision model analyzes photos for safety findings
2. **Compliance** — grounds findings against building codes via hybrid RAG (FAISS + BM25 + cross-encoder rerank, 24,915 chunks)
3. **Risk** — aggregates per-finding risks into prioritized issue list
4. **Work Orders** — generates SLA-aware tickets with team routing and cost estimates
5. **Documentation** — produces audience-aware reports (operational / executive)
6. **Follow-up** — schedules re-inspections and dispatches notifications via MCP servers

**Infrastructure**
- Three MCP servers: filesystem, work-order, notification
- SQLite asset memory with change detection (worsening / improving / persisting)
- Full-stack Langfuse tracing: workflow → agent → LLM → RAG → MCP spans
- RAGAS-style retrieval evals with threshold tuning

**Architecture**
- FastAPI for HTTP, with async job submission for long-running workflows
- Streamlit for the demo UI (this page)
- Pluggable LLM router supports Gemini, Anthropic Claude, IBM Watsonx
        """
    )