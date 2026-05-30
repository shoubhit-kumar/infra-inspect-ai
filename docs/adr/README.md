# Architecture Decision Records (ADRs)

This directory captures the substantive architectural decisions made during the development of infra-inspect-ai. Each ADR follows the [Michael Nygard format](https://github.com/joelparkerhenderson/architecture-decision-record/blob/main/templates/decision-record-template-by-michael-nygard/index.md): **Context → Decision → Consequences**.

The intent is not to document every choice — only the ones where:
- The decision wasn't obvious
- A reasonable engineer might pick differently
- The trade-offs are worth remembering

## Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-langgraph-over-langchain-pipelines.md) | Use LangGraph for agent orchestration over LangChain pipelines | Accepted |
| [0002](0002-multi-provider-llm-routing.md) | Multi-provider LLM routing with vision/text separation | Accepted |
| [0003](0003-hybrid-rag-with-rrf-and-reranker.md) | Hybrid retrieval: FAISS + BM25 + RRF + cross-encoder reranker | Accepted |
| [0004](0004-empirical-threshold-tuning.md) | Tune retrieval threshold empirically rather than by intuition | Accepted |
| [0005](0005-server-side-aggregation-over-llm.md) | Compute deterministic aggregations server-side, not via LLM | Accepted |
| [0006](0006-bge-semantic-change-detection.md) | BGE cosine similarity for change detection, with lexical fallback | Accepted |
| [0007](0007-mcp-for-side-effects.md) | Use Model Context Protocol for filesystem, work orders, notifications | Accepted |
| [0008](0008-correlation-ids-end-to-end.md) | Propagate X-Request-ID through every layer for full audit trail | Accepted |

## When to Write a New ADR

Add an ADR when introducing a change that:
- Affects multiple modules or layers
- Has non-obvious trade-offs
- Future maintainers (including future-you) might second-guess
- Required real engineering judgment, not just convention

## Status Values

- **Proposed** — under discussion
- **Accepted** — decision is in effect; code reflects it
- **Deprecated** — no longer recommended for new code; existing code may remain
- **Superseded** — replaced by another ADR (link to the replacement)