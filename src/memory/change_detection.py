"""Compare new findings against historical ones.

Used by Inspection and Risk agents (Day 10) to detect:
    - persisting issues (same problem found again, unresolved)
    - resolved issues (something previously open is no longer present)
    - new issues (genuinely new)
    - potentially worsening issues (same category + location, higher severity)
"""
from dataclasses import dataclass
from typing import Iterable

from src.schemas.inspection import InspectionFinding
from src.schemas.memory import HistoricalFinding


@dataclass
class FindingComparison:
    """Per-finding classification against history."""

    new_finding: InspectionFinding
    historical_match: HistoricalFinding | None
    """The closest matching historical finding, if any."""

    status: str
    """One of:
       'new'             - no historical analog
       'persisting'      - very similar to a past finding (same category + similar location)
       'worsening'       - persisting, but new severity > historical severity
       'improving'       - persisting, but new severity < historical severity
    """


# Severity ordering for delta calculation.
_SEVERITY_RANK = {
    "info": 0,
    "minor": 1,
    "major": 2,
    "critical": 3,
}


def _severity_rank(s: str) -> int:
    return _SEVERITY_RANK.get(s.lower(), 0)


def _normalise_location(text: str | None) -> str:
    """Lowercase + strip for fuzzy location matching."""
    return (text or "").strip().lower()


def classify_findings(
    new_findings: Iterable[InspectionFinding],
    history: Iterable[HistoricalFinding],
) -> list[FindingComparison]:
    """Classify each new finding against the historical set.

    Matching is heuristic: same category AND overlapping location words
    AND similar issue text. Good enough for Week 3. Week 5 evals can
    measure how often this misfires, after which we can swap in a
    smarter matcher (embedding similarity, LLM judge, etc.).
    """
    history_list = list(history)
    results: list[FindingComparison] = []

    for nf in new_findings:
        match = _best_history_match(nf, history_list)
        if match is None:
            results.append(FindingComparison(nf, None, "new"))
            continue

        new_rank = _severity_rank(nf.severity.value)
        old_rank = _severity_rank(match.severity)
        if new_rank > old_rank:
            status = "worsening"
        elif new_rank < old_rank:
            status = "improving"
        else:
            status = "persisting"
        results.append(FindingComparison(nf, match, status))

    return results


def _best_history_match(
    new_finding: InspectionFinding,
    history: list[HistoricalFinding],
) -> HistoricalFinding | None:
    """Find the most plausible historical match for a new finding.

    Currently: same category, and location/issue word overlap above threshold.
    Returns None if no candidate clears the bar.
    """
    if not history:
        return None

    new_category = new_finding.category.value
    new_loc_words = set(_normalise_location(new_finding.location_hint).split())
    new_issue_words = set(_normalise_location(new_finding.issue).split())

    best: HistoricalFinding | None = None
    best_score = 0

    for h in history:
        if h.category != new_category:
            continue
        h_loc_words = set(_normalise_location(h.location_hint).split())
        h_issue_words = set(_normalise_location(h.issue).split())
        loc_overlap = len(new_loc_words & h_loc_words)
        issue_overlap = len(new_issue_words & h_issue_words)
        score = loc_overlap * 2 + issue_overlap  # location weighs more

        if score > best_score:
            best_score = score
            best = h

    # Require a minimum overlap to count as a match.
    return best if best_score >= 2 else None