"""Tests for change_detection.py - severity ranking, lexical matching, BGE path."""
from src.memory.change_detection import (
    SEMANTIC_SIMILARITY_THRESHOLD,
    _cosine,
    _severity_rank,
    classify_findings,
)


# ----- pure functions ----

def test_severity_rank_ordering():
    """info < minor < major < critical."""
    assert _severity_rank("info") < _severity_rank("minor")
    assert _severity_rank("minor") < _severity_rank("major")
    assert _severity_rank("major") < _severity_rank("critical")


def test_severity_rank_unknown_defaults_to_zero():
    """Unknown severity gracefully defaults rather than raising."""
    assert _severity_rank("absurd") == 0


def test_cosine_identical_vectors():
    """cos(v, v) == 1."""
    v = [1.0, 2.0, 3.0]
    assert abs(_cosine(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal_vectors():
    """cos([1,0], [0,1]) == 0."""
    assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_cosine_handles_zero_vectors():
    """Zero vectors don't crash with div-by-zero."""
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# ----- classification ----

def test_classify_no_history_marks_everything_new(make_finding):
    """First-ever inspection: all findings are 'new'."""
    new_finding = make_finding(issue="A long enough finding description here")
    result = classify_findings([new_finding], [])
    assert len(result) == 1
    assert result[0].status == "new"
    assert result[0].historical_match is None


def test_classify_persisting_via_lexical(make_finding, make_historical):
    """Identical category + heavy word overlap → persisting (lexical path)."""
    new = make_finding(
        issue="Exposed and frayed wiring near junction box visible",
        category="electrical",
        location_hint="north wall panel",
        severity="major",
    )
    old = make_historical(
        issue="Exposed and frayed wiring near junction box visible",
        category="electrical",
        location_hint="north wall panel",
        severity="major",
    )
    result = classify_findings([new], [old])
    assert result[0].status == "persisting"


def test_classify_worsening_when_severity_increases(make_finding, make_historical):
    """Same finding, new severity > old severity → worsening."""
    new = make_finding(
        issue="Exposed wiring causing visible sparking and damage to insulation",
        category="electrical",
        severity="critical",
    )
    old = make_historical(
        issue="Exposed wiring causing visible sparking and damage to insulation",
        category="electrical",
        severity="major",
    )
    result = classify_findings([new], [old])
    assert result[0].status == "worsening"


def test_classify_semantic_with_embedder(make_finding, make_historical, fake_embedder):
    """When embed_fn is provided, semantic matching kicks in."""
    new = make_finding(
        issue="Exposed and frayed wiring near junction box visible damage",
        category="electrical",
    )
    old = make_historical(
        issue="Exposed and frayed wiring near junction box visible damage",
        category="electrical",
    )
    result = classify_findings([new], [old], embed_fn=fake_embedder)
    assert result[0].status == "persisting"
    assert result[0].match_score >= SEMANTIC_SIMILARITY_THRESHOLD


def test_classify_different_category_stays_new(make_finding, make_historical, fake_embedder):
    """Hard category gate: electrical finding doesn't match plumbing history."""
    new = make_finding(
        issue="Exposed and frayed wiring causing visible damage today",
        category="electrical",
    )
    old = make_historical(
        issue="Exposed and frayed wiring causing visible damage today",
        category="plumbing",
    )
    result = classify_findings([new], [old], embed_fn=fake_embedder)
    assert result[0].status == "new"  # category mismatch even with identical text