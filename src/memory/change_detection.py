"""Compare new findings against historical ones.

Used by Inspection and Risk agents (Day 10) to detect:
    - persisting issues (same problem found again, unresolved)
    - resolved issues (something previously open is no longer present)
    - new issues (genuinely new)
    - potentially worsening issues (same category + location, higher severity)

Matching strategy:
    Primary: BGE-small-en-v1.5 cosine similarity between concatenated
             (issue + location_hint) text. Catches semantic matches like
             "rust on terminals" <-> "corrosion on fuse holders" that
             word-overlap misses.

    Fallback: word overlap (location words weigh 2x, issue words 1x).
             Used when no embedding function is provided.

    Both paths require category match - we never cross-classify a finding
    in one trade (electrical) against another (plumbing).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from src.schemas.inspection import InspectionFinding
from src.schemas.memory import HistoricalFinding
from src.utils.logging import get_logger

logger = get_logger(__name__)


EmbedFn = Callable[[list[str]], list[list[float]]]
"""Type alias: takes texts, returns list of embedding vectors."""


# Minimum cosine similarity to count two findings as "the same".
# Calibrated empirically: BGE-small-en typically gives ~0.85+ for paraphrases,
# ~0.7 for related-but-distinct, ~0.5 for unrelated same-domain text.
# 0.65 is a conservative bar that catches paraphrases without over-merging.
SEMANTIC_SIMILARITY_THRESHOLD = 0.65


@dataclass
class FindingComparison:
    """Per-finding classification against history."""

    new_finding: InspectionFinding
    historical_match: HistoricalFinding | None
    """The closest matching historical finding, if any."""

    status: str
    """One of:
       'new'             - no historical analog
       'persisting'      - very similar to a past finding (same category + semantically close)
       'worsening'       - persisting, but new severity > historical severity
       'improving'       - persisting, but new severity < historical severity
    """

    match_score: float = 0.0
    """Similarity score [0..1] for the matched pair. 0 if status == 'new'."""


# Severity ordering for delta calculation.
_SEVERITY_RANK = {
    "info": 0,
    "minor": 1,
    "major": 2,
    "critical": 3,
}


def _severity_rank(s: str) -> int:
    return _SEVERITY_RANK.get(s.lower(), 0)


def _normalise(text: str | None) -> str:
    """Lowercase + strip + collapse whitespace."""
    if not text:
        return ""
    return " ".join(text.strip().lower().split())


def _finding_text(issue: str | None, location: str | None) -> str:
    """Concatenate issue + location for a representative embedding input."""
    parts = [_normalise(issue), _normalise(location)]
    return " | ".join(p for p in parts if p)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors.

    Assumes vectors are NOT pre-normalised. BGE with normalize_embeddings=True
    returns unit vectors, in which case dot product equals cosine, but we
    compute the full formula here to be robust if a different model is plugged in.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def classify_findings(
    new_findings: Iterable[InspectionFinding],
    history: Iterable[HistoricalFinding],
    embed_fn: EmbedFn | None = None,
) -> list[FindingComparison]:
    """Classify each new finding against the historical set.

    Args:
        new_findings: current run's findings.
        history: prior findings to compare against.
        embed_fn: optional embedding function. If provided, uses cosine
            similarity for matching. If None, falls back to word overlap.

    Returns one FindingComparison per new finding, in input order.
    """
    new_list = list(new_findings)
    history_list = list(history)

    if not new_list:
        return []

    if embed_fn is not None:
        return _classify_semantic(new_list, history_list, embed_fn)
    return _classify_lexical(new_list, history_list)


# ---------- Semantic path (BGE-backed) ----------

def _classify_semantic(
    new_list: list[InspectionFinding],
    history_list: list[HistoricalFinding],
    embed_fn: EmbedFn,
) -> list[FindingComparison]:
    """Match via cosine similarity of finding embeddings."""
    if not history_list:
        # Nothing to compare against - every finding is new.
        return [FindingComparison(nf, None, "new") for nf in new_list]

    # Embed all new and historical findings in a single batched call each.
    new_texts = [_finding_text(nf.issue, nf.location_hint) for nf in new_list]
    hist_texts = [_finding_text(h.issue, h.location_hint) for h in history_list]

    try:
        new_vecs = embed_fn(new_texts)
        hist_vecs = embed_fn(hist_texts)
    except Exception as e:
        logger.warning("change_detection.embed_failed", error=str(e), fallback="lexical")
        return _classify_lexical(new_list, history_list)

    results: list[FindingComparison] = []
    for i, nf in enumerate(new_list):
        new_vec = new_vecs[i]
        new_cat = nf.category.value

        best_idx = -1
        best_sim = 0.0
        for j, h in enumerate(history_list):
            # Hard category gate - never cross-classify trades.
            if h.category != new_cat:
                continue
            sim = _cosine(new_vec, hist_vecs[j])
            if sim > best_sim:
                best_sim = sim
                best_idx = j

        if best_idx == -1 or best_sim < SEMANTIC_SIMILARITY_THRESHOLD:
            results.append(FindingComparison(nf, None, "new", match_score=0.0))
            continue

        match = history_list[best_idx]
        status = _severity_status(nf.severity.value, match.severity)
        results.append(FindingComparison(nf, match, status, match_score=best_sim))

    return results


# ---------- Lexical fallback ----------

def _classify_lexical(
    new_list: list[InspectionFinding],
    history_list: list[HistoricalFinding],
) -> list[FindingComparison]:
    """Word-overlap matching. Used when no embed_fn is provided."""
    results: list[FindingComparison] = []
    for nf in new_list:
        match, score = _best_history_match_lexical(nf, history_list)
        if match is None:
            results.append(FindingComparison(nf, None, "new"))
            continue
        status = _severity_status(nf.severity.value, match.severity)
        # Convert raw overlap score to a [0..1]-ish range for consistency.
        # Not strictly cosine but provides a useful number for logs.
        normalized = min(score / 10.0, 1.0)
        results.append(FindingComparison(nf, match, status, match_score=normalized))
    return results


def _best_history_match_lexical(
    new_finding: InspectionFinding,
    history: list[HistoricalFinding],
) -> tuple[HistoricalFinding | None, int]:
    """Find the most plausible historical match via word overlap.

    Returns (match, raw_score). raw_score is 0 if no match clears the bar.
    """
    if not history:
        return None, 0

    new_category = new_finding.category.value
    new_loc_words = set(_normalise(new_finding.location_hint).split())
    new_issue_words = set(_normalise(new_finding.issue).split())

    best: HistoricalFinding | None = None
    best_score = 0

    for h in history:
        if h.category != new_category:
            continue
        h_loc_words = set(_normalise(h.location_hint).split())
        h_issue_words = set(_normalise(h.issue).split())
        loc_overlap = len(new_loc_words & h_loc_words)
        issue_overlap = len(new_issue_words & h_issue_words)
        score = loc_overlap * 2 + issue_overlap  # location weighs more

        if score > best_score:
            best_score = score
            best = h

    if best_score >= 2:
        return best, best_score
    return None, 0


# ---------- Shared helpers ----------

def _severity_status(new_sev: str, old_sev: str) -> str:
    """Derive persisting/worsening/improving from severity comparison."""
    new_rank = _severity_rank(new_sev)
    old_rank = _severity_rank(old_sev)
    if new_rank > old_rank:
        return "worsening"
    if new_rank < old_rank:
        return "improving"
    return "persisting"