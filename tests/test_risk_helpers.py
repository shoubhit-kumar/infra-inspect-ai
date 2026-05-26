"""Tests for risk agent helper functions."""
from src.agents.risk import _compute_highest_risk_category


class _MockIssue:
    """Lightweight stand-in for RiskedIssue - only fields the helper reads."""
    def __init__(self, category: str, risk_score: float):
        self.category = category
        self.risk_score = risk_score


def test_compute_highest_risk_returns_none_for_empty():
    """No issues → no category."""
    assert _compute_highest_risk_category([]) is None


def test_compute_highest_risk_picks_max_score():
    """Category with highest total risk_score wins."""
    issues = [
        _MockIssue("electrical", 80.0),
        _MockIssue("plumbing", 30.0),
        _MockIssue("electrical", 10.0),  # total electrical = 90
    ]
    assert _compute_highest_risk_category(issues) == "electrical"


def test_compute_highest_risk_tiebreaks_by_count():
    """Equal totals → category with more issues wins."""
    issues = [
        _MockIssue("electrical", 50.0),
        _MockIssue("plumbing", 25.0),
        _MockIssue("plumbing", 25.0),  # plumbing: 2 issues, same total
    ]
    # Both total 50; plumbing has 2 issues vs electrical's 1, so plumbing wins.
    assert _compute_highest_risk_category(issues) == "plumbing"


def test_compute_highest_risk_single_category():
    """One issue → that issue's category."""
    assert _compute_highest_risk_category([_MockIssue("fire_safety", 5.0)]) == "fire_safety"