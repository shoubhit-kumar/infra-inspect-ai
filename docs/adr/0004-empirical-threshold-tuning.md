# ADR-0004: Tune retrieval threshold empirically, not by intuition

**Status:** Accepted
**Date:** 2026-05-10
**Deciders:** Project author

## Context

The retriever keeps only chunks whose final reranker score exceeds `MIN_RETRIEVAL_SCORE`. The initial default was 0.30, chosen because "scores above 0.3 feel meaningful."

When the system ran end-to-end, 30% of findings (3 out of 10 in the eval set) received zero compliance chunks. The compliance agent then either fabricated citations or returned empty violations — a silent failure mode.

The problem: 0.30 was an intuition, not a measurement. Reranker scores don't have a universal interpretation; they're calibrated to the model's training distribution, which doesn't match the building-codes domain.

## Decision

Build a labeled evaluation set and tune the threshold empirically.

1. **Eval set construction:** `data/eval/retrieval_eval_set.json` — 10 findings drawn from real sample photos, each annotated with the expected ground-truth chunks (identified by chunk hash and partial text).
2. **Evaluation script:** `scripts/evaluate_retrieval.py` runs the full retriever at a given threshold, compares kept chunks to ground-truth via fuzzy text match (Levenshtein > 0.8), and reports per-finding precision, recall, F1, and a global "zero-chunk-failure rate."
3. **Threshold sweep:** `scripts/sweep_threshold.py` runs the above at thresholds `[0.05, 0.10, 0.15, 0.20, 0.30]` and produces a chart.

Sweep results:

| Threshold | Precision | Recall | F1 | Zero-chunk failures |
|-----------|-----------|--------|-----|---------------------:|
| 0.05      | 0.200     | 0.583  | **0.298** | **0** |
| 0.10      | 0.200     | 0.417  | 0.270 | 1 |
| 0.15      | 0.000     | 0.250  | 0.000 | 3 |
| 0.20      | 0.000     | 0.250  | 0.000 | 3 |
| 0.30      | 0.000     | 0.183  | 0.000 | 3 |

Set `MIN_RETRIEVAL_SCORE=0.05` in `.env`. This is the empirical optimum across all three metrics.

## Consequences

**Positive:**
- F1 improves 3.2× over the default (0.298 vs 0.000 at 0.30).
- Zero-chunk failures drop from 30% to 0%.
- The eval framework is reusable. When new building-codes documents are ingested, re-run the sweep and re-tune.
- A reviewer who questions the threshold value has a falsifiable answer: "we measured."

**Negative:**
- F1 is modest in absolute terms. The retriever still keeps too many chunks (precision = 0.20). Top-k limiting at the reranker stage helps but doesn't fully resolve.
- 10 findings is a small eval set. Numbers are directionally meaningful but not statistically robust. A larger labeled set would shift absolute numbers and could justify a different threshold.
- The ground-truth labels are semi-automated (LLM-as-judge). A human-labeled set would be more reliable but expensive.

**Neutral:**
- The threshold-sweep methodology generalizes to other tuning problems: chunk size, top_k at reranker, query construction strategy. Same eval set, same script structure.

## See Also

- `scripts/sweep_threshold.py` — runs the sweep
- `data/eval/results/threshold_sweep_*.png` — historical sweep charts (one is in the README hero section)
- `docs/eval-methodology.md` — full methodology