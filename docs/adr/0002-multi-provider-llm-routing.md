# ADR-0002: Multi-provider LLM routing with vision/text separation

**Status:** Accepted
**Date:** 2026-04-22
**Deciders:** Project author

## Context

The system makes LLM calls from six agents. One agent (inspection) is vision-multimodal; the other five are text-only. Each agent has different latency tolerances and cost sensitivities.

Initial implementation hardcoded a single Gemini client at the base agent level. Two problems surfaced:

1. **Cost asymmetry.** Vision calls are more expensive per token. Text agents make 5× more calls than the vision agent. Forcing all calls through one provider means either overpaying for text or risking rate limits on vision.
2. **Quota fragmentation.** Free tiers across providers have different concurrency and token limits. Using only one provider means hitting that provider's ceiling rapidly.

Three options were considered:

1. **Single provider, fixed.** Simple but inflexible. Hits ceiling quickly under sustained use.
2. **Per-agent hardcoded providers.** Each agent imports its own provider. No central control. Hard to swap for tests or development.
3. **Central router with provider override per task type.** One `get_llm()` function. Defaults via `.env`. Vision agent overrides to a vision-capable provider.

## Decision

Implement a central `src/llm/router.py::get_llm()` that returns LangChain-compatible chat models. Configure two settings:
```
DEFAULT_LLM_PROVIDER=gemini       # for text agents
VISION_LLM_PROVIDER=gemini        # for vision agent (can differ)
```
Vision agent (`src/agents/inspection.py`) overrides `__init__` to read `settings.vision_llm_provider`. All other agents inherit `BaseAgent`'s default behavior.

Three providers are wired: Gemini (`langchain_google_genai`), Watsonx (`langchain_ibm`), and Anthropic (`langchain_anthropic`).

Watsonx instantiation is expensive (three HTTPS round-trips per call: IAM auth, project verify, model list). The router caches Watsonx clients via `@lru_cache(maxsize=8)` keyed on `(model_id, temperature)`. This saves ~24s per workflow with 5 text agents.

## Consequences

**Positive:**
- A single `.env` change switches the entire workflow between providers. Useful for cost optimization, rate-limit avoidance, and A/B comparison.
- Vision and text providers can differ. For example: free Watsonx Llama for text, Gemini for vision. Doubles effective quota.
- Tests can override providers without touching agent code.
- Adding a fourth provider is one `elif provider == ...` branch.

**Negative:**
- Each provider has subtle parameter differences (`max_tokens` vs `max_new_tokens` vs `time_limit`). The router smooths these but the smoothing is implicit and could surprise.
- The `@lru_cache` on the Watsonx factory holds open HTTP sessions. For a long-running process this is fine. For a process forked across multiple workers, each worker has its own cache.

**Neutral:**
- The router could support per-agent provider configuration (e.g., `RISK_LLM_PROVIDER`). Not implemented; the two-level (default + vision) split has been sufficient.