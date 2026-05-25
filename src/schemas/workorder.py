"""Work order schemas."""
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from src.schemas.enums import IssueCategory, Priority


class ResponsibleTeam(str, Enum):
    """Which internal team or vendor handles this work."""
    ELECTRICAL = "electrical_team"
    PLUMBING = "plumbing_team"
    STRUCTURAL = "structural_engineer"
    FIRE_SAFETY = "fire_safety_team"
    HVAC = "hvac_team"
    FACILITIES = "facilities_general"
    EXTERNAL_VENDOR = "external_vendor"


# SLA hours per priority. Centralized so they cannot drift.
SLA_HOURS = {
    Priority.P1: 4,
    Priority.P2: 24,
    Priority.P3: 24 * 7,    # 1 week
    Priority.P4: 24 * 30,   # 1 month
}


class WorkOrder(BaseModel):
    """A single actionable ticket generated from a RiskedIssue."""

    work_order_id: str | None = None
    """Set by the work order system (Week 4). Optional at creation time."""

    issue_id: Annotated[str, Field(min_length=3, max_length=50)]
    """Links back to the RiskedIssue that generated this."""

    title: Annotated[str, Field(min_length=10, max_length=200)]
    """Short imperative title. Example: 'Repair exposed wiring in panel B'."""

    description: Annotated[str, Field(min_length=30, max_length=2000)]
    """Detailed scope of work."""

    category: IssueCategory
    assigned_team: ResponsibleTeam
    priority: Priority

    estimated_cost_inr: Annotated[float, Field(ge=0, le=10_000_000)]
    """Rough cost estimate in Indian rupees."""

    estimated_hours: Annotated[float, Field(gt=0, le=2000)]
    """Estimated labor hours."""

    sla_deadline: datetime
    """When this work must be completed by."""

    safety_precautions: list[str] = Field(default_factory=list)
    """E.g. 'De-energize panel before work', 'Use full PPE'."""

    requires_approval: bool = False
    """True for high-cost or critical work orders. Set by validator below."""

    @model_validator(mode="after")
    def _enforce_business_rules(self) -> "WorkOrder":
        """Cross-field validation - the kind of rule you cannot express per-field.

        1. Normalize sla_deadline to UTC-aware datetime.
        2. SLA deadline must match the priority's SLA window.
        3. High-cost (>500k INR) or P1 work orders require approval.
        """
        # Rule 1: Normalize to UTC-aware. If LLM produced a naive datetime,
        # assume it meant UTC (matches our 'now_utc' prompt convention).
        if self.sla_deadline.tzinfo is None:
            self.sla_deadline = self.sla_deadline.replace(tzinfo=timezone.utc)

        # Rule 2: SLA deadline must be within priority's window from now.
        # Allow a 1-hour tolerance for clock drift.
        max_window = timedelta(hours=SLA_HOURS[self.priority] + 1)
        now = datetime.now(timezone.utc)
        if self.sla_deadline - now > max_window:
            self.sla_deadline = now + timedelta(hours=SLA_HOURS[self.priority])

        # Rule 3: approval flag
        if self.priority == Priority.P1 or self.estimated_cost_inr > 500_000:
            self.requires_approval = True

        return self