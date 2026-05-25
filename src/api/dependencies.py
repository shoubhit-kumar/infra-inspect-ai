"""Shared resources used by API endpoints.

The MCP manager and workflow are heavy to construct, so we build them once
on app startup and share across requests. The job registry tracks async work.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.api.schemas.api_models import InspectionSummary, JobStatus


@dataclass
class JobRecord:
    """In-memory state for one async workflow job.

    For a single-worker uvicorn this is fine. For a multi-worker deployment
    we'd promote this to Redis or a database table. Day 22 deployment note.
    """
    job_id: str
    status: JobStatus = JobStatus.queued
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: InspectionSummary | None = None
    error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class JobRegistry:
    """Thread-safe registry of async jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(self) -> JobRecord:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        record = JobRecord(job_id=job_id)
        with self._lock:
            self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs: Any) -> None:
        record = self.get(job_id)
        if record is None:
            return
        with record._lock:
            for k, v in kwargs.items():
                setattr(record, k, v)


# ----------------------------------------------------------------------------
# Module-level singletons - constructed once on app startup
# ----------------------------------------------------------------------------

_job_registry: JobRegistry | None = None


def get_job_registry() -> JobRegistry:
    """Dependency: get the job registry (created lazily)."""
    global _job_registry
    if _job_registry is None:
        _job_registry = JobRegistry()
    return _job_registry