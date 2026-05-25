"""Read-side smoke test for asset memory.

Run after seeding:
    python -m scripts.test_memory
"""
from src.memory.repository import AssetRepository
from src.utils.logging import configure_logging


def main() -> None:
    configure_logging()
    repo = AssetRepository()

    print("\nAll known assets:")
    for a in repo.list_assets():
        print(f"  - {a.building_id} ({a.display_name})  @  {a.location}")

    print("\nBLDG-001 memory snapshot:")
    mem = repo.get_asset_memory("BLDG-001")
    s = mem.summary
    print(f"  First inspection:  {s.first_inspection_at}")
    print(f"  Last inspection:   {s.last_inspection_at}")
    print(f"  Total inspections: {s.total_inspections}")
    print(f"  Open WOs:          {s.open_work_orders}")
    print(f"  Closed WOs:        {s.closed_work_orders}")
    print(f"  Longest-open days: {s.longest_open_issue_days}")

    print(f"\nRecent findings ({len(mem.recent_findings)}):")
    for f in mem.recent_findings:
        print(f"  [{f.severity}] {f.category}: {f.issue[:70]}")
        print(f"      at {f.location_hint}")

    print(f"\nOpen work orders ({len(mem.open_work_orders)}):")
    for wo in mem.open_work_orders:
        print(f"  [{wo.priority}] {wo.title[:70]}")
        print(f"      issue_id: {wo.issue_id}  cost: Rs.{wo.estimated_cost_inr:,.0f}")

    print(f"\nRecently closed ({len(mem.recently_closed_work_orders)}):")
    for wo in mem.recently_closed_work_orders:
        print(f"  [{wo.priority}] {wo.title[:70]}  closed_at={wo.closed_at}")


if __name__ == "__main__":
    main()