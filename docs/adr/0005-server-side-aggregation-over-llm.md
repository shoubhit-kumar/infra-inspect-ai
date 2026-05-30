# ADR-0005: Compute deterministic aggregations server-side, not via LLM

**Status:** Accepted
**Date:** 2026-05-18
**Deciders:** Project author

## Context

The Risk Agent outputs a `RiskAssessment` containing a list of issues and a `highest_risk_category` field. The original implementation asked the LLM to populate `highest_risk_category` directly: "Identify which category has the most aggregate risk."

In production runs, `highest_risk_category` was frequently `None`. The LLM would either:
- Skip the field entirely (omitted from JSON output)
- Return `null` because it "wasn't sure"
- Return an inconsistent value that didn't match the categories actually present in the issues list

The pattern is general. LLMs handle creative and extractive tasks well. They handle deterministic aggregations (counting, summing, finding the max) inconsistently. Every aggregation handed to the LLM is a hallucination opportunity.

A related case existed in the same agent. The `risk_score` field is defined as `impact_score × probability_score`. The LLM was asked to compute this. It was sometimes wrong (off by 1.5+ in absolute value). The code already defended against this: after the LLM call, the score is recomputed in Python and a `risk.score_drift` warning is logged on mismatch.

The `highest_risk_category` field had no such defense.

## Decision

Compute `highest_risk_category` deterministically in Python, after the LLM produces the issues list.

Implementation: `src/agents/risk.py::_compute_highest_risk_category(issues)`. The function:

1. Returns `None` for an empty issue list
2. Groups issues by category, summing `risk_score` and counting issues per category
3. Returns the category with the highest aggregate `risk_score`
4. Tie-breaks by issue count (more issues > equal score)

The Risk Agent's `run()` method overwrites whatever the LLM produced for this field with the deterministic computation.

The same principle was applied to the `risk_score` field on individual issues (recompute from impact × probability after the LLM call) and is documented as a general pattern.

## Consequences

**Positive:**
- `highest_risk_category` is now always populated when the issues list is non-empty.
- The value is fully explainable: anyone can re-derive it from the issues array.
- One less hallucination surface in the LLM's output.
- The unit test `tests/test_risk_helpers.py` covers all aggregation cases (empty, single category, tie-breaking) in milliseconds, without invoking an LLM.

**Negative:**
- Slight duplication: the LLM is still asked to produce the field (the schema requires it). Its value is then discarded. Could be removed from the prompt to save tokens, at the cost of a more invasive prompt change.
- The aggregation rule (sum risk_score, tie-break by count) is a design choice. A different definition of "highest risk" (e.g., max severity issue's category) would require a code change.

**Neutral:**
- The pattern generalizes. Anywhere the system asks the LLM for a count, sum, max, or group-by-and-aggregate, move it to code.

## See Also

- `src/agents/risk.py::_compute_highest_risk_category` — implementation
- `tests/test_risk_helpers.py` — unit tests
- ADR-0006 (BGE change detection) — similar pattern, replacing LLM judgment with deterministic similarity matching