"""Evaluate retrieval quality using RAGAS metrics.

Runs the corpus retriever against a labeled eval set and reports:
- Context Precision: fraction of retrieved chunks that are relevant
- Context Recall:    fraction of expected themes covered by retrieved chunks

Both use Gemini as a judge LLM with caching (subsequent runs are free).

Usage:
    python -m scripts.evaluate_retrieval
    python -m scripts.evaluate_retrieval --min-score 0.2 --top-k 5

Output: prints scores to console, writes detailed report to
data/eval/results/retrieval_eval_<timestamp>.json
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import get_settings
from src.llm.router import get_llm
from src.rag.retriever import CodeRetriever
from src.utils.cache import enable_dev_cache
from src.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

EVAL_SET_PATH = Path("data/eval/retrieval_eval_set.json")
RESULTS_DIR = Path("data/eval/results")


def load_eval_set() -> list[dict]:
    """Load the eval set."""
    if not EVAL_SET_PATH.exists():
        raise FileNotFoundError(f"Eval set not found at {EVAL_SET_PATH}")
    return json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))


def run_retrieval(query: str, retriever: CodeRetriever, top_k: int, min_score: float) -> list[dict]:
    """Run retrieval, return chunks above the score threshold."""
    results = retriever.search(f"{query}", top_k=top_k)
    kept = [r for r in results if r.score >= min_score]
    return [
        {
            "text": r.text[:500],  # truncate for eval
            "score": r.score,
            "source": r.regulation_source,
            "source_file": r.source_file,
            "page": r.page,
        }
        for r in kept
    ]


def run_ragas_eval(eval_set: list[dict], retriever: CodeRetriever, top_k: int, min_score: float) -> dict:
    """Run RAGAS-style evaluation.

    For each eval item:
    1. Run retrieval
    2. Ask Gemini (via existing router): score precision and recall against expected_themes

    Returns aggregate scores plus per-item details.
    """
    judge_llm = get_llm(temperature=0.0)  # deterministic judging

    per_item_results = []

    for idx, item in enumerate(eval_set):
        finding = item["finding"]
        expected_themes = item["expected_themes"]
        item_id = item["id"]

        logger.info(f"eval.start  id={item_id} finding={finding[:60]}")
        chunks = run_retrieval(finding, retriever, top_k=top_k, min_score=min_score)
        logger.info(f"eval.retrieved  id={item_id} kept={len(chunks)}")

        if not chunks:
            per_item_results.append({
                "id": item_id,
                "finding": finding,
                "chunks_retrieved": 0,
                "context_precision": 0.0,
                "context_recall": 0.0,
                "notes": "No chunks retrieved (all below threshold)",
            })
            continue

        # Precision: judge whether each chunk is relevant to the finding
        precision_scores = []
        for chunk in chunks:
            prompt = (
                "You are an expert in building codes and inspection compliance.\n\n"
                f"FINDING: {finding}\n"
                f"EXPECTED THEMES: {', '.join(expected_themes)}\n\n"
                f"RETRIEVED EXCERPT:\n{chunk['text']}\n\n"
                "Is this excerpt relevant to the finding and themes? Answer ONLY 'yes' or 'no'."
            )
            try:
                resp = judge_llm.invoke(prompt)
                txt = (getattr(resp, "content", "") or str(resp)).strip().lower()
                precision_scores.append(1.0 if txt.startswith("yes") else 0.0)
            except Exception as e:
                logger.warning(f"eval.precision_judge_failed  id={item_id} error={str(e)[:100]}")
                precision_scores.append(0.0)

        precision = sum(precision_scores) / len(precision_scores) if precision_scores else 0.0

        # Recall: judge whether expected themes appear in retrieved chunks
        combined_text = "\n\n".join(c["text"] for c in chunks)[:6000]
        theme_hits = []
        for theme in expected_themes:
            prompt = (
                "You are an expert in building codes and inspection compliance.\n\n"
                f"THEME: {theme}\n\n"
                f"RETRIEVED EXCERPTS (combined):\n{combined_text}\n\n"
                "Do the excerpts collectively cover this theme? Answer ONLY 'yes' or 'no'."
            )
            try:
                resp = judge_llm.invoke(prompt)
                txt = (getattr(resp, "content", "") or str(resp)).strip().lower()
                theme_hits.append(1.0 if txt.startswith("yes") else 0.0)
            except Exception as e:
                logger.warning(f"eval.recall_judge_failed  id={item_id} error={str(e)[:100]}")
                theme_hits.append(0.0)

        recall = sum(theme_hits) / len(theme_hits) if theme_hits else 0.0

        per_item_results.append({
            "id": item_id,
            "finding": finding,
            "chunks_retrieved": len(chunks),
            "context_precision": round(precision, 3),
            "context_recall": round(recall, 3),
            "themes": dict(zip(expected_themes, theme_hits)),
            "top_score": chunks[0]["score"],
            "min_score": chunks[-1]["score"],
        })

        logger.info(
            f"eval.done  id={item_id} precision={precision:.2f} recall={recall:.2f}"
        )

    # Aggregate
    mean_precision = sum(r["context_precision"] for r in per_item_results) / len(per_item_results)
    mean_recall = sum(r["context_recall"] for r in per_item_results) / len(per_item_results)

    # F1: balanced average
    if mean_precision + mean_recall > 0:
        f1 = 2 * (mean_precision * mean_recall) / (mean_precision + mean_recall)
    else:
        f1 = 0.0

    return {
        "config": {"top_k": top_k, "min_score": min_score},
        "summary": {
            "mean_precision": round(mean_precision, 3),
            "mean_recall": round(mean_recall, 3),
            "f1_score": round(f1, 3),
            "items_with_zero_chunks": sum(1 for r in per_item_results if r["chunks_retrieved"] == 0),
            "total_items": len(per_item_results),
        },
        "per_item": per_item_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.3)
    parser.add_argument("--limit", type=int, default=None, help="Limit number of eval items (for quota saving)")
    args = parser.parse_args()

    configure_logging()
    enable_dev_cache()

    eval_set = load_eval_set()
    if args.limit:
        eval_set = eval_set[:args.limit]

    logger.info(f"eval.config  items={len(eval_set)} top_k={args.top_k} min_score={args.min_score}")

    retriever = CodeRetriever()
    results = run_ragas_eval(eval_set, retriever, top_k=args.top_k, min_score=args.min_score)

    # Print summary
    s = results["summary"]
    print("\n" + "=" * 72)
    print("RETRIEVAL EVALUATION RESULTS")
    print("=" * 72)
    print(f"Config: top_k={args.top_k}  min_score={args.min_score}")
    print(f"Items:           {s['total_items']}")
    print(f"Mean precision:  {s['mean_precision']}")
    print(f"Mean recall:     {s['mean_recall']}")
    print(f"F1 score:        {s['f1_score']}")
    print(f"Zero-chunk items:{s['items_with_zero_chunks']}")
    print()
    print("Per-item breakdown:")
    print("-" * 72)
    for r in results["per_item"]:
        print(
            f"  {r['id']:30}  chunks={r['chunks_retrieved']:>2}  "
            f"prec={r['context_precision']:.2f}  rec={r['context_recall']:.2f}"
        )

    # Save detailed report
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"retrieval_eval_{timestamp}_t{args.min_score}.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDetailed results: {out_path}")


if __name__ == "__main__":
    main()