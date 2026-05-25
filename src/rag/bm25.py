"""BM25 sparse retrieval over the corpus.

BM25 = bag-of-words term matching. Cannot understand meaning, but is
unbeatable for exact-term queries like 'IS 732' or 'Section 4.2.3'.

We build a separate BM25 index that mirrors the documents in the FAISS
store. Both indices answer the same queries; we combine their results
in hybrid.py via Reciprocal Rank Fusion.
"""
import pickle
import re
from pathlib import Path

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from src.utils.logging import get_logger

logger = get_logger(__name__)


DEFAULT_BM25_PATH = Path("data/vector_db/bm25_index.pkl")


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, alphanumeric tokens.

    Production option: use spaCy or NLTK for stemming + stopword removal.
    For technical docs, simple wins because we want exact terms like
    'IS' and '732' kept intact.
    """
    return re.findall(r"\w+", text.lower())


class BM25Retriever:
    """In-memory BM25 retriever over a list of Documents."""

    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        # Tokenize each document for BM25.
        tokenized = [_tokenize(d.page_content) for d in documents]
        self.bm25 = BM25Okapi(tokenized)
        logger.info("bm25.init", documents=len(documents))

    def search(self, query: str, top_k: int = 5) -> list[tuple[Document, float]]:
        """Return top_k (document, score) pairs for the query."""
        tokens = _tokenize(query)
        scores = self.bm25.get_scores(tokens)
        # Get top_k indices
        ranked = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[:top_k]
        return [(self.documents[i], float(scores[i])) for i in ranked]

    def save(self, path: Path = DEFAULT_BM25_PATH) -> None:
        """Persist the BM25 index and documents."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({"documents": self.documents, "bm25": self.bm25}, f)
        logger.info("bm25.saved", path=str(path), documents=len(self.documents))

    @classmethod
    def load(cls, path: Path = DEFAULT_BM25_PATH) -> "BM25Retriever":
        """Load a previously saved BM25 index."""
        if not path.exists():
            raise FileNotFoundError(
                f"No BM25 index at {path}. Run: python -m scripts.build_bm25"
            )
        with path.open("rb") as f:
            data = pickle.load(f)
        obj = cls.__new__(cls)  # bypass __init__
        obj.documents = data["documents"]
        obj.bm25 = data["bm25"]
        logger.info("bm25.loaded", path=str(path), documents=len(obj.documents))
        return obj