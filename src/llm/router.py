"""LLM router — unified interface across Gemini, Watsonx, Anthropic.

Why LiteLLM under the hood? Single API, 100+ providers, drop-in OpenAI-compat.
But we wrap it in LangChain-compatible interface for LangGraph (Week 2).
"""
from functools import lru_cache
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config.settings import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

ProviderName = Literal["gemini", "watsonx", "anthropic"]

@lru_cache(maxsize=8)
def _get_watsonx_client(model_id: str, temperature: float) -> BaseChatModel:
    """Cached Watsonx ChatWatsonx instance keyed by (model_id, temperature).

    Watsonx instantiation makes three HTTP round-trips (IAM token, project
    verify, foundation model list). For workflows with 5 text agents, that's
    ~15 redundant network calls per run. Caching the client by (model, temp)
    keeps these to a single setup per process per config.

    ChatWatsonx instances are stateless between .invoke() calls and refresh
    their auth token internally, so reusing them is safe.
    """
    from langchain_ibm import ChatWatsonx

    settings = get_settings()
    if not all([settings.watsonx_api_key, settings.watsonx_url, settings.watsonx_project_id]):
        raise ValueError("Watsonx credentials missing in .env")

    logger.info("watsonx.client_cache_miss", model_id=model_id, temperature=temperature)
    return ChatWatsonx(
        model_id=model_id,
        url=settings.watsonx_url,
        apikey=settings.watsonx_api_key,
        project_id=settings.watsonx_project_id,
        params={
            "temperature": temperature,
            "max_tokens": 2000,
            "time_limit": 90000,
        },
    )

def get_llm(
    provider: ProviderName | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    **kwargs,
) -> BaseChatModel:
    """Return a LangChain-compatible chat model.

    Args:
        provider: 'gemini', 'watsonx', or 'anthropic'. Defaults to settings.
        model: Override default model for provider.
        temperature: Sampling temperature (0=deterministic, 1=creative).

    Examples:
        >>> llm = get_llm()  # uses default (Gemini)
        >>> llm = get_llm("watsonx")
        >>> response = llm.invoke("Hello")
    """
    settings = get_settings()
    provider = provider or settings.default_llm_provider

    logger.info("llm.init", provider=provider, model=model, temperature=temperature)

    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=model or settings.gemini_model,
            google_api_key=settings.google_api_key,
            temperature=temperature,
            timeout=60,  # seconds. Fail fast instead of hanging on overloaded model.
            **kwargs,
        )

    if provider == "watsonx":
        default_model = "meta-llama/llama-3-3-70b-instruct"
        return _get_watsonx_client(
            model_id=model or default_model,
            temperature=temperature,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY missing in .env")

        return ChatAnthropic(
            model=model or "claude-3-5-sonnet-20241022",
            anthropic_api_key=settings.anthropic_api_key,
            temperature=temperature,
            timeout=60.0,  # seconds. Same pattern as Gemini.
            **kwargs,
        )

    raise ValueError(f"Unknown provider: {provider}")


# ─── Quick test (run: python -m src.llm.router) ─────
if __name__ == "__main__":
    from src.utils.logging import configure_logging

    configure_logging()

    print("\nTesting Gemini...")
    llm = get_llm("gemini")
    response = llm.invoke("Say hello in 5 words.")
    print(f"Gemini: {response.content}\n")

    settings = get_settings()
    if settings.watsonx_api_key:
        print("Testing Watsonx...")
        try:
            llm = get_llm("watsonx")
            response = llm.invoke("Say hello in 5 words.")
            print(f"Watsonx: {response.content}\n")
        except Exception as e:
            print(f"Watsonx unavailable ({type(e).__name__}) - skipping, will retry in Week 5\n")
    else:
        print("Watsonx skipped (no credentials)\n")