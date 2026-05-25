"""Resilient structured output helpers.

Wraps LangChain's `with_structured_output` with retry-on-validation-failure.
When the LLM produces a response that violates the Pydantic schema, we
re-prompt with the validation error so the model can correct itself.
"""
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from src.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

def invoke_with_retry(
    llm: BaseChatModel,
    schema: type[T],
    messages: list[BaseMessage],
    max_retries: int = 2,
) -> T:
    """Call an LLM with structured output, retrying on validation errors.

    Now instrumented with Langfuse generation spans for token tracking,
    latency, and cost (when supported by the underlying provider).
    """
    from src.tracing.setup import observe_llm

    # Try to extract a model name for the span
    model_name = (
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or getattr(llm, "_llm_type", "unknown")
    )

    structured_llm = llm.with_structured_output(schema)
    current_messages = list(messages)
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        # Each attempt is its own generation span - so retries show clearly.
        span_name = f"llm.{schema.__name__}"
        if attempt > 0:
            span_name = f"llm.{schema.__name__}.retry{attempt}"

        try:
            with observe_llm(
                name=span_name,
                model=str(model_name),
                messages=current_messages,
                metadata={"schema": schema.__name__, "attempt": attempt},
            ) as gen:
                result = structured_llm.invoke(current_messages)

                if gen:
                    # Record the structured output as the generation's output
                    try:
                        gen.update(output=result.model_dump(mode="json"))
                    except Exception:
                        gen.update(output=str(result)[:1000])

                return result

        except (ValidationError, Exception) as e:
            last_error = e
            error_text = str(e)

            is_parse_error = (
                isinstance(e, ValidationError)
                or "OUTPUT_PARSING_FAILURE" in error_text
                or "Failed to parse" in error_text
            )
            if not is_parse_error or attempt == max_retries:
                raise

            logger.warning(
                "structured_output.retry",
                attempt=attempt + 1,
                error=error_text[:200],
            )

            current_messages.append(
                HumanMessage(
                    content=(
                        "Your previous response failed schema validation with this error:\n\n"
                        f"{error_text}\n\n"
                        "Please regenerate the response, strictly conforming to the schema. "
                        "Pay special attention to string length limits and required fields. "
                        "Keep all factual content; just adjust to fit the schema."
                    )
                )
            )

    assert last_error is not None
    raise last_error