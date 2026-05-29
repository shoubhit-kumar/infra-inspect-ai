"""Langfuse tracing setup.

Provides:
- get_langfuse(): a singleton client that ships traces to Langfuse Cloud
- trace_workflow_run(): a context manager wrapping the workflow with a root trace
- span_node(): a context manager wrapping a single agent node with a child span

Design notes:
- We deliberately keep the API thin. Each node-level span is a `with` block,
  not a decorator, because we want full control over span attributes.
- If Langfuse credentials are not set, get_langfuse() returns None and all
  helpers become no-ops. The workflow runs unchanged.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator
from dotenv import load_dotenv
from src.utils.logging import get_logger

# Load .env into os.environ so get_langfuse() can find LANGFUSE_* variables.
# This is a no-op if env is already loaded (idempotent).
load_dotenv()

logger = get_logger(__name__)

# Singleton holder
_client: Any = None
_initialized: bool = False


def get_langfuse() -> Any:
    """Return the global Langfuse client, or None if not configured.

    Idempotent: first call initializes, subsequent calls reuse.
    """
    global _client, _initialized

    if _initialized:
        return _client

    _initialized = True

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.info("langfuse.disabled", reason="missing credentials")
        return None

    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning("langfuse.not_installed", action="pip install langfuse")
        return None

    try:
        _client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        logger.info("langfuse.initialized", host=host)
        return _client
    except Exception as e:
        logger.error("langfuse.init_failed", error=str(e))
        return None


def flush() -> None:
    """Flush pending traces to Langfuse. Call before process exit."""
    client = get_langfuse()
    if client is not None:
        try:
            client.flush()
            logger.info("langfuse.flushed")
        except Exception as e:
            logger.error("langfuse.flush_failed", error=str(e))


@contextmanager
def trace_workflow_run(
    building_id: str,
    photo_count: int,
    inspector_notes: str = "",
    request_id: str = "",
) -> Iterator[Any]:
    """Open a root trace for one workflow invocation.

    Yields the trace object (or None if tracing disabled). Pass it to
    `span_node()` calls inside the workflow so spans nest under this trace.

    If request_id is provided, it's used as the Langfuse session_id so all
    traces from a single request can be filtered together in the Langfuse UI.
    """
    client = get_langfuse()
    if client is None:
        yield None
        return

    trace_kwargs: dict[str, Any] = {
        "name": "infra-inspect-workflow",
        "input": {
            "building_id": building_id,
            "photo_count": photo_count,
            "inspector_notes": inspector_notes[:200],
        },
        "metadata": {
            "workflow_version": "day16",
            "request_id": request_id,
        },
        "tags": ["workflow", "v1"],
    }
    if request_id:
        trace_kwargs["session_id"] = request_id

    trace = client.trace(**trace_kwargs)
    try:
        yield trace
    except Exception as e:
        trace.update(level="ERROR", status_message=str(e)[:500])
        raise
    finally:
        flush()


@contextmanager
def span_node(
    name: str,
    trace: Any = None,
    input_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Open a child span under the current trace.

    Also sets `_current_span` so downstream code can attach child spans
    without having to thread the span object through every call site.
    """
    if trace is None:
        yield None
        return

    span = trace.span(
        name=name,
        input=input_data or {},
        metadata=metadata or {},
    )
    # Set as the current span so retrieval/mcp/llm helpers can nest under it
    token = set_current_span(span)
    try:
        yield span
    except Exception as e:
        span.update(level="ERROR", status_message=str(e)[:500])
        raise
    finally:
        reset_current_span(token)
        span.end()
               
# ============================================================================
# Day 17: Drill-down spans for retrieval, MCP, and LLM calls
# ============================================================================

# Module-level "current trace" so nested code can find the active trace
# without passing it through every function signature. The workflow nodes
# set this when they create a span, and code beneath them reads it.
import contextvars

_current_span: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "_current_span", default=None
)


def set_current_span(span: Any) -> Any:
    """Set the current span context. Returns a token to restore later."""
    return _current_span.set(span)


def reset_current_span(token: Any) -> None:
    """Restore previous span context using a token from set_current_span."""
    _current_span.reset(token)


def get_current_span() -> Any:
    """Read the current span. Returns None if no span is active."""
    return _current_span.get()


@contextmanager
def span_retrieval(
    query: str,
    finding_index: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Open a child span for a RAG retrieval cycle.

    Nests under whatever span is currently active (typically the
    compliance agent's span). Use inside CodeRetriever.search().
    """
    parent = get_current_span()
    if parent is None:
        yield None
        return

    span = parent.span(
        name="rag.retrieve",
        input={"query": query[:300], "finding_index": finding_index},
        metadata=metadata or {},
    )
    try:
        yield span
    except Exception as e:
        span.update(level="ERROR", status_message=str(e)[:500])
        raise
    finally:
        span.end()


@contextmanager
def span_mcp_call(
    server: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Open a child span for an MCP tool call.

    Nests under whatever span is currently active (typically an agent span).
    Use inside MCPConnectionManager.call_tool().
    """
    parent = get_current_span()
    if parent is None:
        yield None
        return

    # Truncate large arguments to keep span payloads small
    safe_args = {}
    if arguments:
        for k, v in arguments.items():
            if isinstance(v, str) and len(v) > 500:
                safe_args[k] = v[:500] + f"... ({len(v)} chars total)"
            else:
                safe_args[k] = v

    span = parent.span(
        name=f"mcp.{server}.{tool}",
        input={"server": server, "tool": tool, "arguments": safe_args},
    )
    try:
        yield span
    except Exception as e:
        span.update(level="ERROR", status_message=str(e)[:500])
        raise
    finally:
        span.end()


@contextmanager
def observe_llm(
    name: str,
    model: str | None = None,
    messages: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Open a Langfuse generation span for an LLM call.

    Generation spans are special in Langfuse - they get cost/token tracking
    in the UI and roll up to per-model/per-run statistics.

    Use inside invoke_with_retry() to wrap LLM invocations.
    """
    parent = get_current_span()
    if parent is None:
        yield None
        return

    # Convert LangChain messages to a serializable form
    serialized_input = _serialize_messages(messages) if messages else None

    gen = parent.generation(
        name=name,
        model=model,
        input=serialized_input,
        metadata=metadata or {},
    )
    try:
        yield gen
    except Exception as e:
        gen.update(level="ERROR", status_message=str(e)[:500])
        raise
    finally:
        gen.end()


def _serialize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert LangChain messages to JSON-safe dicts for Langfuse."""
    out = []
    for m in messages:
        role = getattr(m, "type", "unknown")  # 'human', 'system', 'ai'
        content = getattr(m, "content", "")
        if isinstance(content, list):
            # Multimodal content (text + image blocks)
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "image_url":
                        text_parts.append("[image]")
                else:
                    text_parts.append(str(block)[:200])
            content = " ".join(text_parts)
        # Truncate long content to keep spans manageable
        if isinstance(content, str) and len(content) > 4000:
            content = content[:4000] + f"... ({len(content)} chars total)"
        out.append({"role": role, "content": content})
    return out