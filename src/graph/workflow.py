"""Full multi-agent workflow with memory.

memory_recall -> inspection -> compliance? -> risk? -> workorder
              -> documentation -> followup -> memory_persist -> END
"""
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.compliance import ComplianceAgent
from src.agents.documentation import DocumentationAgent
from src.agents.followup import FollowUpAgent
from src.agents.inspection import InspectionAgent
from src.agents.risk import RiskAgent
from src.agents.workorder import WorkOrderAgent
from src.memory.change_detection import classify_findings
from src.memory.repository import AssetRepository
from src.schemas.documentation import ReportAudience
from src.schemas.enums import ComplianceStatus
from src.schemas.memory import AssetMemory, HistoricalFinding
from src.schemas.state import AgentState
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ---------- Memory nodes (Day 10) ----------

def memory_recall_node(state: AgentState) -> AgentState:
    """First node: load any prior memory for this building."""
    from src.tracing.setup import span_node
    with span_node("memory_recall", trace=state.trace, input_data={"building_id": state.building_id}) as span:
        try:
            repo = AssetRepository()
            memory = repo.get_asset_memory(state.building_id)
            state.asset_memory = memory.model_dump(mode="json")
            logger.info(
                "memory.recall",
                building_id=state.building_id,
                total_inspections=memory.summary.total_inspections,
                open_work_orders=memory.summary.open_work_orders,
            )
            if span:
                span.update(output={
                    "total_inspections": memory.summary.total_inspections,
                    "open_work_orders": memory.summary.open_work_orders,
                })
        except Exception as e:
            logger.error("memory.recall_failed", error=str(e))
            state.errors.append(f"memory recall failed: {e}")
    return state


def memory_persist_node(state: AgentState) -> AgentState:
    """Last node: write findings + work orders to persistent storage."""
    from src.tracing.setup import span_node
    with span_node("memory_persist", trace=state.trace) as span:
        try:
            repo = AssetRepository()

            flat_findings: list[dict[str, Any]] = []
            for report in state.inspection_reports:
                photo_name = Path(report.photo_path).name
                for f in report.findings:
                    flat_findings.append(
                        {
                            "photo_filename": photo_name,
                            "issue": f.issue,
                            "severity": f.severity.value,
                            "category": f.category.value,
                            "location_hint": f.location_hint,
                            "visual_evidence": f.visual_evidence,
                            "confidence": f.confidence,
                        }
                    )

            run_id = repo.record_inspection_run(
                building_id=state.building_id,
                inspector_notes=state.inspector_notes,
                photo_count=len(state.inspection_reports),
                finding_count=len(flat_findings),
                violation_count=len(state.compliance_violations),
                compliance_status=state.compliance_status.value,
                findings=flat_findings,
                work_orders=[],
            )
            state.memory_run_id = run_id

            from src.mcp_clients.connections import get_mcp
            mcp = get_mcp()

            for wo in state.work_orders:
                if mcp is not None:
                    try:
                        mcp.call_tool(
                            "workorder",
                            "create_work_order",
                            {
                                "building_id": state.building_id,
                                "issue_id": wo["issue_id"],
                                "title": wo["title"],
                                "description": wo.get("description", ""),
                                "category": wo["category"],
                                "priority": wo["priority"],
                                "assigned_team": wo["assigned_team"],
                                "estimated_cost_inr": float(wo["estimated_cost_inr"]),
                                "estimated_hours": float(wo["estimated_hours"]),
                                "sla_deadline": wo["sla_deadline"],
                                "requires_approval": bool(wo.get("requires_approval", False)),
                            },
                        )
                        continue
                    except Exception as e:
                        logger.warning(
                            "memory.workorder_mcp_failed",
                            wo=wo.get("issue_id"),
                            error=str(e),
                            fallback="repo direct",
                        )
                repo.create_standalone_work_order(state.building_id, wo)

            logger.info(
                "memory.persisted",
                run_id=run_id,
                findings=len(flat_findings),
                work_orders=len(state.work_orders),
                via_mcp=mcp is not None,
            )
            if span:
                span.update(output={
                    "run_id": run_id,
                    "findings": len(flat_findings),
                    "work_orders": len(state.work_orders),
                })
        except Exception as e:
            logger.error("memory.persist_failed", error=str(e))
            state.errors.append(f"memory persist failed: {e}")
    return state


