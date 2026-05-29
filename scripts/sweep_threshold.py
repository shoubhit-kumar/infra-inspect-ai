"""Run retrieval eval at multiple thresholds and chart the results.

Reuses the same eval set and judge logic from evaluate_retrieval.py.
After the first threshold runs, subsequent thresholds reuse cached judge
calls for chunks they have in common.

Output: data/eval/results/threshold_sweep_<timestamp>.png
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt

from src.rag.retriever import CodeRetriever
from src.utils.cache import enable_dev_cache
from src.utils.logging import configure_logging, get_logger
from scripts.evaluate_retrieval import load_eval_set, run_ragas_eval

logger = get_logger(__name__)

THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.30]
RESULTS_DIR = Path("data/eval/results")


def main() -> None:
    configure_logging()
    enable_dev_cache()

    eval_set = load_eval_set()[:5]  # half-size for quota
    retriever = CodeRetriever()

    sweep_results = []
    for threshold in THRESHOLDS:
        logger.info(f"sweep.start  threshold={threshold}")
        result = run_ragas_eval(
            eval_set=eval_set,
            retriever=retriever,
            top_k=5,
            min_score=threshold,
        )
        sweep_results.append({
            "threshold": threshold,
            "precision": result["summary"]["mean_precision"],
            "recall": result["summary"]["mean_recall"],
            "f1": result["summary"]["f1_score"],
            "zero_chunk_items": result["summary"]["items_with_zero_chunks"],
        })
        logger.info(
            f"sweep.done  threshold={threshold} "
            f"P={result['summary']['mean_precision']:.3f} "
            f"R={result['summary']['mean_recall']:.3f} "
            f"F1={result['summary']['f1_score']:.3f}"
        )

    # --- Print table ---
    print("\n" + "=" * 72)
    print("THRESHOLD SWEEP RESULTS")
    print("=" * 72)
    print(f"{'Threshold':>10}  {'Precision':>10}  {'Recall':>8}  {'F1':>6}  {'Zero-chunk':>10}")
    print("-" * 72)
    for r in sweep_results:
        print(
            f"{r['threshold']:>10.2f}  {r['precision']:>10.3f}  "
            f"{r['recall']:>8.3f}  {r['f1']:>6.3f}  {r['zero_chunk_items']:>10}"
        )

    # --- Chart ---
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    thresholds = [r["threshold"] for r in sweep_results]
    precisions = [r["precision"] for r in sweep_results]
    recalls = [r["recall"] for r in sweep_results]
    f1s = [r["f1"] for r in sweep_results]
    zero_counts = [r["zero_chunk_items"] for r in sweep_results]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Left: P/R/F1 curves
    ax1.plot(thresholds, precisions, marker="o", label="Precision", linewidth=2)
    ax1.plot(thresholds, recalls, marker="s", label="Recall", linewidth=2)
    ax1.plot(thresholds, f1s, marker="^", label="F1", linewidth=2, linestyle="--")
    ax1.set_xlabel("MIN_RETRIEVAL_SCORE threshold")
    ax1.set_ylabel("Score")
    ax1.set_title("Retrieval quality vs threshold")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 1.05)

    # Right: zero-chunk count (failure mode)
    ax2.bar(thresholds, zero_counts, width=0.02, color="crimson")
    ax2.set_xlabel("MIN_RETRIEVAL_SCORE threshold")
    ax2.set_ylabel("Findings with zero chunks (of 10)")
    ax2.set_title("Empty retrievals vs threshold")
    ax2.set_ylim(0, len(thresholds) and 10)
    ax2.grid(True, alpha=0.3, axis="y")

    fig.suptitle("Retrieval threshold sweep", fontsize=14)
    plt.tight_layout()

    chart_path = RESULTS_DIR / f"threshold_sweep_{timestamp}.png"
    plt.savefig(chart_path, dpi=120, bbox_inches="tight")
    print(f"\nChart saved: {chart_path}")

    # Save raw results too
    json_path = RESULTS_DIR / f"threshold_sweep_{timestamp}.json"
    json_path.write_text(json.dumps(sweep_results, indent=2), encoding="utf-8")
    print(f"Data saved:  {json_path}")


if __name__ == "__main__":
    main()