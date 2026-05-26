"""Shared fixtures across all test files.

Fixtures here are imported automatically into every test file.
The goal is to make individual tests short and readable - no per-test
factory boilerplate.
"""
from __future__ import annotations

import pytest

# Pytest config - automatically picked up.
# `asyncio_mode = "auto"` is already in pyproject.toml.


@pytest.fixture
def make_finding():
    """Factory for InspectionFinding instances with sensible defaults.

    Usage:
        def test_thing(make_finding):
            f = make_finding(issue="Cracked tile", severity="major")
    """
    from src.schemas.enums import IssueCategory, Severity
    from src.schemas.inspection import InspectionFinding

    def _factory(
        issue: str = "Default test finding text that meets min length requirement",
        severity: str = "major",
        category: str = "electrical",
        location_hint: str = "test location",
        visual_evidence: str = "visible test evidence in the photograph here",
        confidence: float = 0.9,
        recommended_action: str = "test recommended action here",
    ) -> InspectionFinding:
        return InspectionFinding(
            issue=issue,
            severity=Severity(severity),
            category=IssueCategory(category),
            location_hint=location_hint,
            visual_evidence=visual_evidence,
            confidence=confidence,
            recommended_action=recommended_action,
        )

    return _factory


@pytest.fixture
def make_historical():
    """Factory for HistoricalFinding instances."""
    from datetime import datetime, timezone
    from src.schemas.memory import HistoricalFinding

    def _factory(
        issue: str = "Default historical finding text exceeding minimum length",
        severity: str = "major",
        category: str = "electrical",
        location_hint: str = "test location",
        visual_evidence: str = "historical evidence text long enough to pass validation",
        inspection_run_id: int = 1,
        photo_filename: str = "test.png",
    ) -> HistoricalFinding:
        return HistoricalFinding(
            inspection_run_id=inspection_run_id,
            inspected_at=datetime.now(timezone.utc),
            photo_filename=photo_filename,
            issue=issue,
            severity=severity,
            category=category,
            location_hint=location_hint,
            visual_evidence=visual_evidence,
        )

    return _factory


@pytest.fixture
def fake_embedder():
    """Returns a deterministic 'embedder' for change_detection tests.

    Uses a simple hash-based vectorizer: same text → same vector, similar
    text → similar vector. NOT actual semantics, but deterministic and
    lets us assert behaviour without loading real BGE (~5s + 130MB).
    """
    def _embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            words = set(text.lower().split())
            # Project words into a 16-dim "embedding" via stable hashing.
            vec = [0.0] * 16
            for word in words:
                idx = hash(word) % 16
                vec[idx] += 1.0
            # Normalize (so cosine works correctly).
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors

    return _embed