"""Hybrid retrieval: dense (FAISS) + sparse (BM25) via Reciprocal Rank Fusion.

RRF formula:
    score(d) = sum over retrievers r of  1 / (k + rank_r(d))

where k is a constant (typically 60). RRF cares about *rank* in each
retriever, not raw scores. This is robust to score-scale differences
between retrievers - a real advantage over score-normalization methods.
"""
from collections import defaultdict
from dataclasses import dataclass

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from src.rag.bm25 import BM25Retriever
from src.utils.logging import get_logger

logger = get_logger(__name__)

# RRF constant - 60 is the original paper's recommendation.
RRF_K = 60


@dataclass
class HybridHit:
    """A single hybrid retrieval result."""
    document: Document
    rrf_score: float
    dense_rank: int | None
    sparse_rank: int | None


def reciprocal_rank_fusion(
    dense_results: list[Document],
    sparse_results: list[Document],
    top_k: int = 10,
    k: int = RRF_K,
) -> list[HybridHit]:
    """Fuse two ranked lists into one using RRF.

    Identifies the same document across the two lists by `page_content`
    (since LangChain Documents do not have stable IDs by default).
    """
    # Map content -> (document, dense_rank, sparse_rank)
    entries: dict[str, dict] = {}

    for rank, doc in enumerate(dense_results, start=1):
        entries[doc.page_content] = {
            "doc": doc,
            "dense_rank": rank,
            "sparse_rank": None,
        }

    for rank, doc in enumerate(sparse_results, start=1):
        existing = entries.get(doc.page_content)
        if existing:
            existing["sparse_rank"] = rank
        else:
            entries[doc.page_content] = {
                "doc": doc,
                "dense_rank": None,
                "sparse_rank": rank,
            }

    # Compute RRF score for each unique document
    hits: list[HybridHit] = []
    for entry in entries.values():
        score = 0.0
        if entry["dense_rank"]:
            score += 1.0 / (k + entry["dense_rank"])
        if entry["sparse_rank"]:
            score += 1.0 / (k + entry["sparse_rank"])
        hits.append(
            HybridHit(
                document=entry["doc"],
                rrf_score=score,
                dense_rank=entry["dense_rank"],
                sparse_rank=entry["sparse_rank"],
            )
        )

    hits.sort(key=lambda h: h.rrf_score, reverse=True)
    return hits[:top_k]


def hybrid_search(
    query: str,
    dense_store: FAISS,
    bm25: BM25Retriever,
    candidates_per_retriever: int = 20,
    top_k: int = 10,
) -> list[HybridHit]:
    """Run hybrid retrieval and return fused top_k results."""
    # Dense retrieval
    dense_docs = dense_store.similarity_search(query, k=candidates_per_retriever)
    # Sparse retrieval
    sparse_pairs = bm25.search(query, top_k=candidates_per_retriever)
    sparse_docs = [doc for doc, _ in sparse_pairs]

    fused = reciprocal_rank_fusion(dense_docs, sparse_docs, top_k=top_k)
    logger.info(
        "hybrid.search",
        query=query[:80],
        dense_n=len(dense_docs),
        sparse_n=len(sparse_docs),
        fused_n=len(fused),
    )
    return fused