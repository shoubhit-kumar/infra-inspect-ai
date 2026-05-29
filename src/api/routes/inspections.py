"""Inspection workflow routes - async job submission and result polling."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from src.api.dependencies import JobRegistry, get_job_registry
from src.api.request_context import get_request_id, set_request_id
from src.api.schemas.api_models import (
    CreateInspectionRequest,
    InspectionSummary,
    JobAcceptedResponse,
    JobStatus,
    JobStatusResponse,
    WorkOrderSummary,
)
from src.graph.workflow import build_workflow
from src.schemas.state import AgentState
from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["inspections"])


def _run_workflow_job(
    job_id: str,
    request: CreateInspectionRequest,
    request_id: str,
) -> None:
    """Background task: run the workflow and stash the result on the job record.

    Runs in FastAPI's background tasks thread - the request returns 202
    immediately while this executes.

    `request_id` is captured from the originating HTTP request and re-applied
    here because ContextVars don't auto-propagate across thread boundaries.
    With it bound, every log line emitted during this workflow's execution
    is tagged with the same request_id as the API call that started it.
    """
    set_request_id(request_id)
    registry = get_job_registry()
    registry.update(
        job_id,
        status=JobStatus.running,
        started_at=datetime.now(timezone.utc),
    )
    try:
        # Validate photo paths exist
        missing = [p for p in request.photo_paths if not Path(p).exists()]
        if missing:
            raise FileNotFoundError(f"Photos not found: {missing}")

        initial_state = AgentState(
            building_id=request.building_id,
            photo_paths=request.photo_paths,
            inspector_notes=request.inspector_notes,
            request_id=request_id,
        )

        logger.info(
            "api.job.starting",
            job_id=job_id,
            building_id=request.building_id,
            photo_count=len(request.photo_paths),
        )

        workflow = build_workflow()
        final = AgentState.model_validate(workflow.invoke(initial_state))

        summary = _summarize_state(final)
        registry.update(
            job_id,
            status=JobStatus.succeeded,
            finished_at=datetime.now(timezone.utc),
            result=summary,
        )
        logger.info("api.job.succeeded", job_id=job_id)

    except Exception as e:
        logger.error("api.job.failed", job_id=job_id, error=str(e))
        registry.update(
            job_id,
            status=JobStatus.failed,
            finished_at=datetime.now(timezone.utc),
            error=str(e)[:500],
        )


def _summarize_state(state: AgentState) -> InspectionSummary:
    """Reduce a full AgentState to a public API response."""
    risk_issues_count = 0
    if state.risk_assessment:
        risk_issues_count = len(state.risk_assessment.get("issues", []))

    work_orders = [
        WorkOrderSummary(
            issue_id=wo["issue_id"],
            title=wo["title"],
            priority=wo["priority"],
            assigned_team=wo["assigned_team"],
            estimated_cost_inr=float(wo["estimated_cost_inr"]),
            sla_deadline=str(wo["sla_deadline"]),
            requires_approval=bool(wo.get("requires_approval", False)),
        )
        for wo in state.work_orders
    ]

    total_findings = sum(len(r.findings) for r in state.inspection_reports)

    return InspectionSummary(
        building_id=state.building_id,
        compliance_status=state.compliance_status,
        photos_analyzed=len(state.inspection_reports),
        findings_count=total_findings,
        violations_count=len(state.compliance_violations),
        risk_issues_count=risk_issues_count,
        work_orders=work_orders,
        report_path=state.report_path,
        memory_run_id=state.memory_run_id,
        errors=list(state.errors),
    )



@router.post(
    "/inspections",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a new inspection workflow (async)",
)
def create_inspection(
    request: CreateInspectionRequest,
    background_tasks: BackgroundTasks,
    registry: JobRegistry = Depends(get_job_registry),
) -> JobAcceptedResponse:
    """Submit a building + photos for inspection.

    Returns immediately with a job_id. Workflow runs in the background;
    poll GET /jobs/{job_id} for status and results.

    The X-Request-ID header (set by middleware on every request) is captured
    and propagated into the background task so all workflow logs share the
    same correlation ID as this HTTP request.
    """
    record = registry.create()
    rid = get_request_id()
    record.request_id = rid
    background_tasks.add_task(_run_workflow_job, record.job_id, request, rid)

    logger.info(
        "api.job.queued",
        job_id=record.job_id,
        building_id=request.building_id,
        photo_count=len(request.photo_paths),
    )

    return JobAcceptedResponse(
        job_id=record.job_id,
        request_id=rid,
        status=record.status,
        poll_url=f"/jobs/{record.job_id}",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get status and result of an inspection job",
)
def get_job(
    job_id: str,
    registry: JobRegistry = Depends(get_job_registry),
) -> JobStatusResponse:
    """Poll for the status and result of an async inspection job."""
    record = registry.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobStatusResponse(
        job_id=record.job_id,
        request_id=record.request_id,
        status=record.status,
        submitted_at=record.submitted_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        result=record.result,
        error=record.error,
    )