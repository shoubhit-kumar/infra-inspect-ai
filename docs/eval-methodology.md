# Evaluation Methodology

How the system is measured for retrieval quality, and how the empirical threshold was chosen.

For the architectural decision behind empirical tuning, see [ADR-0004](adr/0004-empirical-threshold-tuning.md). For the retrieval pipeline being evaluated, see [`rag-pipeline.md`](rag-pipeline.md).

---

## Why eval at all

Without measurement, retrieval tuning is folklore. Someone says "0.30 feels right" and the threshold gets locked in. Months later when production behaves badly, no one can answer why 0.30. There's no path to improvement that doesn't reset the choice.

The eval framework exists to make tuning falsifiable: every choice (threshold, top_k, query construction) can be answered with "we measured."

The eval is intentionally lightweight. 10 findings, semi-automated labels. The point is not to compete with public benchmarks; the point is to be able to detect regression and make defensible choices.

---

## Eval set construction

**File:** `data/eval/retrieval_eval_set.json`

10 findings drawn from real sample photos in `data/sample_photos/`. For each finding:

```json
{
  "id": "elec-frayed-wiring",
  "category": "electrical",
  "issue": "Exposed and frayed wiring near junction box visible damage to insulation",
  "visual_evidence": "Multiple conductors show damaged jacketing with copper exposed and insulation peeling away at the junction box terminal",
  "ground_truth_chunks": [
    {
      "source": "NFPA-70",
      "section": "300.10",
      "text_snippet": "Continuity. Metal raceways, cable armors, and other metal enclosures for conductors..."
    },
    {
      "source": "NFPA-70",
      "section": "110.7",
      "text_snippet": "Wiring Integrity. Completed wiring installations shall be free from short circuits..."
    }
  ]
}
```

**How the ground truth was generated:**

1. For each finding, run the full retrieval pipeline at a permissive threshold (0.05) and capture all top-k chunks
2. Ask a strong LLM (claude-3-5-sonnet via the Anthropic API) to identify which of the candidate chunks would be cited by a human inspector reviewing this finding
3. Author manually reviewed the LLM's selections, corrected obvious errors, removed false positives
4. Persisted the corrected selections as `ground_truth_chunks`

This is **LLM-as-judge with human verification**. Not as reliable as a fully human-labeled set, but dramatically cheaper, and the verification step catches the worst LLM errors. Documented caveat: the eval set's labels reflect the judge's biases.

---

## Metrics

Three metrics, computed per threshold over all 10 findings:

### Precision
```
precision = |retrieved ∩ ground_truth| / |retrieved|
```
What fraction of returned chunks are actually relevant. Higher = less noise.

### Recall
```
recall = |retrieved ∩ ground_truth| / |ground_truth|
```
What fraction of relevant chunks were returned. Higher = fewer misses.

### F1
```
F1 = 2 × precision × recall / (precision + recall)
```
Harmonic mean. Used as the single optimization target.

### Zero-chunk failures

A separate count: for how many findings did the retriever return *zero* chunks at this threshold? This isn't a standard IR metric but is critical for this system — a zero-chunk finding gets no compliance grounding. Different from low precision, which still produces output.

---

## Chunk-match logic

The eval needs to decide whether a retrieved chunk "matches" a ground-truth chunk. Source documents are large; chunk boundaries can differ run-to-run if chunking changes.

The match rule: **Levenshtein ratio between chunk text and ground-truth `text_snippet` > 0.8**.

Implementation:
```python
from rapidfuzz import fuzz

def chunk_matches(chunk_text, gt_snippet):
    return fuzz.partial_ratio(chunk_text, gt_snippet) >= 80
```

This catches the case where a chunk contains the ground-truth snippet plus some surrounding text — a substring match in spirit.

---

## Running an evaluation

### Single threshold

```bash
python -m scripts.evaluate_retrieval --threshold 0.05
```

Outputs:
```
Finding 1/10: elec-frayed-wiring
Retrieved 5 chunks; 3 matched ground truth
Precision: 0.60  Recall: 0.60  F1: 0.60
Finding 2/10: elec-corrosion-fuses
Retrieved 4 chunks; 1 matched ground truth
...
=== AGGREGATE ===
Precision: 0.20  Recall: 0.583  F1: 0.298
Zero-chunk failures: 0 of 10
```
### Threshold sweep

