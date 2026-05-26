"""Module-level singleton for the SQLAlchemy engine and session factory.

Production pattern: one engine per process, sessions scoped per request.
Repository instances reuse this shared factory instead of each constructing
a new engine + connection pool on every instantiation.

Tests can still create isolated repositories by passing a different
db_path - see AssetRepository.__init__.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.memory.store import init_db, make_engine, make_session_factory
from src.utils.logging import get_logger

logger = get_logger(__name__)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_session_factory(db_path: Path | None = None) -> sessionmaker[Session]:
    """Return the process-wide session factory, creating it on first call.

    The engine and tables are initialised exactly once per process.
    Subsequent calls return the cached factory.

    db_path is honoured only on the first call. After that, all callers
    share the same engine regardless of what path they pass. This matches
    the singleton semantics: the second caller doesn't get to relocate
    the database from under the first caller.

    For tests that need an isolated database, pass db_path directly to
    AssetRepository and bypass the singleton.
    """
    global _engine, _session_factory
    if _session_factory is None:
        path = db_path  # falls through to make_engine's default if None
        _engine = make_engine(path) if path else make_engine()
        init_db(_engine)
        _session_factory = make_session_factory(_engine)
        logger.info("memory.shared_engine_initialized")
    return _session_factory


def reset_session_factory() -> None:
    """Reset the singleton. Test-only - production code should never call this.

    Useful when tests need to swap in a different engine partway through.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None