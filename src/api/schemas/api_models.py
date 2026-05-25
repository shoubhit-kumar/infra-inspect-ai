"""HTTP request and response models for the FastAPI layer.

These wrap (but don't replace) the internal Pydantic schemas. The wrappers
exist to:
- Document the public API surface without leaking internal state shape
- Avoid serializing fields meant only for in-memory use (e.g., Langfuse trace)
- Provide stable JSON contracts even if internal schemas evolve
"""
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.schemas.enums import ComplianceStatus


# ============================================================================
# Requests
# ============================================================================

class CreateInspectionRequest(BaseModel):
    """Body for POST /inspections."""

    building_id: str = Field(..., examples=["BLDG-001"])
    photo_paths: list[str] = Field(
        ...,
        description="Absolute or workspace-relative paths to photos on the server.",
        examples=[["data/sample_photos/electrical_panel_unsafe.png"]],
    )
    inspector_notes: str = Field(
        default="",
        examples=["Routine annual safety inspection."],
    )


# ============================================================================
# Responses
# ============================================================================

class JobStatus(str, Enum):
    """Status of an async workflow job."""
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class JobAcceptedResponse(BaseModel):
    """Returned from POST /inspections with HTTP 202."""

    job_id: str = Field(..., examples=["job_a1b2c3d4"])
    status: JobStatus = JobStatus.queued
    poll_url: str = Field(
        ...,
        description="GET this URL to check status and retrieve the result when ready.",
        examples=["/jobs/job_a1b2c3d4"],
    )


class WorkOrderSummary(BaseModel):
    """Compact work order representation for the API."""

    issue_id: str
    title: str
    priority: str
    assigned_team: str
    estimated_cost_inr: float
    sla_deadline: str
    requires_approval: bool


class InspectionSummary(BaseModel):
    """Top-line numbers from a completed workflow run."""

    building_id: str
    compliance_status: ComplianceStatus
    photos_analyzed: int
    findings_count: int
    violations_count: int
    risk_issues_count: int
    work_orders: list[WorkOrderSummary]
    report_path: str | None = None
    memory_run_id: int | None = None
    errors: list[str] = Field(default_factory=list)


class JobStatusResponse(BaseModel):
    """Returned from GET /jobs/{job_id}."""

    job_id: str
    status: JobStatus
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: InspectionSummary | None = None
    error: str | None = Field(
        default=None,
        description="Set if status=failed. Otherwise null.",
    )


class HealthResponse(BaseModel):
    """Liveness check."""

    status: str = "ok"
    version: str = "0.1.0"
    workflow_loaded: bool
    mcp_servers_connected: list[str]


class BuildingMemoryResponse(BaseModel):
    """Compact memory recall for a building."""

    building_id: str
    total_inspections: int
    last_inspection_at: datetime | None
    open_work_orders: int
    closed_work_orders: int
    longest_open_issue_days: int
    recent_findings: list[dict[str, Any]] = Field(default_factory=list)


class BuildingInspectionItem(BaseModel):
    """One historical inspection run."""

    run_id: int
    started_at: datetime
    compliance_status: str
    finding_count: int
    violation_count: int


class BuildingInspectionsResponse(BaseModel):
    """List of historical inspections for a building."""

    building_id: str
    total: int
    inspections: list[BuildingInspectionItem]