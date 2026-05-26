"""Application startup helpers - warm up heavy resources before serving requests.

Called by every workflow entry point (test scripts, FastAPI lifespan, Streamlit)
so the first real workflow doesn't pay cold-start costs for ML models.
"""
from __future__ import annotations

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Load .env BEFORE any HuggingFace imports so HF_TOKEN is picked up.
from dotenv import load_dotenv
load_dotenv()


def warm_up_rag_stack() -> None:
    """Eagerly load RAG models so the first retrieval is hot.

    Loads (in order):
      1. BGE-small-en-v1.5 embeddings (~130MB, ~5s cold)
      2. BGE-reranker-base cross-encoder (~280MB, ~5s cold)

    Total time at boot: ~10s. Saves ~10s on first compliance retrieval.

    Idempotent and best-effort: failures are logged but do not raise,
    because the lazy fallback path still works for both models.
    """
    logger.info("bootstrap.warm_up.start")

    # Embeddings (used by retriever)
    try:
        from src.rag.embeddings import get_embeddings
        model = get_embeddings()
        # Throwaway encode to JIT-compile forward pass and warm tokenizer.
        _ = model.embed_query("warm up the embedding model")
        logger.info("bootstrap.embeddings_warm")
    except Exception as e:
        logger.warning("bootstrap.embeddings_warm_failed", error=str(e))

    # Cross-encoder reranker
    try:
        from src.rag.reranker import warm_up_reranker
        warm_up_reranker()
    except Exception as e:
        logger.warning("bootstrap.reranker_warm_failed", error=str(e))

    logger.info("bootstrap.warm_up.done")