# Documentation

Engineering documentation for infra-inspect-ai. Organized in three layers: orientation, deep-dives, and decisions.

## Start here

| Document | Read when |
|----------|-----------|
| [`architecture.md`](architecture.md) | You want the high-altitude system view |
| [`workflow.md`](workflow.md) | You're tracing the agent-by-agent flow |
| [`rag-pipeline.md`](rag-pipeline.md) | You're modifying the retrieval architecture |
| [`observability.md`](observability.md) | You're debugging a request or adding tracing |
| [`eval-methodology.md`](eval-methodology.md) | You're tuning the system empirically |
| [`deployment.md`](deployment.md) | You're moving from dev to production |

## Architecture Decision Records

The `adr/` directory captures decisions where the trade-offs are worth remembering. Read these when you want to understand *why* the codebase looks the way it does. See [`adr/README.md`](adr/README.md) for the full index.

| ADR | Topic |
|-----|-------|
| [0001](adr/0001-langgraph-over-langchain-pipelines.md) | LangGraph for orchestration |
| [0002](adr/0002-multi-provider-llm-routing.md) | Multi-provider LLM routing |
| [0003](adr/0003-hybrid-rag-with-rrf-and-reranker.md) | Hybrid RAG architecture |
| [0004](adr/0004-empirical-threshold-tuning.md) | Empirical threshold tuning |
| [0005](adr/0005-server-side-aggregation-over-llm.md) | Server-side aggregation |
| [0006](adr/0006-bge-semantic-change-detection.md) | BGE semantic change detection |
| [0007](adr/0007-mcp-for-side-effects.md) | MCP for side effects |
| [0008](adr/0008-correlation-ids-end-to-end.md) | End-to-end correlation IDs |

## Asset index

- `hero_trace.png` — Langfuse trace screenshot featured in the README

## How docs are organized

- **README.md (root)** — Project overview, quickstart, headline narratives. Audience: any visitor.
- **docs/*.md (this directory)** — Engineering deep-dives. Audience: anyone modifying or extending the system.
- **docs/adr/*.md** — Decision records. Audience: maintainers asking "why was this done?"
- **tests/README.md** — Test scope and what's intentionally not tested. Audience: contributors writing tests.

When adding new documentation:

- Architecture-level changes → update `architecture.md`
- New agent or workflow node → update `workflow.md`
- New RAG component → update `rag-pipeline.md`
- New tracing or logging integration → update `observability.md`
- New evaluation method → update `eval-methodology.md`
- Deployment target or scaling change → update `deployment.md`
- Non-obvious technical decision → write a new ADR

For project-wide contributing guidelines, see [`CONTRIBUTING.md`](../CONTRIBUTING.md) at the repository root.
```
Status
All docs/ files complete. Save these three. You now have:
```
docs/
├── README.md                    ← just delivered
├── architecture.md              ✓
├── workflow.md                  ✓
├── rag-pipeline.md              ✓
├── observability.md             ✓
├── deployment.md                ← just delivered
├── eval-methodology.md          ← just delivered
├── hero_trace.png               ✓ (already there)
└── adr/
    ├── README.md                ✓
    ├── 0001-langgraph-over-langchain-pipelines.md  ✓
    ├── 0002-multi-provider-llm-routing.md          ✓
    ├── 0003-hybrid-rag-with-rrf-and-reranker.md    ✓
    ├── 0004-empirical-threshold-tuning.md          ✓
    ├── 0005-server-side-aggregation-over-llm.md    ✓
    ├── 0006-bge-semantic-change-detection.md       ✓
    ├── 0007-mcp-for-side-effects.md                ✓
    └── 0008-correlation-ids-end-to-end.md          ✓

