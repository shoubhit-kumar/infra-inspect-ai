"""Schemas for compliance violations and citations."""
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

from src.schemas.enums import Severity


class RegulationSource(str, Enum):
    """Where a regulation comes from. Used to route citations correctly."""
    NBC = "NBC"            # National Building Code (India)
    IS = "IS"              # Indian Standards (BIS)
    NFPA = "NFPA"          # National Fire Protection Association
    OSHA = "OSHA"          # Occupational Safety and Health Administration
    LOCAL = "LOCAL"        # State or municipal codes
    INTERNAL = "INTERNAL"  # Company-specific policies


class RegulationCitation(BaseModel):
    """A specific clause from a regulation."""

    source: RegulationSource
    """Which regulatory body issued this rule."""

    code: Annotated[str, Field(min_length=2, max_length=200)]
    """Code identifier, e.g. 'NBC 2016 Part 4 Section 4.2.3' or 'IS 732:2019'."""

    title: Annotated[str, Field(min_length=5, max_length=400)]
    """Short title of the clause."""

    requirement_summary: Annotated[str, Field(min_length=10, max_length=1000)]
    """Plain-language summary of what the rule requires."""


class ComplianceViolation(BaseModel):
    """A single compliance violation tied to one or more inspection findings."""

    finding_indices: list[int] = Field(default_factory=list)
    """Indices of findings in the InspectionReport that triggered this violation."""

    citation: RegulationCitation
    """The specific regulation being violated."""

    violation_description: Annotated[str, Field(min_length=20, max_length=1500)]
    """How the finding violates the regulation, in plain language."""

    severity: Severity
    """Compliance-weighted severity. May differ from the finding severity."""

    mandatory: bool = True
    """True = legally required fix. False = recommended best practice."""

    suggested_remediation: Annotated[str, Field(min_length=10, max_length=1500)]
    """What to do to come back into compliance."""

    # ----- RAG grounding (Day 8) -----
    grounded: bool = False
    """True if this violation was supported by retrieved regulation chunks.
    False means the LLM produced this without retrieval context (legacy or fallback)."""

    retrieval_score: float | None = None
    """Reranker confidence for the top retrieved chunk that grounds this violation.
    None if no retrieval was performed. Higher = more confident the citation matches reality."""

    source_excerpts: list[str] = Field(default_factory=list)
    """The actual text excerpts from regulations that ground this violation.
    For audit and explainability. Empty if not grounded."""