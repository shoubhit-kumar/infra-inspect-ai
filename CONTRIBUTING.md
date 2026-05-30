# Contributing to infra-inspect-ai

Thank you for considering a contribution. This document covers how the project is organized for contributors, the local development loop, the conventions the codebase follows, and what to expect during review.

The project is small-scale and primarily author-maintained. Issues and discussions are welcome; pull requests are welcome but will be reviewed against the conventions below.

## Table of Contents

- [Getting set up](#getting-set-up)
- [Development loop](#development-loop)
- [Where things live](#where-things-live)
- [Code conventions](#code-conventions)
- [Testing conventions](#testing-conventions)
- [Documentation conventions](#documentation-conventions)
- [Commit and PR conventions](#commit-and-pr-conventions)
- [Reporting issues](#reporting-issues)
- [Code of conduct](#code-of-conduct)

---

## Getting set up

```bash
git clone https://github.com/shoubhit-kumar/infra-inspect-ai.git
cd infra-inspect-ai

python -m venv .venv
source .venv/bin/activate                    # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[all]"
pre-commit install                            # optional but recommended

cp .env.example .env                          # fill in at least GOOGLE_API_KEY
```

For a working end-to-end environment, you also need:
- Tesseract OCR (only for ingestion)
- Poppler (only for ingestion)
- The source PDFs in `data/building_codes/` (gitignored due to licensing)

See [`docs/deployment.md`](docs/deployment.md) for full local-setup details.

---

## Development loop

The fast inner loop is the unit tests:

```bash
pytest -v                          # ~5 seconds on warm cache
```

The slower outer loop is the workflow:

```bash
python -m scripts.test_workflow    # ~3 minutes (real LLM calls)
```

The API loop:

```bash
uvicorn src.api.app:app --reload   # auto-reloads on file changes
```

When changing retrieval code, the eval scripts validate behavior:

```bash
python -m scripts.evaluate_retrieval --threshold 0.05
python -m scripts.sweep_threshold
```

Before opening a PR:

```bash
pytest                              # all tests pass
ruff check src tests                # no lint issues
ruff format --check src tests       # formatted
```

---

## Where things live

The repo follows a strict layout. New code goes into the corresponding layer.
```
src/
├── agents/         ← Per-agent logic (one file per agent)
├── api/            ← FastAPI app, routes, middleware
├── config/         ← Pydantic Settings
├── graph/          ← LangGraph workflow definition
├── llm/            ← LLM router (multi-provider)
├── mcp_clients/    ← MCP connection manager + client
├── mcp_servers/    ← MCP server implementations
├── memory/         ← SQLAlchemy models + repository
├── prompts/        ← System and user prompts per agent
├── rag/            ← Retrieval pipeline (FAISS, BM25, RRF, reranker)
├── schemas/        ← Pydantic models for cross-layer contracts
├── tracing/        ← Langfuse setup and span helpers
└── utils/          ← Logging, cache, structured output
tests/              ← Unit tests (no LLM calls, no real models)
scripts/            ← CLI runners, evaluation, ingestion
data/               ← Corpora, indexes, sample photos, outputs (mostly gitignored)
docs/               ← Engineering documentation + ADRs
```
When unsure where new code belongs, check `docs/architecture.md` for the layer responsibilities.

---

## Code conventions

### Style

The codebase uses [ruff](https://docs.astral.sh/ruff/) for both linting and formatting. Configuration is in `pyproject.toml`.

- Line length: 100
- Indent: 4 spaces
- Imports: sorted by ruff (PEP 8 groups)
- Quotes: double for strings, single only when nested

### Types

The codebase uses Python 3.12 syntax for type hints (`str | None` instead of `Optional[str]`, `list[X]` instead of `List[X]`).

Type hints are mandatory on:
- Function signatures (parameters and return types)
- Pydantic model fields
- Public class attributes

Type hints are optional on:
- Internal local variables (when obvious from context)
- Loop variables

`Any` is reserved for genuine `Any` cases (e.g., LangChain message content blocks). When tempted to use `Any`, consider a `TypedDict` or `dataclass` first.

### Pydantic models

Every cross-layer contract is a Pydantic model. See `src/schemas/`. Conventions:

- One file per logical group (`inspection.py`, `compliance.py`, etc.)
- Each model has a docstring explaining its role
- Each field has a docstring explaining its semantics
- Field constraints (`min_length`, `ge`, `le`) are used aggressively to fail fast on bad input
- Enums for controlled vocabularies (see `src/schemas/enums.py`)

### Logging

All logs go through structlog (`src/utils/logging.py::get_logger`). No `print()` statements in production code.

Log event names follow `module.action` namespacing:
- `memory.engine_ready`
- `compliance.start`
- `mcp.health.status_change`

Structured fields are passed as kwargs:
```python
logger.info("compliance.retrieved", finding_index=idx, kept_hits=len(strong), total_hits=len(hits))
```

Avoid string interpolation in log messages. Avoid logging at WARN/ERROR for expected conditions (e.g., "no findings"). Reserve those levels for genuine anomalies.

### Imports

- Standard library first
- Third-party second
- First-party (`src.*`) third
- Each group separated by a blank line

Avoid wildcard imports. Avoid relative imports across module boundaries.

When importing for a context manager that's used in a hot path, prefer module-level import. When importing only for a docstring or type hint, consider `TYPE_CHECKING`.

### Errors

The system catches errors at agent boundaries and appends to `state.errors`. Agents do not let exceptions propagate.

Inside an agent:
```python
try:
    result = agent.run(input)
except SpecificException as e:
    logger.error("agent.specific_failure", error=str(e))
    raise  # only if recovery is impossible
```

For exceptions that should kill the process (e.g., FAISS index missing at boot), let them propagate. For exceptions that should degrade gracefully (e.g., an MCP server is down), catch and log.

---

## Testing conventions

The test suite is documented in [`tests/README.md`](tests/README.md). Key rules:

- Tests must run in under 10 seconds total on a warm cache
- Tests must not make real LLM calls
- Tests must not load BGE or the reranker models (use the `fake_embedder` fixture)
- Tests must not require a network connection
- Tests must not depend on test execution order
- Each test does one thing; the test name describes that thing

Tests that violate these rules belong in `scripts/`, not `tests/`. The CLI scripts in `scripts/test_*.py` are integration tests that run against real services.

When adding a new module, ask: which behaviors are pure functions over data? Those go in unit tests. Behaviors that require LLMs, models, or MCP servers go in integration tests.

---

## Documentation conventions

### Code comments

Comments explain *why*, not *what*. The code shows *what*.

Good:
```python
# Defensive: ensure risk_score = impact * probability for every issue.
# LLMs sometimes do the math wrong. Recompute and warn on drift.
for issue in assessment.issues:
    ...
```

Less good:
```python
# Loop through the issues
for issue in assessment.issues:
    ...
```

Avoid TODO comments without an owner or date. If a TODO has lived longer than two months, either fix it, file an issue, or delete it.

### Docstrings

Public functions and classes have docstrings. Internal helpers do not require them (the function name should be self-explanatory; the body is short).

Docstring style: triple-quoted strings, one-line summary on the first line, optional body after a blank line, optional Args/Returns sections.

```python
def _compute_highest_risk_category(issues: list) -> IssueCategory | None:
    """Determine the category contributing the most aggregate risk.

    Deterministic and explainable: sums the risk_score per category and
    returns the category with the highest total. Tie-breaks by issue count.

    Returns None for an empty issue list.
    """
    ...
```

### ADRs

When making a non-obvious architectural decision, write an ADR. See `docs/adr/README.md` for the format. Indicators that an ADR is warranted:

- The decision affects multiple modules
- A reasonable engineer might pick differently
- You can imagine future-you wondering why the code looks this way

### Docs/ updates

When adding a new feature that affects a layer:

- A new agent → update `docs/workflow.md`
- A new RAG component → update `docs/rag-pipeline.md`
- A new tracing integration → update `docs/observability.md`
- A new deployment target → update `docs/deployment.md`

If unsure which doc to update, ask in the PR.

---

## Commit and PR conventions

### Commits

Commit messages follow the conventional structure:
```
<type>: <short summary in imperative mood, lowercase>
<optional body explaining what and why, not how>
```
Types in use in this repo:
- `feat:` — new functionality
- `fix:` — bug fix
- `refactor:` — no behavior change
- `test:` — adding or fixing tests
- `docs:` — documentation only
- `chore:` — tooling, gitignore, dependencies

Examples:
- `feat: add BGE semantic change detection with lexical fallback`
- `fix: compute risk top_category server-side instead of via LLM`
- `docs: write ADR-0008 for correlation IDs`

Avoid commit messages like "WIP", "more fixes", "update". Each commit should be a coherent unit.

### Pull requests

Use the template in `.github/PULL_REQUEST_TEMPLATE.md`. Key sections:

- **What** — the change in one sentence
- **Why** — the problem being solved
- **How** — the approach taken, including any trade-offs
- **Verification** — what you ran to confirm it works
- **Related** — links to issues, ADRs, prior PRs

Small, focused PRs are reviewed faster than large mixed ones. If a change touches multiple layers, consider splitting it. If a refactor and a feature are mixed, split them.

### Review

Pull requests are reviewed against:

1. **Does it work?** Tests pass. Workflow runs end-to-end without new errors.
2. **Is it documented?** Code comments explain non-obvious decisions. Docs are updated if the architecture changed.
3. **Does it fit the project?** No new dependencies without justification. No new layers without architectural alignment.
4. **Is it tested?** Pure functions have unit tests. Integration paths have a script.

Reviews are direct. Suggestions come without preamble. Disagreement is welcome; the goal is the right answer, not consensus.

---

## Reporting issues

Use the templates in `.github/ISSUE_TEMPLATE/`:

- **Bug report** — something behaves incorrectly
- **Feature request** — something is missing that should exist

Before filing:

- Search existing issues — including closed ones
- Reproduce on the main branch (not your fork)
- Include the relevant log lines (with `request_id` if applicable)
- Specify your environment (Python version, OS, which providers you're using)

The system has multiple moving parts. A good bug report includes which agent or component is at fault — not just "the workflow failed".

---

## Code of conduct

Contributors are expected to communicate respectfully, focus discussion on the technical content, and assume good faith. The project follows the [Contributor Covenant](https://www.contributor-covenant.org/) standard.

For private or sensitive concerns, contact shoubhitkr@gmail.com directly.

---

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License (see `LICENSE`).