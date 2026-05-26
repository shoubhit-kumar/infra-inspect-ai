"""Schema validation tests.

Pydantic does most of the work for us. These tests verify:
  - Required fields are required
  - Field constraints fire correctly (min_length, ge/le, etc.)
  - Enums reject invalid values
  - Defaults populate correctly
"""
import pytest
from pydantic import ValidationError


def test_inspection_finding_constructs_with_defaults(make_finding):
    """Smoke: factory produces a valid finding."""
    f = make_finding()
    assert f.issue.startswith("Default")
    assert f.confidence == 0.9


def test_inspection_finding_rejects_short_issue(make_finding):
    """min_length=10 should reject 5-char issue strings."""
    with pytest.raises(ValidationError):
        make_finding(issue="short")


def test_inspection_finding_rejects_bad_confidence(make_finding):
    """confidence must be in [0, 1]."""
    with pytest.raises(ValidationError):
        make_finding(confidence=1.5)
    with pytest.raises(ValidationError):
        make_finding(confidence=-0.1)


def test_inspection_finding_rejects_bad_severity():
    """Severity must be one of the enum values - tested by passing raw string to schema."""
    from src.schemas.inspection import InspectionFinding
    with pytest.raises(ValidationError):
        InspectionFinding(
            issue="Default test finding text that meets min length requirement",
            severity="catastrophic",          # ← invalid - Pydantic should reject
            category="electrical",
            location_hint="test location",
            visual_evidence="visible test evidence in the photograph here",
            confidence=0.9,
            recommended_action="test recommended action here",
        )

def test_inspection_finding_rejects_bad_category():
    """Category must be one of the enum values."""
    from src.schemas.inspection import InspectionFinding
    with pytest.raises(ValidationError):
        InspectionFinding(
            issue="Default test finding text that meets min length requirement",
            severity="major",
            category="nonexistent_category",  # ← invalid
            location_hint="test location",
            visual_evidence="visible test evidence in the photograph here",
            confidence=0.9,
            recommended_action="test recommended action here",
        )

def test_inspection_report_defaults():
    """Report has sensible defaults: empty findings, recent analyzed_at."""
    from datetime import datetime, timezone
    from src.schemas.inspection import InspectionReport

    r = InspectionReport(
        photo_path="x.png",
        overall_assessment="Overall assessment text long enough to pass validation",
        model_used="test:default",
    )
    assert r.findings == []
    assert (datetime.now(timezone.utc) - r.analyzed_at).total_seconds() < 5


def test_severity_enum_values():
    """Lock down severity vocabulary - if these change, downstream rank computation breaks."""
    from src.schemas.enums import Severity
    assert {s.value for s in Severity} >= {"info", "minor", "major", "critical"}


def test_category_enum_includes_electrical():
    """Sanity check on category enum membership."""
    from src.schemas.enums import IssueCategory
    assert "electrical" in {c.value for c in IssueCategory}