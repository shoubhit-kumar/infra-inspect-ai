"""Build a BM25 index from the documents currently in the FAISS store.

This is a one-time operation after FAISS ingestion. Re-run if you
re-ingest the corpus.

    python -m scripts.build_bm25
"""
from src.rag.bm25 import BM25Retriever
from src.rag.vectorstore import load_index
from src.utils.logging import configure_logging


def main() -> None:
    configure_logging()

    print("\nLoading FAISS index to extract documents...")
    store = load_index()

    # FAISS stores documents in docstore._dict
    docs = list(store.docstore._dict.values())
    print(f"  Found {len(docs)} chunks in FAISS.")

    print("Building BM25 index...")
    bm25 = BM25Retriever(docs)

    print("Saving...")
    bm25.save()

    print("\nDone. Now you can run retrieval with hybrid + rerank.")


if __name__ == "__main__":
    main()