def inspection_node(state: AgentState) -> AgentState:
    """Run InspectionAgent for every photo."""
    from src.tracing.setup import span_node
    with span_node(
        "inspection",
        trace=state.trace,
        input_data={"photos": len(state.photo_paths)},
    ) as span:
        history_text = _format_history_for_inspection(state)

        agent = InspectionAgent()
        for photo_path in state.photo_paths:
            try:
                report = agent.run(
                    Path(photo_path),
                    inspector_notes=state.inspector_notes,
                    history_text=history_text,
                )
                state.inspection_reports.append(report)
            except Exception as e:
                logger.error("inspection.error", photo=photo_path, error=str(e))
                state.errors.append(f"inspection failed for {photo_path}: {e}")

        state.finding_classifications = _classify_against_history(state)

        total_findings = sum(len(r.findings) for r in state.inspection_reports)
        if span:
            span.update(output={
                "total_findings": total_findings,
                "classifications": {
                    s: sum(1 for c in state.finding_classifications if c["status"] == s)
                    for s in ("new", "persisting", "worsening", "improving")
                },
            })
    return state


def compliance_node(state: AgentState) -> AgentState:
    from src.tracing.setup import span_node
    with span_node("compliance", trace=state.trace) as span:
        agent = ComplianceAgent()
        for report in state.inspection_reports:
            try:
                result = agent.run(report)
                for v in result.violations:
                    state.compliance_violations.append(v.model_dump())
            except Exception as e:
                logger.error("compliance.error", error=str(e))
                state.errors.append(f"compliance failed: {e}")
        state.compliance_status = _derive_status(state)
        if span:
            span.update(output={
                "violations": len(state.compliance_violations),
                "status": state.compliance_status.value,
            })
    return state


def risk_node(state: AgentState) -> AgentState:
    from src.tracing.setup import span_node
    with span_node("risk", trace=state.trace) as span:
        try:
            assessment = RiskAgent().run(state)
            state.risk_assessment = assessment.model_dump()
            if span:
                span.update(output={
                    "issues_count": len(assessment.issues),
                })
        except Exception as e:
            logger.error("risk.error", error=str(e))
            state.errors.append(f"risk failed: {e}")
    return state


def workorder_node(state: AgentState) -> AgentState:
    from src.tracing.setup import span_node
    with span_node("workorder", trace=state.trace) as span:
        if not state.risk_assessment:
            return state
        from src.schemas.risk import RiskAssessment
        assessment = RiskAssessment.model_validate(state.risk_assessment)
        try:
            result = WorkOrderAgent().run(assessment)
            state.work_orders = [wo.model_dump(mode="json") for wo in result.work_orders]
            state.workorder_summary = result.summary
            if span:
                span.update(output={"work_orders_created": len(state.work_orders)})
        except Exception as e:
            logger.error("workorder.error", error=str(e))
            state.errors.append(f"workorder failed: {e}")
    return state


def documentation_node(state: AgentState) -> AgentState:
    from src.tracing.setup import span_node
    with span_node("documentation", trace=state.trace) as span:
        try:
            agent = DocumentationAgent(audience=ReportAudience.OPERATIONAL)
            doc = agent.run(state)
            state.document = doc.model_dump(mode="json")
            state.report_path = doc.output_path
            if span:
                span.update(output={
                    "report_path": doc.output_path,
                    "sections": len(doc.sections),
                })
        except Exception as e:
            logger.error("documentation.error", error=str(e))
            state.errors.append(f"documentation failed: {e}")
    return state


def followup_node(state: AgentState) -> AgentState:
    from src.tracing.setup import span_node
    with span_node("followup", trace=state.trace) as span:
        try:
            plan = FollowUpAgent().run(state)
            state.followup_plan = plan.model_dump(mode="json")
            if span:
                span.update(output={
                    "notifications": len(plan.notifications),
                    "scheduled_tasks": len(plan.scheduled_tasks),
                })
        except Exception as e:
            logger.error("followup.error", error=str(e))
            state.errors.append(f"followup failed: {e}")
    return state

# ---------- Routing helpers ----------

