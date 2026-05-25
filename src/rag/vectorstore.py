"""FAISS vector store wrapper.

Provides save/load and an unified interface so callers don't need to
know whether the store exists yet or needs creation.
"""
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from src.rag.embeddings import get_embeddings
from src.utils.logging import get_logger

logger = get_logger(__name__)


DEFAULT_INDEX_DIR = Path("data/vector_db/codes_index")


def build_index(
    chunks: list[Document],
    embeddings: Embeddings | None = None,
    index_dir: Path = DEFAULT_INDEX_DIR,
) -> FAISS:
    """Build a FAISS index from chunks and persist to disk.

    Overwrites any existing index at the same path.
    """
    embeddings = embeddings or get_embeddings()
    logger.info("vectorstore.build_start", chunks=len(chunks), path=str(index_dir))

    store = FAISS.from_documents(chunks, embeddings)
    index_dir.mkdir(parents=True, exist_ok=True)
    store.save_local(str(index_dir))

    logger.info("vectorstore.build_done", path=str(index_dir))
    return store


def load_index(
    index_dir: Path = DEFAULT_INDEX_DIR,
    embeddings: Embeddings | None = None,
) -> FAISS:
    """Load a previously persisted FAISS index."""
    if not (index_dir / "index.faiss").exists():
        raise FileNotFoundError(
            f"No FAISS index at {index_dir}. "
            "Run: python -m scripts.ingest_codes"
        )

    embeddings = embeddings or get_embeddings()
    logger.info("vectorstore.load", path=str(index_dir))

    # allow_dangerous_deserialization=True is required for FAISS pickle files.
    # Safe here because we only load indexes we built ourselves.
    return FAISS.load_local(
        str(index_dir),
        embeddings,
        allow_dangerous_deserialization=True,
    )