# Deployment

How to run infra-inspect-ai locally, and what's involved in deploying it to a real environment. The system targets developer machines first; production deployment is a documented direction rather than an out-of-the-box capability.

For configuration details, see the README's Configuration section. For architecture, see [`architecture.md`](architecture.md).

---

## Local development

The default deployment is a single Python process on a developer machine. This is what the README's Quickstart describes.

### Requirements

- Python 3.12 or higher
- ~2 GB RAM headroom (BGE embeddings + reranker + FAISS index together use ~960 MB at steady state)
- Disk space for the corpus: ~500 MB for the built FAISS + BM25 indexes, plus the source PDFs
- Tesseract OCR installed (for ingestion only; not needed for queries)
  - Windows: install to `C:\Program Files\Tesseract-OCR\`
  - macOS: `brew install tesseract`
  - Linux: `apt install tesseract-ocr`
- Poppler (for PDF rendering during OCR; ingestion-time only)

### Setup

```bash
git clone https://github.com/shoubhit-kumar/infra-inspect-ai.git
cd infra-inspect-ai
python -m venv .venv
source .venv/bin/activate                    # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[all]"
cp .env.example .env
# Edit .env: add GOOGLE_API_KEY at minimum
```

### One-time corpus ingestion

The source PDFs (BIS-1893, NFPA-70, NFPA-101) are gitignored due to licensing. Drop them into `data/building_codes/` and run:

```bash
python -m scripts.ingest_codes        # ~5 min
python -m scripts.build_bm25          # ~30 sec
```

This produces:
- `data/vector_db/codes_index/` — FAISS index (~500 MB)
- `data/vector_db/bm25_index.pkl` — BM25 index

These are gitignored. Anyone cloning the repo must run ingestion themselves.

### Running

Three entry points, all use the same workflow:

```bash
# CLI workflow on a sample photo
python -m scripts.test_workflow

# FastAPI service
uvicorn src.api.app:app --reload
# Then: http://localhost:8000/docs for OpenAPI UI

# Streamlit UI
streamlit run app.py
# Then: http://localhost:8501
```

---

## What's already production-grade

The system was built with production constraints in mind. The following are not deployment-time concerns; they work out of the box:

- **LLM rate-limit handling.** The router uses `@lru_cache` for Watsonx clients; the structured-output helper retries on parse failure; each provider has explicit timeouts.
- **Graceful degradation.** Agent failures don't kill the workflow. The Langfuse client is optional. MCP server failures are detected by the health monitor and logged.
- **Configuration via environment.** Everything that varies between environments is in `.env`.
- **Health endpoint.** `/health` aggregates per-MCP-server status for orchestrator probes.
- **Correlation IDs.** Every request traceable end-to-end via `X-Request-ID`.
- **Structured logs.** stdout output is JSON-serializable; ready for a log shipper to forward.

---

## What needs work for production

Deploying to a real environment (not a developer machine) requires changes in these areas. None are blockers; all are documented directions.

### 1. Multi-worker concurrency

The current design is single-process. uvicorn can fork workers, but each worker would:

- Load its own copy of BGE (~130 MB) and the reranker (~280 MB)
- Spawn its own three MCP subprocesses
- Hold its own SQLAlchemy connection pool (already singleton per-process via `src/memory/connection.py`)
- Maintain its own in-memory `JobRegistry`

For 4 workers, this is roughly 4× the memory baseline. Acceptable on a 4-core 8 GB instance. Beyond that, externalize:

- **Models:** Run BGE and the reranker as a separate service (TorchServe, Triton, or a thin FastAPI wrapper). Workers fetch over the network.
- **Job registry:** Move to Redis. Already structured to accept that — `JobRegistry` is a class behind `get_job_registry()`.
- **DB:** SQLite serializes writes, so multiple workers write-blocking each other becomes the bottleneck before model memory does. Switch to Postgres (see below).

### 2. SQLite → Postgres

The DB layer uses SQLAlchemy abstractly. Switching to Postgres is roughly a one-line change to the connection string:

```python
# src/memory/store.py
def make_engine(db_path=None, echo=False):
    # Before:
    # return create_engine(f"sqlite:///{db_path}", ...)
    # After:
    return create_engine(os.getenv("DATABASE_URL"), echo=echo, ...)
