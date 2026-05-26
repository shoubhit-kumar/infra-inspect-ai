# Tests

Fast, focused unit tests for `infra-inspect-ai`.

## Running

```bash
pytest -v                     # all tests
pytest tests/test_schemas.py  # one file
pytest -k "severity"           # tests matching keyword
```

Target: all green in under 3 seconds.

## What's tested

| File | Covers |
|------|--------|
| `test_schemas.py` | Pydantic validation: required fields, length constraints, enum values |
| `test_change_detection.py` | Severity ranking, cosine math, lexical + semantic classification, category gate |
| `test_risk_helpers.py` | `_compute_highest_risk_category` deterministic aggregation |
| `test_workflow_helpers.py` | `_derive_status`, conditional routing edges |

## What's deliberately NOT tested

| Component | Reason |
|-----------|--------|
| Agent `.run()` methods | All make real LLM calls. Tested via end-to-end workflow runs in `scripts/`. |
| FAISS retrieval | Slow (loads ~500MB index). Covered by `scripts/evaluate_retrieval.py`. |
| MCP servers | Subprocess setup is environment-dependent. Tested manually via `scripts/test_mcp_*.py`. |
| Streamlit UI | UI testing requires separate infrastructure (Playwright). Out of scope. |
| Watsonx integration | Costs quota, depends on external service. Covered by `scripts/test_watsonx.py`. |

## Fixtures

`conftest.py` provides factories so tests don't drown in boilerplate:

- `make_finding(**overrides)` - builds a valid `InspectionFinding`
- `make_historical(**overrides)` - builds a valid `HistoricalFinding`
- `fake_embedder` - deterministic 16-dim "embedder" so semantic tests don't load real BGE