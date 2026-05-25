"""On-disk LLM response cache for development.

Wraps any chat model so identical prompts return cached responses.
Drastically reduces API calls during iterative development.

Production behavior:
- enabled if settings.environment == 'development'
- disabled in staging/production (we want fresh outputs there)
"""
from pathlib import Path

from langchain_community.cache import SQLiteCache
from langchain_core.globals import set_llm_cache

from src.config.settings import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

_CACHE_PATH = Path(".cache/llm_cache.sqlite")


def enable_dev_cache() -> None:
    """Turn on LLM response caching for development.

    Call once at app startup, after configure_logging().
    Production environments skip caching automatically.
    """
    settings = get_settings()
    if settings.environment != "development":
        logger.info("cache.skipped", reason="not_development")
        return

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Suppress the LangChain cache deprecation warning at the warnings level.
    # The warning is about a future default change for allowed_objects;
    # SQLiteCache does not accept that arg in our current version, so we
    # filter the warning until LangChain stabilizes its API.
    import warnings
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
    warnings.filterwarnings(
        "ignore",
        category=LangChainPendingDeprecationWarning,
        module=r"langchain_community\.cache",
    )

    set_llm_cache(SQLiteCache(database_path=str(_CACHE_PATH)))
    logger.info("cache.enabled", path=str(_CACHE_PATH))