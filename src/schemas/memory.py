"""Schemas for long-term asset memory."""
from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, Field


class AssetSummary(BaseModel):
    """Aggregate facts about a building/asset known so far."""

    building_id: str
    first_inspection_at: datetime | None = None
    last_inspection_at: datetime | None = None
    total_inspections: int = 0
    open_work_orders: int = 0
    closed_work_orders: int = 0
    longest_open_issue_days: int = 0
    """How long the oldest unresolved issue has been open."""


class HistoricalFinding(BaseModel):
    """A finding observed in some past inspection (read-only summary)."""

    inspection_run_id: int
    inspected_at: datetime
    photo_filename: str | None
    issue: str
    severity: str
    category: str
    location_hint: str | None
    visual_evidence: str | None


class HistoricalWorkOrder(BaseModel):
    """A work order from any prior inspection."""

    work_order_internal_id: int
    issue_id: str
    title: str
    priority: str
    status: str
    """E.g. 'open', 'in_progress', 'closed', 'verified'."""
    created_at: datetime
    closed_at: datetime | None = None
    estimated_cost_inr: float


class AssetMemory(BaseModel):
    """Full memory snapshot for a building, returned to agents on inspection."""

    summary: AssetSummary
    recent_findings: list[HistoricalFinding] = Field(default_factory=list)
    open_work_orders: list[HistoricalWorkOrder] = Field(default_factory=list)
    recently_closed_work_orders: list[HistoricalWorkOrder] = Field(default_factory=list)
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )