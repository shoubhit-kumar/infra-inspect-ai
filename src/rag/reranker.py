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

def warm_up_reranker(
    model_name: str = DEFAULT_RERANKER,
    dummy_query: str = "warm up the model",
    dummy_doc: str = "this is a placeholder document for jit compilation",
) -> None:
    """Warm up the cross-encoder model at boot to avoid cold-start latency.

    Loads the model into memory and runs one throwaway prediction so the
    tokenizer cache and torch jit-traced forward pass are ready. The first
    real reranker call after this will reuse the cached singleton.

    Idempotent: safe to call multiple times. Subsequent calls are no-ops
    because `get_reranker` is `@lru_cache`-decorated.

    Typical cost: ~3-5s at boot, eliminated from first real retrieval.
    """
    logger.info("reranker.warm_up.start", model=model_name)
    try:
        model = get_reranker(model_name)
        # Throwaway prediction to JIT-compile forward pass and warm tokenizer.
        _ = model.predict([(dummy_query, dummy_doc)])
        logger.info("reranker.warm_up.done", model=model_name)
    except Exception as e:
        # Warm-up failure is non-fatal - the lazy path will still work.
        logger.warning("reranker.warm_up.failed", model=model_name, error=str(e))