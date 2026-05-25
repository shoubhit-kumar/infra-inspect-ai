"""Seed asset memory with a sample building and a prior inspection.

Run once:
    python -m scripts.seed_memory
"""
from datetime import datetime, timedelta, timezone

from src.memory.repository import AssetRepository
from src.utils.logging import configure_logging


def main() -> None:
    configure_logging()

    repo = AssetRepository()

    # Idempotency: if we already have an inspection for this building,
    # don't re-seed. Re-running seed_memory becomes safe.
    existing = repo.get_asset_memory("BLDG-001")
    if existing.summary.total_inspections > 0:
        print(
            f"\nBLDG-001 already has {existing.summary.total_inspections} "
            "inspection(s) - skipping seed.\n"
            "Delete data/memory/asset_memory.sqlite to force a re-seed."
        )
        return

    repo.ensure_asset(
        building_id="BLDG-001",
        display_name="Demo Office Building",
        location="Delhi, India",
    )

    # Simulate a past inspection from 2 months ago.
    past_findings = [
        {
            "photo_filename": "electrical_panel_unsafe.png",
            "issue": "Exposed and frayed wiring throughout the electrical panel.",
            "severity": "major",
            "category": "electrical",
            "location_hint": "main electrical panel, second floor",
            "visual_evidence": "Several wires showed signs of frayed insulation.",
            "confidence": 0.9,
        },
        {
            "photo_filename": "wall_crack.png",
            "issue": "Small crack in wall plaster near load-bearing column.",
            "severity": "minor",
            "category": "structural",
            "location_hint": "third floor north wall",
            "visual_evidence": "A hairline crack approximately 15cm long.",
            "confidence": 0.7,
        },
    ]

    past_work_orders = [
        {
            "issue_id": "electrical-wiring-degradation-01",
            "title": "Inspect and repair frayed electrical wiring in main panel",
            "description": "Initial repair work to address wiring concerns.",
            "category": "electrical",
            "priority": "P2",
            "assigned_team": "electrical_team",
            "estimated_cost_inr": 75000.0,
            "estimated_hours": 12.0,
            "sla_deadline": (
                datetime.now(timezone.utc) - timedelta(days=50)
            ).isoformat(),
        },
        {
            "issue_id": "structural-wall-crack-01",
            "title": "Monitor wall crack on third floor",
            "description": "Document size and check progression every 30 days.",
            "category": "structural",
            "priority": "P3",
            "assigned_team": "facilities_general",
            "estimated_cost_inr": 5000.0,
            "estimated_hours": 2.0,
            "sla_deadline": (
                datetime.now(timezone.utc) - timedelta(days=30)
            ).isoformat(),
        },
    ]

    run_id = repo.record_inspection_run(
        building_id="BLDG-001",
        inspector_notes="Routine quarterly inspection - simulated 2 months ago.",
        photo_count=2,
        finding_count=len(past_findings),
        violation_count=2,
        compliance_status="partial",
        findings=past_findings,
        work_orders=past_work_orders,
    )

    # Pretend the electrical work order was completed; structural one remains open.
    # We need the actual ID of the inserted record.
    mem = repo.get_asset_memory("BLDG-001")
    for wo in mem.open_work_orders:
        if wo.issue_id == "electrical-wiring-degradation-01":
            repo.update_work_order_status(wo.work_order_internal_id, "closed")

    print(f"\nSeeded run_id={run_id} for BLDG-001.")
    final = repo.get_asset_memory("BLDG-001")
    print(f"\nSummary:")
    print(f"  Total inspections:     {final.summary.total_inspections}")
    print(f"  Open work orders:      {final.summary.open_work_orders}")
    print(f"  Closed work orders:    {final.summary.closed_work_orders}")
    print(f"  Recent findings:       {len(final.recent_findings)}")
    print(f"  Longest-open days:     {final.summary.longest_open_issue_days}")


if __name__ == "__main__":
    main()