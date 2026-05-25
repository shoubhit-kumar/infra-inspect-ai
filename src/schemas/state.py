"""Shared state passed between agents in the LangGraph workflow."""
from datetime import datetime, timezone
from typing import Annotated, Any
from operator import add

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.enums import ComplianceStatus
from src.schemas.inspection import InspectionReport
from typing import Any


class AgentState(BaseModel):
    """The state object that flows through the agent graph.

    Each agent reads what it needs, writes its outputs, and passes
    the (mutated) state to the next agent.

    In Week 2 we will use this as the LangGraph state type.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # ---------- Input ----------
    building_id: str
    """Identifier for the building being inspected."""

    photo_paths: list[str]
    """All photos to be analyzed in this run."""

    inspector_notes: str = ""
    """Free-text notes from the human inspector."""

    # ---------- Agent 1: Inspection ----------
    inspection_reports: list[InspectionReport] = Field(default_factory=list)
    """One report per photo. Filled by InspectionAgent."""

    # ---------- Agent 2: Compliance (Week 2) ----------
    compliance_violations: list[dict[str, Any]] = Field(default_factory=list)
    compliance_status: ComplianceStatus = ComplianceStatus.UNKNOWN

    # ---------- Agent 3: Risk ----------
    risk_assessment: dict[str, Any] | None = None
    """RiskAssessment.model_dump() - kept as dict for JSON serialization."""

    # ---------- Agent 4: Work Orders ----------
    work_orders: list[dict[str, Any]] = Field(default_factory=list)
    """List of WorkOrder.model_dump() dicts."""

    workorder_summary: str = ""

    # ---------- Agent 5: Documentation ----------
    document: dict[str, Any] | None = None
    """InspectionDocument.model_dump() as dict for JSON state safety."""
    report_path: str | None = None

    # ---------- Agent 6: Follow-up ----------
    followup_plan: dict[str, Any] | None = None
    """FollowUpPlan.model_dump() as dict."""

    # ---------- Memory (Day 10) ----------
    asset_memory: dict[str, Any] | None = None
    """AssetMemory.model_dump() - filled by memory_recall_node at the start."""

    finding_classifications: list[dict[str, Any]] = Field(default_factory=list)
    """One classification per finding: new / persisting / worsening / improving."""

    memory_run_id: int | None = None
    """The inspection_runs.id assigned when persisting this run. Set by memory_persist_node."""

    # ---------- Tracing (Day 16) ----------
    trace: Any = Field(default=None, exclude=True)
    """Langfuse trace object for this workflow run. Set by test_workflow."""

    # ---------- Metadata ----------
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    errors: Annotated[list[str], Field(default_factory=list)]
    """Non-fatal errors accumulated during the run."""