"""Cross-encoder re-ranking.

A cross-encoder model takes (query, candidate) pairs and outputs a
relevance score. Slower than embedding-based retrieval (we run the
model per pair) but dramatically more accurate.

Default model: BAAI/bge-reranker-base, ~280MB, CPU-friendly.
"""
from functools import lru_cache

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from src.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_RERANKER = "BAAI/bge-reranker-base"


@lru_cache
def get_reranker(model_name: str = DEFAULT_RERANKER) -> CrossEncoder:
    """Return a cached CrossEncoder instance."""
    logger.info("reranker.init", model=model_name)
    return CrossEncoder(model_name, max_length=512)


def rerank(
    query: str,
    documents: list[Document],
    top_k: int = 5,
    model_name: str = DEFAULT_RERANKER,
) -> list[tuple[Document, float]]:
    """Re-rank documents by relevance to the query.

    Returns (document, score) pairs sorted by score descending,
    truncated to top_k.
    """
    if not documents:
        return []

    model = get_reranker(model_name)
    pairs = [(query, d.page_content) for d in documents]
    scores = model.predict(pairs)

    ranked = sorted(
        zip(documents, scores),
        key=lambda x: float(x[1]),
        reverse=True,
    )
    logger.info("reranker.done", input_count=len(documents), top_k=top_k)
    return [(doc, float(score)) for doc, score in ranked[:top_k]]