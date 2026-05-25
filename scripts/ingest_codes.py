"""Incremental ingestion of building-code PDFs into a FAISS index.

Processes PDFs one at a time. After each PDF, saves the FAISS index to
disk. If the script is interrupted, re-running picks up where it left off
by skipping PDFs whose chunks are already indexed.

Run:
    python -m scripts.ingest_codes
"""
import json
from pathlib import Path

from langchain_community.vectorstores import FAISS

from src.rag.chunking import chunk_documents
from src.rag.contextual import add_context
from src.rag.embeddings import get_embeddings
from src.rag.ingest import load_pdf
from src.rag.vectorstore import DEFAULT_INDEX_DIR
from src.utils.logging import configure_logging, get_logger

PROGRESS_FILE = DEFAULT_INDEX_DIR / "ingested_files.json"


def _load_progress() -> set[str]:
    """Return set of source filenames already ingested."""
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text()))
    return set()


def _save_progress(done: set[str]) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(sorted(done), indent=2))


def _load_or_create_index(embeddings, sample_doc) -> FAISS:
    """Load existing index from disk, or create a fresh one if none exists."""
    if (DEFAULT_INDEX_DIR / "index.faiss").exists():
        return FAISS.load_local(
            str(DEFAULT_INDEX_DIR),
            embeddings,
            allow_dangerous_deserialization=True,
        )
    # Initialize from one doc so the index has the right dimensions.
    return FAISS.from_documents([sample_doc], embeddings)


def main() -> None:
    configure_logging()
    logger = get_logger("ingest")

    pdf_dir = Path("data/building_codes")
    pdfs = sorted(p for p in pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {pdf_dir}/. Add PDFs and re-run.")
        return

    done = _load_progress()
    todo = [p for p in pdfs if p.name not in done]

    print(f"\nFound {len(pdfs)} PDF(s). Already ingested: {len(done)}. Pending: {len(todo)}.")
    if not todo:
        print("Nothing to do. Delete data/vector_db/codes_index to force re-ingest.")
        return

    embeddings = get_embeddings()
    store: FAISS | None = None

    for i, pdf in enumerate(todo, start=1):
        print(f"\n[{i}/{len(todo)}] {pdf.name}")

        try:
            docs = load_pdf(pdf)
        except Exception as e:
            logger.error("ingest.load_failed", file=pdf.name, error=str(e))
            print(f"  SKIPPED (load failed): {e}")
            continue

        if not docs:
            print("  SKIPPED (no content extracted)")
            continue

        print(f"  Loaded {len(docs)} pages, chunking...")
        chunks = chunk_documents(docs)
        chunks = add_context(chunks)

        if not chunks:
            # OCR may have extracted whitespace/junk only.
            total_chars = sum(len(d.page_content.strip()) for d in docs)
            print(
                f"  SKIPPED (chunking produced 0 chunks; "
                f"{total_chars} chars of raw text across {len(docs)} pages)"
            )
            # Mark as ingested anyway so we do not retry endlessly.
            done.add(pdf.name)
            _save_progress(done)
            continue

        print(f"  Embedding {len(chunks)} chunks (this is the slow part)...")

        if store is None:
            store = _load_or_create_index(embeddings, sample_doc=chunks[0])
            store.add_documents(chunks)
        else:
            store.add_documents(chunks)

        print(f"  Saving index...")
        DEFAULT_INDEX_DIR.mkdir(parents=True, exist_ok=True)
        store.save_local(str(DEFAULT_INDEX_DIR))

        done.add(pdf.name)
        _save_progress(done)
        print(f"  Done. Total indexed PDFs now: {len(done)}.")

    print("\nIngestion complete.")
    print(f"Index at: {DEFAULT_INDEX_DIR}")
    print(f"Ingested PDFs tracked in: {PROGRESS_FILE}")


if __name__ == "__main__":
    main()