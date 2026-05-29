"""SQLAlchemy ORM models for asset memory."""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from src.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_DB_PATH = Path("data/memory/asset_memory.sqlite")


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Asset(Base):
    """A building or other inspectable asset."""

    __tablename__ = "assets"

    building_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    asset_type: Mapped[str] = mapped_column(String(50), default="building")
    """E.g. 'building', 'data_center', 'warehouse'."""
    location: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    inspections: Mapped[list["InspectionRun"]] = relationship(back_populates="asset")


class InspectionRun(Base):
    """One inspection event - corresponds to one full workflow run."""

    __tablename__ = "inspection_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    building_id: Mapped[str] = mapped_column(ForeignKey("assets.building_id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    inspector_notes: Mapped[str | None] = mapped_column(Text)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    violation_count: Mapped[int] = mapped_column(Integer, default=0)
    compliance_status: Mapped[str | None] = mapped_column(String(30))
    """E.g. 'compliant', 'non_compliant', 'partial'."""

    request_id: Mapped[str | None] = mapped_column(String(50))
    """Correlation ID from the originating HTTP request. NULL for CLI/script runs.
    
    Indexed-via-default for direct SQL lookup: 
        SELECT * FROM inspection_runs WHERE request_id = 'req_abc123'
    """

    asset: Mapped[Asset] = relationship(back_populates="inspections")
    findings: Mapped[list["FindingRecord"]] = relationship(back_populates="run")
    work_orders: Mapped[list["WorkOrderRecord"]] = relationship(back_populates="run")


class FindingRecord(Base):
    """A finding recorded against an inspection run.

    Denormalized for easy querying. The full structured finding can be
    reconstructed from these fields plus the JSON column for less-used data.
    """

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("inspection_runs.id"))
    photo_filename: Mapped[str | None] = mapped_column(String(200))
    issue: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(30))
    location_hint: Mapped[str | None] = mapped_column(String(400))
    visual_evidence: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)

    run: Mapped[InspectionRun] = relationship(back_populates="findings")


class WorkOrderRecord(Base):
    """A work order recorded against an inspection run.

    Mirrors WorkOrder from the agent pipeline. Status is mutable - this is
    the only table where we update rows after creation (the rest is append-only).
    """

    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("inspection_runs.id"))
    issue_id: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(10))
    assigned_team: Mapped[str] = mapped_column(String(50))
    estimated_cost_inr: Mapped[float] = mapped_column(Float)
    estimated_hours: Mapped[float] = mapped_column(Float)
    sla_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="open")
    """open | in_progress | closed | verified | cancelled."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requires_approval: Mapped[bool] = mapped_column(default=False)

    run: Mapped[InspectionRun] = relationship(back_populates="work_orders")

class NotificationRecord(Base):
    """A notification dispatched by the notification MCP server.

    Append-only log. No status field - notifications are facts about
    things we sent, not stateful entities.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    building_id: Mapped[str | None] = mapped_column(String(50))
    """Optional - some notifications aren't tied to a building."""
    work_order_id: Mapped[int | None] = mapped_column(Integer)
    """Optional - some notifications aren't tied to a work order."""
    channel: Mapped[str] = mapped_column(String(20))
    """slack | email | in_app | sms"""
    audience: Mapped[str] = mapped_column(String(50))
    """assigned_team | building_manager | executive | external_inspector | ..."""
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    urgency: Mapped[str] = mapped_column(String(20), default="normal")
    """normal | high | URGENT"""
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )
    delivery_status: Mapped[str] = mapped_column(String(20), default="sent")
    """sent | failed | queued.
    In production this would update asynchronously when delivery confirms."""


# ---------- Engine setup ----------

def make_engine(db_path: Path = DEFAULT_DB_PATH, echo: bool = False):
    """Create a SQLAlchemy engine pointing at a SQLite file.

    Args:
        db_path: Where to put (or find) the SQLite file.
        echo: If True, SQLAlchemy logs all SQL statements. Useful for debug.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=echo,
        # Recommended for multi-threaded use; cheap on single-threaded too.
        connect_args={"check_same_thread": False},
    )
    logger.info("memory.engine_ready", path=str(db_path))
    return engine


def init_db(engine) -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(engine)
    logger.info("memory.tables_created")


def make_session_factory(engine):
    """Return a sessionmaker bound to the engine."""
    return sessionmaker(bind=engine, expire_on_commit=False)