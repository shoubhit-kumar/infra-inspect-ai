"""Data models for inspection findings and reports."""
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, Field

from src.schemas.enums import IssueCategory, Severity


class InspectionFinding(BaseModel):
    """A single issue detected in an inspection photo."""

    issue: Annotated[str, Field(min_length=10, max_length=500)]
    """Short description of what was found. Example: 'Fire extinguisher tag expired 2023'."""

    severity: Severity
    """How critical is this finding."""

    category: IssueCategory
    """Which trade or domain this belongs to."""

    location_hint: Annotated[str, Field(max_length=400)]
    """Where in the photo, e.g. 'top-left corner', 'near the door frame'."""

    visual_evidence: Annotated[str, Field(min_length=20, max_length=1000)]
    """What the agent actually sees in the photo that led to this finding."""

    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    """Agent's confidence in this finding (0 to 1)."""

    recommended_action: Annotated[str, Field(min_length=10, max_length=800)]
    """Short next-step suggestion. Risk and Work Order agents refine later."""


class InspectionReport(BaseModel):
    """Output of the Inspection Agent for one photo."""

    photo_path: str
    """Path to the analyzed image."""

    findings: list[InspectionFinding] = Field(default_factory=list)
    """All issues found in this photo. Empty list = no issues detected."""

    overall_assessment: Annotated[str, Field(min_length=20, max_length=2000)]
    """One-paragraph summary of the photo's condition."""

    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """When this analysis was performed."""

    model_used: str
    """Which LLM model produced this report. For audit and reproducibility."""