"""Interactive retrieval test against the building-codes index.

Run: python -m scripts.test_retrieval
"""
from src.rag.retriever import CodeRetriever
from src.utils.logging import configure_logging


SAMPLE_QUERIES = [
    "fire extinguisher inspection requirements",
    "electrical wiring insulation standards",
    "structural wall crack assessment",
    "water leakage from ceiling plumbing",
    "exposed electrical conductors safety",
]


def main() -> None:
    configure_logging()

    retriever = CodeRetriever()

    print("\nBuilding-codes retrieval test")
    print("=" * 70)
    print("Type a query (or just press Enter to cycle through samples).")
    print("Type 'quit' to exit.\n")

    sample_iter = iter(SAMPLE_QUERIES)

    while True:
        user_input = input("Query> ").strip()
        if user_input.lower() in {"quit", "exit", "q"}:
            break

        if not user_input:
            try:
                query = next(sample_iter)
                print(f"  (sample query: {query})")
            except StopIteration:
                print("  No more samples. Type your own query.")
                continue
        else:
            query = user_input

        results = retriever.search(query, top_k=3)

        if not results:
            print("  No results.\n")
            continue

        for i, r in enumerate(results, 1):
            print(f"\n  [{i}] score={r.score:.4f}  {r.citation()}")
            preview = r.text[:400].replace("\n", " ")
            print(f"      {preview}...")

        print()


if __name__ == "__main__":
    main()