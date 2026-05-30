# ADR-0003: Hybrid retrieval — FAISS + BM25 + RRF + cross-encoder reranker

**Status:** Accepted
**Date:** 2026-05-02
**Deciders:** Project author

## Context

The compliance agent needs to ground each finding against building codes (BIS-1893, NFPA-70, NFPA-101). The corpus is ~24,915 chunks after structure-aware splitting and OCR. Queries look like:

- `"electrical Exposed and frayed wiring near junction box visible damage"`
- `"fire_safety Sprinkler head obstruction in storage room ceiling area"`

Two retrieval failure modes were observed with dense embeddings (FAISS + BGE-small-en) alone:

1. **Acronym and code-number misses.** A finding referencing `"NFPA-70"` or `"section 4.3.1"` would retrieve semantically related but lexically distinct chunks. The exact code number was missed.
2. **Paraphrase misses.** A finding describing `"rust on metal terminals"` failed to retrieve passages discussing `"corrosion of conductive surfaces"` because the embedding space tilted toward surface-form similarity.

Options considered:

1. **Dense only.** Simple. Sufficient for general semantic matches. Fails on acronyms and exact strings.
2. **Sparse (BM25) only.** Catches exact strings. Fails on paraphrases.
3. **Hybrid with weighted score combination.** Requires learning weights. Sensitive to query distribution.
4. **Hybrid with Reciprocal Rank Fusion (RRF).** No weights to learn. Combines ranks instead of scores.
5. **Hybrid + cross-encoder reranker.** Add a final reranking stage that scores query-document pairs jointly.

## Decision

Use option 5: dense + sparse + RRF + reranker.

The pipeline:

1. **Dense retrieval** (FAISS, BGE-small-en-v1.5, 384-dim, normalized): top 20 hits
2. **Sparse retrieval** (BM25): top 20 hits
3. **Reciprocal Rank Fusion** (`k=60`, see `src/rag/hybrid.py`): combines both lists into a fused top-20
4. **Cross-encoder reranking** (BGE-reranker-base): re-scores fused hits, keeps top 5

`k=60` is the value from the original RRF paper (Cormack et al. 2009). It is a hyperparameter, but tests show low sensitivity in the range `40 < k < 80`.

The reranker is a cross-encoder, not a bi-encoder: it takes `(query, document)` pairs and produces a relevance score per pair. This is more accurate than re-using the bi-encoder embeddings because the cross-encoder attends jointly to query and document.

## Consequences

**Positive:**
- Acronym misses largely eliminated. Code numbers like `"NFPA-70"` consistently rank in the top 5.
- Paraphrase matching preserved via the dense leg.
- RRF requires no training data — works zero-shot.
- Reranker sharpens the final selection. Empirical chunk-relevance scores cluster around 0.7-0.9 for true positives; non-relevant chunks fall to 0.1-0.3.

**Negative:**
- Four retrieval stages add latency. Per-finding retrieval is ~10-15 seconds, dominated by reranker inference on CPU.
- Reranker model (~280MB) and bi-encoder model (~130MB) must be loaded into memory. Cold-start adds ~10 seconds.
- Sparse leg requires a separate index (`data/vector_db/bm25_index.pkl`) that must be rebuilt when the corpus changes.

**Neutral:**
- An attempt to parallelize the 5 sequential retrievals via `ThreadPoolExecutor` was reverted. See [ADR-0009] (or the README "What I tried and reverted" section).