"""Building memory and inspection history routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from src.api.schemas.api_models import (
    BuildingInspectionItem,
    BuildingInspectionsResponse,
    BuildingMemoryResponse,
)
from src.memory.repository import AssetRepository
from src.memory.store import InspectionRun
from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["memory"])


@router.get(
    "/buildings/{building_id}/memory",
    response_model=BuildingMemoryResponse,
    summary="Recall asset memory for a building",
)
def get_building_memory(building_id: str) -> BuildingMemoryResponse:
    """Return summary, recent findings, and work-order counts for one building."""
    repo = AssetRepository()
    memory = repo.get_asset_memory(building_id)
    s = memory.summary

    return BuildingMemoryResponse(
        building_id=s.building_id,
        total_inspections=s.total_inspections,
        last_inspection_at=s.last_inspection_at,
        open_work_orders=s.open_work_orders,
        closed_work_orders=s.closed_work_orders,
        longest_open_issue_days=s.longest_open_issue_days,
        recent_findings=[f.model_dump(mode="json") for f in memory.recent_findings[:20]],
    )


@router.get(
    "/buildings/{building_id}/inspections",
    response_model=BuildingInspectionsResponse,
    summary="List historical inspection runs for a building",
)
def list_building_inspections(
    building_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> BuildingInspectionsResponse:
    """Paginated list of inspection runs for a building, newest first."""
    repo = AssetRepository()

    with repo.SessionLocal() as s:
        rows = s.scalars(
            select(InspectionRun)
            .where(InspectionRun.building_id == building_id)
            .order_by(desc(InspectionRun.started_at))
            .limit(limit)
        ).all()

        items = [
            BuildingInspectionItem(
                run_id=r.id,
                started_at=r.started_at,
                compliance_status=r.compliance_status or "unknown",
                finding_count=r.finding_count,
                violation_count=r.violation_count,
            )
            for r in rows
        ]

    return BuildingInspectionsResponse(
        building_id=building_id,
        total=len(items),
        inspections=items,
    )