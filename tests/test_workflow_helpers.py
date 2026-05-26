"""Tests for workflow.py routing/derivation helpers."""
from src.graph.workflow import _derive_status, should_run_compliance, should_run_risk
from src.schemas.enums import ComplianceStatus
from src.schemas.state import AgentState


def _state_with(**overrides) -> AgentState:
    """Build an AgentState with sensible defaults, override specific fields."""
    base = {
        "building_id": "BLDG-001",
        "photo_paths": ["test.png"],
        "inspector_notes": "",
    }
    base.update(overrides)
    return AgentState(**base)


# ----- _derive_status ----

def test_derive_status_unknown_when_no_reports():
    """No inspection reports at all → UNKNOWN."""
    state = _state_with()
    assert _derive_status(state) == ComplianceStatus.UNKNOWN


def test_derive_status_non_compliant_when_critical(make_finding):
    """Any 'critical' violation → NON_COMPLIANT."""
    from src.schemas.inspection import InspectionReport
    state = _state_with()
    state.inspection_reports = [InspectionReport(
        photo_path="x.png",
        findings=[make_finding(severity="critical")],
        overall_assessment="overall assessment text long enough",
        model_used="test:default",
    )]
    state.compliance_violations = [{"severity": "critical"}]
    assert _derive_status(state) == ComplianceStatus.NON_COMPLIANT


def test_derive_status_partial_when_only_minor(make_finding):
    """Violations but none critical → PARTIAL."""
    from src.schemas.inspection import InspectionReport
    state = _state_with()
    state.inspection_reports = [InspectionReport(
        photo_path="x.png",
        findings=[make_finding(severity="minor")],
        overall_assessment="overall assessment text long enough",
        model_used="test:default",
    )]
    state.compliance_violations = [{"severity": "minor"}]
    assert _derive_status(state) == ComplianceStatus.PARTIAL


# ----- routing ----

def test_should_run_compliance_skips_when_no_findings():
    """No findings at all → bypass compliance, go to memory_persist."""
    from src.schemas.inspection import InspectionReport
    state = _state_with()
    state.inspection_reports = [InspectionReport(
        photo_path="x.png",
        findings=[],
        overall_assessment="overall assessment text long enough",
        model_used="test:default",
    )]
    assert should_run_compliance(state) == "memory_persist"


def test_should_run_compliance_proceeds_when_findings_exist(make_finding):
    """At least one finding → run compliance."""
    from src.schemas.inspection import InspectionReport
    state = _state_with()
    state.inspection_reports = [InspectionReport(
        photo_path="x.png",
        findings=[make_finding()],
        overall_assessment="overall assessment text long enough",
        model_used="test:default",
    )]
    assert should_run_compliance(state) == "compliance"