def _derive_status(state: AgentState) -> ComplianceStatus:
    if not state.inspection_reports:
        return ComplianceStatus.UNKNOWN
    if not state.compliance_violations:
        return ComplianceStatus.COMPLIANT
    has_critical = any(
        v.get("severity") == "critical"
        for v in state.compliance_violations
    )
    return ComplianceStatus.NON_COMPLIANT if has_critical else ComplianceStatus.PARTIAL


def should_run_compliance(state: AgentState) -> str:
    return "compliance" if any(r.findings for r in state.inspection_reports) else "memory_persist"


def should_run_risk(state: AgentState) -> str:
    has_any = bool(state.inspection_reports) and any(
        r.findings for r in state.inspection_reports
    )
    return "risk" if has_any else "memory_persist"


# ---------- Memory helpers (used inside nodes) ----------

def _format_history_for_inspection(state: AgentState) -> str:
    """Compact history snippet sent to the Inspection Agent."""
    if not state.asset_memory:
        return ""
    s = state.asset_memory.get("summary", {})
    if s.get("total_inspections", 0) == 0:
        return ""

    lines = [f"This building has been inspected {s['total_inspections']} time(s) before."]
    lines.append(f"Last inspected: {s.get('last_inspection_at')}")

    recent = state.asset_memory.get("recent_findings", [])[:10]
    if recent:
        lines.append("Recent findings:")
        for f in recent:
            lines.append(
                f"  - [{f['severity']}] {f['category']}: {f['issue'][:120]}"
            )

    open_wos = state.asset_memory.get("open_work_orders", [])
    if open_wos:
        lines.append(
            f"Open work orders from prior runs ({len(open_wos)}): "
            "the corresponding issues may still be visible if remediation is incomplete."
        )

    return "\n".join(lines)


def _classify_against_history(state: AgentState) -> list[dict[str, Any]]:
    """Classify the new findings against historical ones.

    Produces a flat list of classification dicts suitable for state storage.
    """
    if not state.asset_memory:
        return []

    history_dicts = state.asset_memory.get("recent_findings", [])
    if not history_dicts:
        return []

    history = [HistoricalFinding.model_validate(h) for h in history_dicts]

    # Flatten all new findings across all reports.
    new_findings = []
    for report in state.inspection_reports:
        for f in report.findings:
            new_findings.append(f)

    if not new_findings:
        return []

    # Use BGE embeddings for semantic matching. Falls back to lexical if
    # embeddings fail to load.
    embed_fn = None
    try:
        from src.rag.embeddings import get_embeddings
        embed_model = get_embeddings()
        embed_fn = embed_model.embed_documents
    except Exception as e:
        logger.warning("classification.embeddings_unavailable", error=str(e))

    comparisons = classify_findings(new_findings, history, embed_fn=embed_fn)

    out: list[dict[str, Any]] = []
    for c in comparisons:
        entry: dict[str, Any] = {
            "new_issue": c.new_finding.issue,
            "new_severity": c.new_finding.severity.value,
            "new_category": c.new_finding.category.value,
            "status": c.status,
            "match_score": round(c.match_score, 3),   # ← ADD THIS
        }
        if c.historical_match:
            entry["old_issue"] = c.historical_match.issue
            entry["old_severity"] = c.historical_match.severity
        out.append(entry)

    counts: dict[str, int] = {}
    for c in out:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    logger.info("classification.done", **counts)
    return out


# ---------- Build ----------

def build_workflow():
    graph = StateGraph(AgentState)

    graph.add_node("memory_recall", memory_recall_node)
    graph.add_node("inspection", inspection_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node("risk", risk_node)
    graph.add_node("workorder", workorder_node)
    graph.add_node("documentation", documentation_node)
    graph.add_node("followup", followup_node)
    graph.add_node("memory_persist", memory_persist_node)

    graph.add_edge(START, "memory_recall")
    graph.add_edge("memory_recall", "inspection")
    graph.add_conditional_edges(
        "inspection",
        should_run_compliance,
        {"compliance": "compliance", "memory_persist": "memory_persist"},
    )
    graph.add_conditional_edges(
        "compliance",
        should_run_risk,
        {"risk": "risk", "memory_persist": "memory_persist"},
    )
    graph.add_edge("risk", "workorder")
    graph.add_edge("workorder", "documentation")
    graph.add_edge("documentation", "followup")
    graph.add_edge("followup", "memory_persist")
    graph.add_edge("memory_persist", END)

    return graph.compile()