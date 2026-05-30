# ADR-0006: BGE cosine similarity for change detection, with lexical fallback

**Status:** Accepted
**Date:** 2026-05-23
**Deciders:** Project author

## Context

The memory layer classifies new findings against historical ones into four buckets: `new`, `persisting`, `worsening`, `improving`. The classification drives downstream behavior — a "persisting" finding from three months ago carries different operational weight than a genuinely new issue.

The initial implementation used word-overlap matching. For a new finding and a historical finding, compute the size of the word-set intersection of their `issue` and `location_hint` fields. Above a small threshold, declare a match.

This worked for trivial cases where the LLM produced near-identical text run-over-run ("Exposed and frayed wiring" ↔ "Exposed and frayed wiring"). It failed on realistic paraphrases:

- `"Rust visible on metal terminals"` vs `"Corrosion on fuse holders"` — zero word overlap, both refer to the same issue
- `"Pipes appear oxidized"` vs `"Plumbing showing corrosion"` — zero word overlap

A "new" classification in these cases is wrong. It triggers a fresh work order for an issue that's been open for months.

## Decision

Use BGE-small-en-v1.5 (already loaded for RAG) to embed both new and historical findings. Compute cosine similarity. If similarity ≥ 0.65 and categories match, declare a match.

Implementation: `src/memory/change_detection.py::_classify_semantic`.

Design choices within the decision:

1. **Same model as RAG, not a separate one.** Loading a second embedding model would double memory. BGE-small is good enough for short-text similarity and is already warm.
2. **Hard category gate.** Even if similarity is 1.0, electrical ≠ plumbing. Cross-trade misclassification is a worse failure mode than missing a paraphrase.
3. **Lexical fallback.** When `embed_fn` is not provided (e.g., the embedding model failed to load), the function falls back to word-overlap. The system remains functional, just less precise. Tests don't load the real BGE model — they pass a fake hash-based embedder via `tests/conftest.py::fake_embedder`.
4. **Single-batch embedding.** Embed all N new findings and M historical findings in one call each. N×M cosine comparisons are then microseconds.
5. **Threshold = 0.65.** Empirical. BGE-small typically gives ~0.85+ for paraphrases, ~0.70 for related-but-distinct, ~0.50 for unrelated same-domain. 0.65 is the conservative bar that catches paraphrases without over-merging.

## Consequences

**Positive:**
- Real-world classifications now match what an inspector would say. A finding rephrased as "rust" instead of "corrosion" still classifies as persisting if it matches a prior finding semantically.
- Sample scores from production runs: `frayed wiring` 0.92, `overcrowded wiring` 0.98, `corroded terminals` 0.97, `dust accumulation` 0.94, `unidentified wiring` 1.00 — all comfortably above the 0.65 threshold.
- The classification logic is testable without loading the real model (see `fake_embedder` fixture).

**Negative:**
- An additional model invocation per workflow (one batched embedding call for new+historical findings). Cost is negligible compared to the LLM calls but non-zero.
- The 0.65 threshold is empirical, not theoretical. A future change in the embedding model would invalidate it.
- Some classifications are still wrong. The system has no ground-truth eval set for change detection; the threshold was set by inspection of real outputs, not a labeled set.

**Neutral:**
- The pattern (mature embeddings beat hand-written heuristics) generalizes. Anywhere the codebase does string similarity that's currently lexical, BGE is the upgrade path.

## See Also

- `src/memory/change_detection.py` — implementation
- `tests/test_change_detection.py` — coverage including semantic and lexical paths, category gate, severity-status logic