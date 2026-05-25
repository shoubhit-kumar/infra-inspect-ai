"""Inspect raw retrieval results for one query to see what's being ranked.

No LLM calls. Just shows the top 5 retrieved chunks with their scores
and sources for the query you provide.

Usage:
    python -m scripts.diagnose_retrieval "Exposed and frayed wiring with damaged insulation"
"""
import argparse

from src.rag.retriever import CodeRetriever
from src.utils.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", type=str)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    configure_logging()

    retriever = CodeRetriever()
    results = retriever.search(args.query, top_k=args.top_k)

    print("\n" + "=" * 78)
    print(f"QUERY: {args.query}")
    print("=" * 78)
    print(f"\nTop {len(results)} retrieved chunks:\n")

    for i, r in enumerate(results, 1):
        passes_03 = "PASSES" if r.score >= 0.3 else "FILTERED"
        passes_015 = "PASSES" if r.score >= 0.15 else "FILTERED"
        print(f"--- Hit #{i}  score={r.score:.3f}  [@0.3:{passes_03} @0.15:{passes_015}] ---")
        print(f"Source: {r.regulation_source} | {r.source_file} p.{r.page}")
        print(f"Text: {r.text[:300]}...")
        print()


if __name__ == "__main__":
    main()