```bash
python -m scripts.sweep_threshold
```

This runs `evaluate_retrieval` across `[0.05, 0.10, 0.15, 0.20, 0.30]` and produces:

- A CSV summary in `data/eval/results/`
- A matplotlib chart showing precision/recall/F1 across the sweep
- Best-threshold recommendation

The most recent chart is in the README hero section (`data/eval/results/threshold_sweep_20260524_051516.png`).

---

## The threshold-tuning story

The system originally shipped with `MIN_RETRIEVAL_SCORE = 0.30`, chosen because "scores above 0.3 feel meaningful." When the first end-to-end runs were inspected, 30% of findings (3 of 10) received zero compliance chunks. The compliance LLM then produced no violations for those findings — a silent failure.

Running the sweep produced:

| Threshold | Precision | Recall | F1 | Zero-chunk failures |
|-----------|-----------|--------|----|---------------------:|
| 0.05      | 0.200     | **0.583** | **0.298** | **0** |
| 0.10      | 0.200     | 0.417  | 0.270 | 1 |
| 0.15      | 0.000     | 0.250  | 0.000 | 3 |
| 0.20      | 0.000     | 0.250  | 0.000 | 3 |
| 0.30      | 0.000     | 0.183  | 0.000 | 3 |

The empirical optimum is 0.05 across all three metrics. Lower thresholds were not tested; 0.05 was permissive enough that further reduction would only add noise.

**What this tells you:**

- The reranker doesn't produce calibrated scores. A score of 0.3 doesn't mean "30% confident this is relevant"; it means "30% of the way through this model's score distribution for this kind of text."
- The default threshold was inherited from the reranker's training-data distribution, which is not the building-codes domain.
- Without measurement, no one would have noticed the 30% silent-failure rate. The system "worked" in the sense that it didn't crash.

---

## Limitations

**Small eval set.** 10 findings is enough to detect gross regression but not statistically robust. A 100-finding set would change absolute numbers (likely increasing F1 as the long tail averages out) and could justify a different threshold.

**LLM-as-judge labels.** Ground truth was generated by an LLM and human-verified. A fully human-labeled set is the gold standard but expensive. The current set is appropriate for catching obvious errors and tracking trends, not for publishing.

**Single query construction.** The query is always `{category} {issue} {visual_evidence[:120]}`. Variations could be tested: leading vs trailing category, with vs without visual evidence, different truncation lengths.

**Single corpus.** All evaluations use the same BIS-1893, NFPA-70, NFPA-101 corpus. Re-tuning would be needed for a different domain (e.g., medical compliance, financial regulations).

**No fairness or bias evaluation.** The system makes recommendations about building safety; biases in the source documents propagate into the retrieval. Out of scope for this eval framework.

---

## Future work

If this project continued, the eval framework would extend in these directions:

1. **Expand to 100+ labeled findings.** Hire annotators or use a larger LLM-as-judge run with multiple judges and inter-rater reliability.
2. **End-to-end eval.** Currently retrieval is evaluated independently of the compliance LLM. An end-to-end eval would measure: given a finding, does the system produce the right violation citing the right code section? Requires labels at the violation level, not just the chunk level.
3. **Regression suite in CI.** Run the eval on every PR. Fail CI if F1 drops more than 5% from main.
4. **Tuning of other parameters.** Threshold is one knob. Others: top_k after reranking (currently 5), chunk size (currently ~600 tokens), RRF k value (currently 60).
5. **Per-category breakdown.** Some categories may retrieve better than others. A per-category F1 would surface this.

---

## See also

- [ADR-0004: Empirical threshold tuning](adr/0004-empirical-threshold-tuning.md)
- [`rag-pipeline.md`](rag-pipeline.md) — the pipeline being evaluated
- `scripts/evaluate_retrieval.py` — single-threshold eval
- `scripts/sweep_threshold.py` — multi-threshold sweep
- `scripts/diagnose_retrieval.py` — per-finding diagnostic for debugging
- `data/eval/retrieval_eval_set.json` — the labeled eval set
- `data/eval/results/` — historical sweep results