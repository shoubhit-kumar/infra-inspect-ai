"""Risk assessment schemas."""
from typing import Annotated

from pydantic import BaseModel, Field

from src.schemas.enums import IssueCategory, Priority, Severity


class RiskedIssue(BaseModel):
    """A single issue with risk scoring and prioritization.

    Represents a *deduplicated* issue across the whole building. Multiple
    findings and violations may map to a single RiskedIssue.
    """

    issue_id: Annotated[str, Field(min_length=3, max_length=50)]
    """Stable identifier for this issue, e.g. 'electrical-exposed-wiring-01'."""

    title: Annotated[str, Field(min_length=10, max_length=200)]
    """Short human-readable title."""

    description: Annotated[str, Field(min_length=20, max_length=1000)]
    """Plain-language explanation of the issue and why it matters."""

    category: IssueCategory
    """Which trade/domain this issue belongs to."""

    severity: Severity
    """Aggregated severity across all underlying findings."""

    priority: Priority
    """Operational priority assigned by the Risk Agent."""

    impact_score: Annotated[float, Field(ge=0.0, le=10.0)]
    """How bad the consequences are if not fixed (0-10)."""

    probability_score: Annotated[float, Field(ge=0.0, le=10.0)]
    """Likelihood of those consequences occurring (0-10)."""

    risk_score: Annotated[float, Field(ge=0.0, le=100.0)]
    """impact * probability (the Risk Agent computes this)."""

    related_photo_paths: list[str] = Field(default_factory=list)
    """Photos that surfaced this issue."""

    related_finding_summaries: list[str] = Field(default_factory=list)
    """Short descriptions of contributing findings (audit trail)."""

    related_violation_codes: list[str] = Field(default_factory=list)
    """Citation codes from violations supporting this issue."""

    rationale: Annotated[str, Field(min_length=20, max_length=1000)]
    """Why this priority/score was assigned. Important for explainability."""


class RiskAssessment(BaseModel):
    """Output of the Risk Agent for the whole building."""

    issues: list[RiskedIssue]
    """Deduplicated, scored, prioritized issues."""

    summary: Annotated[str, Field(min_length=20, max_length=2000)]
    """Executive summary of the building's risk profile."""

    highest_risk_category: IssueCategory | None = None
    """Which category contributes the most aggregate risk."""

    model_used: str