```

Then add to `.env`:
```
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/infra_inspect
```
Caveats:
- The existing schema uses no SQLite-specific constructs. `DateTime(timezone=True)` works on both.
- Existing data must be migrated. For the demo system, dropping and re-ingesting is simpler than dumping rows.
- The `request_id` column was added with an `ALTER TABLE` for the existing SQLite. For Postgres, the migration is one Alembic revision.

When to do this: more than ~50 concurrent inspections in flight, or multi-worker deployment.

### 3. Vector store externalization

FAISS is in-process. It's fast at ~24K chunks. At ~1M chunks or in a multi-worker setup, externalize:

- **Pinecone:** Managed, pay-per-use. Free tier supports the current scale. Integration is one new file replacing `src/rag/vectorstore.py`.
- **Qdrant:** Self-host or managed. Free cloud tier with quota.
- **Weaviate:** Heavier-weight; built-in modules for hybrid search would replace the custom RRF logic.

The `RetrievalResult` interface in `src/rag/retriever.py` is the abstraction boundary. Any new vector backend implements `search(query, top_k) -> list[RetrievalResult]`.

When to do this: corpus exceeds ~500 MB or workers exceed 2.

### 4. MCP server consolidation or replacement

The three MCP subprocess servers exist primarily for **process isolation and language flexibility**. In production, you'd likely:

- **Replace the filesystem server** with the actual storage backend (S3, GCS).
- **Replace the workorder server** with the actual ticketing system (Jira, ServiceNow).
- **Replace the notification server** with the actual channels (Slack API, SendGrid).

The MCP protocol is the contract; the implementations behind it are interchangeable. A new server can be in any language that has an MCP SDK.

### 5. Authentication

The API has no authentication. Anyone reaching the endpoint can submit inspections for any building. For production:

- **API keys** (simplest): one middleware that checks an `Authorization: Bearer ...` header against a key store.
- **OAuth2** (industry standard): use `fastapi.security.OAuth2PasswordBearer`. Token validation against an external identity provider.
- **Building access control:** add a `(user_id, building_id)` mapping table; reject inspections for unauthorized buildings.

The middleware layer is the right insertion point. The correlation-ID middleware demonstrates the pattern.

### 6. Observability scaling

The Langfuse Cloud free tier handles modest traffic. For production:

- **Self-host Langfuse:** Docker Compose-based deployment. Documentation at langfuse.com.
- **Log aggregation:** Configure structlog to emit JSON (swap `ConsoleRenderer` for `JSONRenderer`). Add a Fluent Bit / Vector / Promtail sidecar to ship to Loki, CloudWatch, or Datadog.
- **Metrics:** Currently none. Adding Prometheus would mean wrapping key code paths with `prometheus_client` counters and histograms, exposing `/metrics`.
- **Alerting:** Alert on `/health` returning non-`ok` status. Alert on log lines matching `level=error` above a threshold.

---

## Containerization (Dockerfile sketch)

A minimal `Dockerfile` for the API service:

```dockerfile
FROM python:3.12-slim

# OS deps for OCR (only needed if you'll ingest at container build time)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[api,rag,mcp,observability]"
COPY src/ ./src/
COPY scripts/ ./scripts/

# Vector store mounted as a volume, not baked into the image
VOLUME ["/app/data"]

EXPOSE 8000
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Note: this is illustrative, not tested. The actual deployment requires deciding:

- Whether the FAISS index lives inside the image or on a mounted volume (volume is more flexible; image is more reproducible)
- How model weights are cached (huggingface_hub cache directory)
- Resource limits (the BGE + reranker + FAISS combo needs ~1 GB RAM headroom)

---

## Render / Railway / Fly.io (single-instance)

The system fits on a single ~1 GB instance, except for the memory consumed by BGE + reranker models at startup. A history note: an attempt to deploy to Render's free tier (512 MB) hit OOM during boot. The 1 GB tier works.

For these platforms:

1. Create the service from the GitHub repo
2. Set the build command: `pip install -e ".[api,rag,mcp,observability]"`
3. Set the start command: `uvicorn src.api.app:app --host 0.0.0.0 --port $PORT`
4. Add environment variables from `.env`
5. Mount or copy in the pre-built vector store (or build it at container build time, which doubles build time but simplifies deployment)

---

## Kubernetes

For production, the natural deployment is K8s:

- **Deployment** with replicas=N
- **Liveness probe** on `/health` (lower stringency: ok if HTTP responds at all)
- **Readiness probe** on `/health` (stricter: ok if `status` field is `ok` or `degraded`)
- **HorizontalPodAutoscaler** based on CPU
- **PersistentVolumeClaim** for the FAISS index (read-only mount)
- **Secrets** for API keys (Gemini, Langfuse, Watsonx)
- **ConfigMap** for non-secret config (URLs, threshold values)

The single-process design constrains scaling: each pod is independent. No shared state between pods unless you externalize the job registry to Redis.

---

## What's not deployable today

- **Multi-region.** No data replication strategy. Single SQLite or single Postgres instance.
- **Zero-downtime model updates.** Replacing BGE or the reranker requires rebuilding the FAISS index. No blue-green for the index file.
- **Per-tenant isolation.** Single database, single FAISS index, single set of MCP servers. Adding tenant isolation requires schema and code changes.

These are out of scope for a portfolio system. Documented here so the deferral is intentional and visible.