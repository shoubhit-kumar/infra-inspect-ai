"""Per-request correlation ID context.

The ContextVar carries the active request_id through async call chains,
making it available to any code in the request scope without explicit
plumbing.

Note: ContextVars are inherited by asyncio.create_task automatically,
but NOT by threads (incl. FastAPI BackgroundTasks). For background tasks
the request_id must be captured and re-set explicitly. See routes/inspections.py
for the pattern.
"""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Return the current request_id, or empty string if not set."""
    return request_id_var.get()


def set_request_id(rid: str) -> None:
    """Set the request_id for the current context."""
    request_id_var.set(rid)