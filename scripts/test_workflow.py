"""End-to-end test of the full 6-agent workflow."""
from pathlib import Path

from src.config.settings import get_settings
from src.graph.workflow import build_workflow
from src.schemas.state import AgentState
from src.utils.logging import configure_logging


def main() -> None:
    configure_logging()
    from src.utils.cache import enable_dev_cache
    enable_dev_cache()

    samples_dir = Path("data/sample_photos")
    photos = sorted(
        str(p) for p in samples_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )

    if not photos:
        print(f"No photos in {samples_dir}/. Add some images first.")
        return

    initial_state = AgentState(
        building_id="BLDG-001",
        photo_paths=photos,
        inspector_notes="Routine annual safety inspection.",
    )

    print(f"\nRunning full 6-agent workflow on {len(photos)} photo(s)...")
    print(f"Photos: {[Path(p).name for p in photos]}\n")

    # Boot MCP servers if enabled
    settings = get_settings()
    mcp_servers: dict[str, list[str]] = {}
    if settings.mcp_enabled:
        mcp_servers = {
            "filesystem":   settings.mcp_filesystem_command,
            "workorder":    settings.mcp_workorder_command,
            "notification": settings.mcp_notification_command,
        }

    from src.mcp_clients.manager import MCPConnectionManager
    from src.mcp_clients.connections import set_mcp_manager

    from src.tracing.setup import trace_workflow_run

    with MCPConnectionManager(mcp_servers) as manager:
        set_mcp_manager(manager if mcp_servers else None)

        with trace_workflow_run(
            building_id=initial_state.building_id,
            photo_count=len(initial_state.photo_paths),
            inspector_notes=initial_state.inspector_notes,
        ) as trace:
            # Attach trace to state so nodes can create spans under it
            initial_state.trace = trace

            workflow = build_workflow()
            final_state = AgentState.model_validate(workflow.invoke(initial_state))

            if trace:
                final_state.trace = trace  # keep for downstream code if needed
                trace.update(
                    output={
                        "findings": sum(len(r.findings) for r in final_state.inspection_reports),
                        "violations": len(final_state.compliance_violations),
                        "work_orders": len(final_state.work_orders),
                        "compliance_status": final_state.compliance_status.value,
                    },
                )

        _dump_state(final_state)
        _print_top_summary(final_state)
        _print_memory(final_state)
        _print_classifications(final_state)
        _print_workorders(final_state)
        _print_followup(final_state)
        _print_report_pointer(final_state)

        set_mcp_manager(None)

def _dump_state(state: AgentState) -> None:
    """Serialize the full final state to disk for inspection and replay."""
    import json
    from datetime import datetime, timezone

    out_dir = Path("data/outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    latest_path = out_dir / "last_run.json"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = out_dir / f"run_{state.building_id}_{timestamp}.json"

    payload = state.model_dump(mode="json")
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    latest_path.write_text(text, encoding="utf-8")
    archive_path.write_text(text, encoding="utf-8")

    print(f"\n  State dumped to:")
    print(f"    {latest_path}")
    print(f"    {archive_path}")


def _print_top_summary(state: AgentState) -> None:
    total_findings = sum(len(r.findings) for r in state.inspection_reports)
    risk_issues = len(state.risk_assessment["issues"]) if state.risk_assessment else 0
    notifications = (
        len(state.followup_plan["notifications"]) if state.followup_plan else 0
    )
    tasks = (
        len(state.followup_plan["scheduled_tasks"]) if state.followup_plan else 0
    )

    print("=" * 72)
    print(f"WORKFLOW COMPLETE - Building {state.building_id}")
    print(f"Compliance status:     {state.compliance_status.value.upper()}")
    print("=" * 72)
    print(f"Photos analyzed:       {len(state.inspection_reports)}")
    print(f"Findings:              {total_findings}")
    print(f"Compliance violations: {len(state.compliance_violations)}")
    print(f"Risk issues:           {risk_issues}")
    print(f"Work orders:           {len(state.work_orders)}")
    print(f"Notifications:         {notifications}")
    print(f"Scheduled tasks:       {tasks}")
    print(f"Errors:                {len(state.errors)}")
    if state.errors:
        for e in state.errors:
            print(f"  - {e}")


def _print_workorders(state: AgentState) -> None:
    print("\n" + "-" * 72)
    print(f"WORK ORDERS  ({len(state.work_orders)})")
    print("-" * 72)
    for wo in state.work_orders:
        approval = " [NEEDS APPROVAL]" if wo.get("requires_approval") else ""
        print(f"  [{wo['priority']}] Rs.{wo['estimated_cost_inr']:>10,.0f}  "
              f"{wo['assigned_team']}{approval}")
        print(f"        {wo['title'][:80]}")


def _print_followup(state: AgentState) -> None:
    if not state.followup_plan:
        return
    plan = state.followup_plan
    print("\n" + "-" * 72)
    print(f"NOTIFICATIONS  ({len(plan['notifications'])})")
    print("-" * 72)
    for n in plan["notifications"]:
        urgent = " [URGENT]" if n["urgent"] else ""
        print(f"  -> {n['channel']:6} | {n['audience']:20}{urgent}")
        print(f"     {n['subject'][:80]}")

    print("\n" + "-" * 72)
    print(f"SCHEDULED TASKS  ({len(plan['scheduled_tasks'])})")
    print("-" * 72)
    for t in plan["scheduled_tasks"]:
        print(f"  {t['task_type']:25}  @ {t['scheduled_for']}")
        print(f"     {t['description'][:80]}")


def _print_report_pointer(state: AgentState) -> None:
    print("\n" + "-" * 72)
    print("REPORT")
    print("-" * 72)
    if state.report_path:
        print(f"  Saved to: {state.report_path}")
        path = Path(state.report_path)
        if path.exists():
            preview = path.read_text(encoding="utf-8")[:400]
            print(f"\n  Preview:\n{preview}...")
    else:
        print("  (no report generated)")

def _print_memory(state: AgentState) -> None:
    if not state.asset_memory:
        return
    s = state.asset_memory.get("summary", {})
    print("\n" + "-" * 72)
    print("MEMORY (recalled before run)")
    print("-" * 72)
    print(f"  Total prior inspections:  {s.get('total_inspections', 0)}")
    print(f"  Last inspection:          {s.get('last_inspection_at')}")
    print(f"  Open work orders:         {s.get('open_work_orders', 0)}")
    print(f"  Closed work orders:       {s.get('closed_work_orders', 0)}")
    print(f"  Longest open issue days:  {s.get('longest_open_issue_days', 0)}")
    if state.memory_run_id is not None:
        print(f"  This run persisted as id: {state.memory_run_id}")


def _print_classifications(state: AgentState) -> None:
    if not state.finding_classifications:
        return
    counts: dict[str, int] = {}
    for c in state.finding_classifications:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    print("\n" + "-" * 72)
    print("FINDING CLASSIFICATIONS vs HISTORY")
    print("-" * 72)
    for status in ["new", "persisting", "worsening", "improving"]:
        print(f"  {status:12} {counts.get(status, 0)}")

    interesting = [
        c for c in state.finding_classifications
        if c["status"] in ("persisting", "worsening", "improving")
    ]
    for c in interesting[:5]:
        print(f"\n  [{c['status'].upper()}] {c['new_issue'][:70]}")
        if "old_issue" in c:
            print(f"     was: {c['old_issue'][:70]}")
            print(f"     severity: {c.get('old_severity')} -> {c['new_severity']}")


if __name__ == "__main__":
    main()