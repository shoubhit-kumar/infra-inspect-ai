"""Local embeddings via sentence-transformers.

We use HuggingFace's BGE family. Free, runs on CPU, no API calls.
The 'small' variant gives 384-dim embeddings - good quality, fast.
"""
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings

from src.utils.logging import get_logger

logger = get_logger(__name__)


# Model choice rationale:
# - BAAI/bge-small-en-v1.5 is small (~130MB), fast on CPU, strong on
#   retrieval benchmarks. Great default for English technical text.
# - For multilingual content, swap to BAAI/bge-m3.
# - For higher quality at 4x size, swap to BAAI/bge-large-en-v1.5.
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


@lru_cache
def get_embeddings(model_name: str = DEFAULT_EMBEDDING_MODEL) -> Embeddings:
    """Return a cached embedding model instance.

    First call downloads the model (~130MB) into the HuggingFace cache.
    Subsequent calls in the same process reuse the loaded model.
    """
    logger.info("embeddings.init", model=model_name)
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},  # CPU is fine for ingest + query
        encode_kwargs={"normalize_embeddings": True},  # required for cosine
    )