# infra-inspect-ai

Production-grade agentic AI for building inspection and compliance automation.

**Status:** Day 21/25 complete. Functional end-to-end with deployment, CI/CD, and documentation pending.

## What it does

Takes building inspection photos and produces:
- Findings extracted by a vision LLM
- Compliance violations grounded in NBC/IS/NFPA building codes (RAG)
- Risk-scored issues with prioritization
- Work orders with SLAs, costs, and team routing
- Inspection reports (operational/executive/regulatory)
- Follow-up notifications (Slack/email/in-app via MCP)

## Architecture

Six-agent LangGraph workflow:
```
inspection → compliance → risk → work_orders → documentation → follow_up
```
Each agent has structured Pydantic output, RAG grounding where applicable, and full Langfuse tracing.

## Quick start

```bash
git clone https://github.com/<your-username>/infra-inspect-ai
cd infra-inspect-ai

# Install
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[all]"

# Configure
cp .env.example .env             # then fill in API keys

# Build the RAG index (one-time, takes ~5 min)
python -m scripts.ingest_codes
python -m scripts.build_bm25

# Run the API
python -m scripts.run_api

# Run the UI (separate terminal)
streamlit run app.py
```

## Full documentation

Comprehensive README with architecture diagrams, evaluation results, and deployment guides coming in Day 25.

## License

TBD
