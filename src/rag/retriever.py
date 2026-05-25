"""Retrieval orchestration: hybrid retrieval + cross-encoder re-ranking.

Pipeline:
    1. Hybrid search (dense + BM25 via RRF) -> 20 candidates
    2. Cross-encoder re-rank -> top 5
    3. Return as RetrievalResults
"""
from dataclasses import dataclass

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from src.rag.bm25 import BM25Retriever
from src.rag.hybrid import hybrid_search
from src.rag.reranker import rerank
from src.rag.vectorstore import load_index
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RetrievalResult:
    """One retrieved chunk with its score."""
    text: str
    score: float
    source_file: str
    page: int
    regulation_source: str
    chunk_index: int

    def citation(self) -> str:
        return f"{self.regulation_source} | {self.source_file} p.{self.page}"


class CodeRetriever:
    """Hybrid + reranking retriever over the building-codes corpus."""

    def __init__(
        self,
        dense_store: FAISS | None = None,
        bm25: BM25Retriever | None = None,
        use_reranker: bool = True,
    ) -> None:
        self.dense = dense_store or load_index()
        self.bm25 = bm25 or BM25Retriever.load()
        self.use_reranker = use_reranker

    def search(
        self,
        query: str,
        top_k: int = 5,
        candidates: int = 20,
    ) -> list[RetrievalResult]:
        """Search the corpus.
        ...
        """
        from src.tracing.setup import span_retrieval

        with span_retrieval(query=query, metadata={"top_k": top_k, "candidates": candidates}) as span:
            # Stage 1: hybrid retrieval
            hits = hybrid_search(
                query,
                dense_store=self.dense,
                bm25=self.bm25,
                candidates_per_retriever=candidates,
                top_k=candidates,
            )
            candidate_docs = [h.document for h in hits]

            # Stage 2: cross-encoder rerank
            if self.use_reranker and candidate_docs:
                ranked = rerank(query, candidate_docs, top_k=top_k)
                results = [self._to_result(doc, score) for doc, score in ranked]
            else:
                truncated = hits[:top_k]
                results = [self._to_result(h.document, h.rrf_score) for h in truncated]

            if span:
                span.update(output={
                    "hybrid_candidates": len(hits),
                    "results_returned": len(results),
                    "top_score": results[0].score if results else None,
                    "min_score": results[-1].score if results else None,
                    "top_sources": [r.regulation_source for r in results[:3]],
                })
            return results
        
    @staticmethod
    def _to_result(doc: Document, score: float) -> RetrievalResult:
        m = doc.metadata
        display_text = m.get("raw_text") or doc.page_content
        return RetrievalResult(
            text=display_text,
            score=float(score),
            source_file=m.get("source_file", "unknown"),
            page=m.get("page", 0),
            regulation_source=m.get("regulation_source", "INTERNAL"),
            chunk_index=m.get("chunk_index", 0),
        )