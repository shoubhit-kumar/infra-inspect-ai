"""Standalone Watsonx connectivity and structured-output test.

Verifies three things:
  1. Credentials load and can reach the Watsonx endpoint
  2. Plain text invoke works
  3. Structured output via Pydantic schema works (your invoke_with_retry pipeline)

No Gemini quota burned. No workflow run. Just a 2-call ping to Watsonx.

Usage:
    python -m scripts.test_watsonx
    python -m scripts.test_watsonx --model meta-llama/llama-3-3-70b-instruct
"""
from __future__ import annotations

import argparse
import time
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.config.settings import get_settings
from src.llm.router import get_llm
from src.utils.logging import configure_logging, get_logger
from src.utils.structured_output import invoke_with_retry

logger = get_logger(__name__)


class _GreetingOutput(BaseModel):
    """Tiny structured output schema for the test."""
    greeting: Annotated[str, Field(min_length=1, max_length=200)]
    word_count: int = Field(ge=1, le=20)
    tone: Annotated[str, Field(min_length=1, max_length=50)]


def test_credentials_loaded() -> bool:
    """Confirm .env has the three required Watsonx values."""
    settings = get_settings()
    checks = {
        "WATSONX_API_KEY": settings.watsonx_api_key,
        "WATSONX_URL": settings.watsonx_url,
        "WATSONX_PROJECT_ID": settings.watsonx_project_id,
    }

    print("\n[1/3] Checking Watsonx credentials...")
    ok = True
    for key, val in checks.items():
        if val:
            preview = (val[:8] + "...") if len(str(val)) > 12 else val
            print(f"  OK    {key:25} = {preview}")
        else:
            print(f"  MISS  {key:25} = (not set)")
            ok = False

    if not ok:
        print("\n  Credentials incomplete. Set them in .env and try again.")
    return ok


def test_plain_invoke(model: str | None) -> bool:
    """Send a single plain prompt and confirm a response comes back."""
    print("\n[2/3] Plain text invoke...")
    try:
        llm = get_llm("watsonx", model=model, temperature=0.3)
        start = time.time()
        response = llm.invoke("Reply with exactly five words: a polite greeting.")
        elapsed = time.time() - start

        text = getattr(response, "content", str(response))
        print(f"  OK    elapsed={elapsed:.2f}s")
        print(f"  RESP  {text[:200]}")
        return True
    except Exception as e:
        print(f"  FAIL  {type(e).__name__}: {str(e)[:300]}")
        return False


def test_structured_output(model: str | None) -> bool:
    """Run invoke_with_retry against Watsonx to verify the production code path."""
    print("\n[3/3] Structured output via invoke_with_retry...")
    try:
        llm = get_llm("watsonx", model=model, temperature=0.1)

        messages = [
            SystemMessage(content=(
                "You output JSON conforming to the schema. "
                "Be concise. Do not include preamble or explanation."
            )),
            HumanMessage(content=(
                "Produce a greeting object. Use a friendly greeting (max 8 words), "
                "include the exact word count, and label the tone."
            )),
        ]

        start = time.time()
        result = invoke_with_retry(llm, _GreetingOutput, messages, max_retries=1)
        elapsed = time.time() - start

        print(f"  OK    elapsed={elapsed:.2f}s")
        print(f"  greeting    : {result.greeting}")
        print(f"  word_count  : {result.word_count}")
        print(f"  tone        : {result.tone}")
        return True
    except Exception as e:
        print(f"  FAIL  {type(e).__name__}: {str(e)[:500]}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default=None,
        help="Watsonx model ID. Defaults to meta-llama/llama-3-3-70b-instruct.",
    )
    args = parser.parse_args()

    configure_logging()

    print("=" * 70)
    print("WATSONX CONNECTIVITY TEST")
    print("=" * 70)

    if not test_credentials_loaded():
        return

    plain_ok = test_plain_invoke(args.model)
    if not plain_ok:
        print("\nPlain invoke failed. Skipping structured output test.")
        return

    structured_ok = test_structured_output(args.model)

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Credentials      : OK")
    print(f"  Plain invoke     : {'OK' if plain_ok else 'FAIL'}")
    print(f"  Structured output: {'OK' if structured_ok else 'FAIL'}")

    if plain_ok and structured_ok:
        print("\n  Watsonx is wired correctly. You can use it as a fallback by setting")
        print("  DEFAULT_LLM_PROVIDER=watsonx in .env (or pass provider='watsonx' in code).")
    else:
        print("\n  Issues detected above. See error messages.")


if __name__ == "__main__":
    main()