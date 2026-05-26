"""Repository for asset memory.

This is the only file that should construct SQL queries. Agents and
workflows interact with memory via these methods, not via raw SQLAlchemy.
This isolation lets us swap storage engines later without touching agents.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.memory.connection import get_session_factory
from src.memory.store import (
    Asset,
    FindingRecord,
    InspectionRun,
    NotificationRecord,
    WorkOrderRecord,
    init_db,
    make_engine,
    make_session_factory,
)
from src.schemas.memory import (
    AssetMemory,
    AssetSummary,
    HistoricalFinding,
    HistoricalWorkOrder,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


# How many recent findings to include in the memory snapshot returned to agents.
RECENT_FINDINGS_LIMIT = 20
# How many recently-closed work orders to include.
RECENT_CLOSED_LIMIT = 10


class AssetRepository:
    """Read and write asset memory.

    Single-process use. For multi-process / API server use, instantiate
    per-request with a request-scoped session.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        """Build a repository.

        Resolution order:
          1. If session_factory is provided, use it directly. This is how
             tests inject in-memory engines, and how the FastAPI lifespan
             could provide a request-scoped factory in the future.
          2. Else if db_path is provided, build a dedicated engine for it.
             Used by tests that want a fresh on-disk DB.
          3. Otherwise, use the process-wide singleton (the production path).
        """
        if session_factory is not None:
            self.SessionLocal = session_factory
            self.engine = None  # not owned by this instance
        elif db_path is not None:
            self.engine = make_engine(db_path)
            init_db(self.engine)
            self.SessionLocal = make_session_factory(self.engine)
        else:
            self.engine = None  # owned by the singleton
            self.SessionLocal = get_session_factory()

    # ---------- Writes ----------

    def ensure_asset(
        self,
        building_id: str,
        display_name: str | None = None,
        location: str | None = None,
    ) -> None:
        """Create the asset row if absent. Idempotent."""
        with self.SessionLocal() as s:
            existing = s.get(Asset, building_id)
            if existing:
                return
            s.add(
                Asset(
                    building_id=building_id,
                    display_name=display_name,
                    location=location,
                )
            )
            s.commit()
            logger.info("memory.asset_created", building_id=building_id)

    def record_inspection_run(
        self,
        building_id: str,
        inspector_notes: str | None,
        photo_count: int,
        finding_count: int,
        violation_count: int,
        compliance_status: str | None,
        findings: list[dict[str, Any]],
        work_orders: list[dict[str, Any]],
    ) -> int:
        """Persist a complete inspection run with findings and work orders.

        Returns the integer run_id for downstream references.
        """
        self.ensure_asset(building_id=building_id)

        with self.SessionLocal() as s:
            run = InspectionRun(
                building_id=building_id,
                inspector_notes=inspector_notes,
                photo_count=photo_count,
                finding_count=finding_count,
                violation_count=violation_count,
                compliance_status=compliance_status,
            )
            s.add(run)
            s.flush()  # so we have run.id without committing yet

            for f in findings:
                s.add(
                    FindingRecord(
                        run_id=run.id,
                        photo_filename=f.get("photo_filename"),
                        issue=f["issue"],
                        severity=f["severity"],
                        category=f["category"],
                        location_hint=f.get("location_hint"),
                        visual_evidence=f.get("visual_evidence"),
                        confidence=f.get("confidence"),
                    )
                )

            for wo in work_orders:
                s.add(
                    WorkOrderRecord(
                        run_id=run.id,
                        issue_id=wo["issue_id"],
                        title=wo["title"],
                        description=wo.get("description"),
                        category=wo["category"],
                        priority=wo["priority"],
                        assigned_team=wo["assigned_team"],
                        estimated_cost_inr=float(wo["estimated_cost_inr"]),
                        estimated_hours=float(wo["estimated_hours"]),
                        sla_deadline=_parse_dt(wo["sla_deadline"]),
                        requires_approval=bool(wo.get("requires_approval", False)),
                        status="open",
                    )
                )

            s.commit()
            run_id = run.id
            logger.info(
                "memory.run_recorded",
                run_id=run_id,
                building_id=building_id,
                findings=len(findings),
                work_orders=len(work_orders),
            )
            return run_id

    def update_work_order_status(
        self,
        work_order_internal_id: int,
        status: str,
    ) -> None:
        """Transition a work order to a new status.

        Valid transitions:
            open -> in_progress -> closed -> verified
            anything -> cancelled
        """
        with self.SessionLocal() as s:
            wo = s.get(WorkOrderRecord, work_order_internal_id)
            if not wo:
                raise ValueError(f"Work order {work_order_internal_id} not found")
            wo.status = status
            if status in {"closed", "verified", "cancelled"} and wo.closed_at is None:
                wo.closed_at = datetime.now(timezone.utc)
            s.commit()
            logger.info(
                "memory.work_order_updated",
                id=work_order_internal_id,
                status=status,
            )

    # ---------- Reads ----------

    def get_asset_memory(self, building_id: str) -> AssetMemory:
        """Snapshot a building's memory. Returns empty for unknown buildings."""
        with self.SessionLocal() as s:
            asset = s.get(Asset, building_id)
            if asset is None:
                logger.info("memory.unknown_asset", building_id=building_id)
                return AssetMemory(
                    summary=AssetSummary(building_id=building_id),
                )

            summary = self._build_summary(s, building_id)
            recent_findings = self._recent_findings(s, building_id)
            open_wos = self._open_work_orders(s, building_id)
            closed_wos = self._recent_closed_work_orders(s, building_id)

            return AssetMemory(
                summary=summary,
                recent_findings=recent_findings,
                open_work_orders=open_wos,
                recently_closed_work_orders=closed_wos,
            )

    def list_assets(self) -> list[Asset]:
        """List all known buildings."""
        with self.SessionLocal() as s:
            return list(s.scalars(select(Asset)).all())
        
    def get_work_order_by_id(self, work_order_id: int) -> dict[str, Any] | None:
        """Fetch a single work order as a dict, or None if not found."""
        with self.SessionLocal() as s:
            wo = s.get(WorkOrderRecord, work_order_id)
            if wo is None:
                return None
            return _work_order_to_dict(wo)

    def list_work_orders_for_building(
        self,
        building_id: str,
        status_filter: str | None = None,
        priority_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """List work orders for a building with optional filters."""
        with self.SessionLocal() as s:
            stmt = (
                select(WorkOrderRecord)
                .join(InspectionRun, WorkOrderRecord.run_id == InspectionRun.id)
                .where(InspectionRun.building_id == building_id)
            )
            if status_filter:
                stmt = stmt.where(WorkOrderRecord.status == status_filter)
            if priority_filter:
                stmt = stmt.where(WorkOrderRecord.priority == priority_filter)
            stmt = stmt.order_by(WorkOrderRecord.created_at.desc())
            rows = s.scalars(stmt).all()
            return [_work_order_to_dict(wo) for wo in rows]

    def create_standalone_work_order(
        self,
        building_id: str,
        wo: dict[str, Any],
    ) -> int:
        """Create a work order outside of a full inspection run.

        Used by the MCP server when an external tool wants to add a WO.
        Creates a synthetic InspectionRun-of-one to maintain referential
        integrity, since work orders belong to runs.
        """
        self.ensure_asset(building_id=building_id)

        with self.SessionLocal() as s:
            run = InspectionRun(
                building_id=building_id,
                inspector_notes="(standalone work order via MCP)",
                photo_count=0,
                finding_count=0,
                violation_count=0,
                compliance_status=None,
            )
            s.add(run)
            s.flush()

            record = WorkOrderRecord(
                run_id=run.id,
                issue_id=wo["issue_id"],
                title=wo["title"],
                description=wo.get("description"),
                category=wo["category"],
                priority=wo["priority"],
                assigned_team=wo["assigned_team"],
                estimated_cost_inr=float(wo["estimated_cost_inr"]),
                estimated_hours=float(wo["estimated_hours"]),
                sla_deadline=_parse_dt(wo["sla_deadline"]),
                requires_approval=bool(wo.get("requires_approval", False)),
                status="open",
            )
            s.add(record)
            s.commit()
            logger.info(
                "memory.standalone_wo_created",
                id=record.id,
                building_id=building_id,
                issue_id=record.issue_id,
            )
            return record.id

    def reassign_work_order(self, work_order_id: int, team: str) -> None:
        """Change the assigned team for a work order."""
        with self.SessionLocal() as s:
            wo = s.get(WorkOrderRecord, work_order_id)
            if not wo:
                raise ValueError(f"Work order {work_order_id} not found")
            wo.assigned_team = team
            s.commit()
            logger.info("memory.work_order_reassigned", id=work_order_id, team=team)

    # ---------- Internal helpers ----------

    def _build_summary(self, s: Session, building_id: str) -> AssetSummary:
        """Aggregate row-level data into a one-row summary."""
        run_stats = s.execute(
            select(
                func.min(InspectionRun.started_at),
                func.max(InspectionRun.started_at),
                func.count(InspectionRun.id),
            ).where(InspectionRun.building_id == building_id)
        ).one()

        first_at, last_at, total_runs = run_stats

        wo_stats = s.execute(
            select(
                func.count(WorkOrderRecord.id).filter(WorkOrderRecord.status == "open"),
                func.count(WorkOrderRecord.id).filter(
                    WorkOrderRecord.status.in_(["closed", "verified"])
                ),
            )
            .join(InspectionRun, WorkOrderRecord.run_id == InspectionRun.id)
            .where(InspectionRun.building_id == building_id)
        ).one()

        open_count, closed_count = wo_stats

        # Longest-open issue age in days.
        oldest_open = s.execute(
            select(WorkOrderRecord.created_at)
            .join(InspectionRun, WorkOrderRecord.run_id == InspectionRun.id)
            .where(
                InspectionRun.building_id == building_id,
                WorkOrderRecord.status == "open",
            )
            .order_by(WorkOrderRecord.created_at.asc())
            .limit(1)
        ).scalar()

        longest_open_days = 0
        if oldest_open:
            # Normalise to aware UTC for the subtraction.
            now = datetime.now(timezone.utc)
            oldest_aware = (
                oldest_open if oldest_open.tzinfo else oldest_open.replace(tzinfo=timezone.utc)
            )
            longest_open_days = max(0, (now - oldest_aware).days)

        return AssetSummary(
            building_id=building_id,
            first_inspection_at=first_at,
            last_inspection_at=last_at,
            total_inspections=int(total_runs or 0),
            open_work_orders=int(open_count or 0),
            closed_work_orders=int(closed_count or 0),
            longest_open_issue_days=longest_open_days,
        )

    def _recent_findings(self, s: Session, building_id: str) -> list[HistoricalFinding]:
        rows = s.execute(
            select(FindingRecord, InspectionRun.started_at)
            .join(InspectionRun, FindingRecord.run_id == InspectionRun.id)
            .where(InspectionRun.building_id == building_id)
            .order_by(desc(InspectionRun.started_at), desc(FindingRecord.id))
            .limit(RECENT_FINDINGS_LIMIT)
        ).all()

        out: list[HistoricalFinding] = []
        for f, ts in rows:
            out.append(
                HistoricalFinding(
                    inspection_run_id=f.run_id,
                    inspected_at=ts,
                    photo_filename=f.photo_filename,
                    issue=f.issue,
                    severity=f.severity,
                    category=f.category,
                    location_hint=f.location_hint,
                    visual_evidence=f.visual_evidence,
                )
            )
        return out

    def _open_work_orders(self, s: Session, building_id: str) -> list[HistoricalWorkOrder]:
        rows = s.execute(
            select(WorkOrderRecord)
            .join(InspectionRun, WorkOrderRecord.run_id == InspectionRun.id)
            .where(
                InspectionRun.building_id == building_id,
                WorkOrderRecord.status == "open",
            )
            .order_by(WorkOrderRecord.created_at.asc())
        ).scalars().all()
        return [_to_historical_wo(wo) for wo in rows]

    def _recent_closed_work_orders(
        self,
        s: Session,
        building_id: str,
    ) -> list[HistoricalWorkOrder]:
        rows = s.execute(
            select(WorkOrderRecord)
            .join(InspectionRun, WorkOrderRecord.run_id == InspectionRun.id)
            .where(
                InspectionRun.building_id == building_id,
                WorkOrderRecord.status.in_(["closed", "verified"]),
            )
            .order_by(desc(WorkOrderRecord.closed_at))
            .limit(RECENT_CLOSED_LIMIT)
        ).scalars().all()
        return [_to_historical_wo(wo) for wo in rows]
    
    def record_notification(
        self,
        channel: str,
        audience: str,
        subject: str,
        body: str,
        urgency: str = "normal",
        building_id: str | None = None,
        work_order_id: int | None = None,
        delivery_status: str = "sent",
    ) -> int:
        """Persist one dispatched notification. Returns the new row id."""
        with self.SessionLocal() as s:
            rec = NotificationRecord(
                building_id=building_id,
                work_order_id=work_order_id,
                channel=channel,
                audience=audience,
                subject=subject[:300],
                body=body,
                urgency=urgency,
                delivery_status=delivery_status,
            )
            s.add(rec)
            s.commit()
            logger.info(
                "memory.notification_recorded",
                id=rec.id,
                channel=channel,
                urgency=urgency,
                building_id=building_id,
            )
            return rec.id

    def list_notifications(
        self,
        building_id: str | None = None,
        since: datetime | None = None,
        channel: str | None = None,
        urgency: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query notifications with optional filters."""
        with self.SessionLocal() as s:
            stmt = select(NotificationRecord)
            if building_id:
                stmt = stmt.where(NotificationRecord.building_id == building_id)
            if since:
                stmt = stmt.where(NotificationRecord.dispatched_at >= since)
            if channel:
                stmt = stmt.where(NotificationRecord.channel == channel)
            if urgency:
                stmt = stmt.where(NotificationRecord.urgency == urgency)
            stmt = stmt.order_by(NotificationRecord.dispatched_at.desc()).limit(limit)
            rows = s.scalars(stmt).all()
            return [_notification_to_dict(n) for n in rows]

    def notification_stats(self) -> dict[str, Any]:
        """Aggregate counts by channel and urgency, across all buildings."""
        with self.SessionLocal() as s:
            total = s.execute(
                select(func.count(NotificationRecord.id))
            ).scalar() or 0

            by_channel_rows = s.execute(
                select(NotificationRecord.channel, func.count(NotificationRecord.id))
                .group_by(NotificationRecord.channel)
            ).all()
            by_channel = {ch: int(n) for ch, n in by_channel_rows}

            by_urgency_rows = s.execute(
                select(NotificationRecord.urgency, func.count(NotificationRecord.id))
                .group_by(NotificationRecord.urgency)
            ).all()
            by_urgency = {u: int(n) for u, n in by_urgency_rows}

            return {
                "total_notifications": total,
                "by_channel": by_channel,
                "by_urgency": by_urgency,
            }


# ---------- Free functions ----------

def _parse_dt(value: Any) -> datetime:
    """Accept ISO string or datetime, return aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise TypeError(f"Unsupported datetime input: {type(value)}")


def _to_historical_wo(wo: WorkOrderRecord) -> HistoricalWorkOrder:
    return HistoricalWorkOrder(
        work_order_internal_id=wo.id,
        issue_id=wo.issue_id,
        title=wo.title,
        priority=wo.priority,
        status=wo.status,
        created_at=wo.created_at,
        closed_at=wo.closed_at,
        estimated_cost_inr=wo.estimated_cost_inr,
    )

def _work_order_to_dict(wo: WorkOrderRecord) -> dict[str, Any]:
    """Full work order dict for MCP responses."""
    return {
        "id": wo.id,
        "run_id": wo.run_id,
        "issue_id": wo.issue_id,
        "title": wo.title,
        "description": wo.description,
        "category": wo.category,
        "priority": wo.priority,
        "assigned_team": wo.assigned_team,
        "status": wo.status,
        "estimated_cost_inr": wo.estimated_cost_inr,
        "estimated_hours": wo.estimated_hours,
        "sla_deadline": wo.sla_deadline.isoformat() if wo.sla_deadline else None,
        "created_at": wo.created_at.isoformat() if wo.created_at else None,
        "closed_at": wo.closed_at.isoformat() if wo.closed_at else None,
        "requires_approval": wo.requires_approval,
    }

def _notification_to_dict(n: NotificationRecord) -> dict[str, Any]:
    """Notification dict for MCP responses."""
    return {
        "id": n.id,
        "building_id": n.building_id,
        "work_order_id": n.work_order_id,
        "channel": n.channel,
        "audience": n.audience,
        "subject": n.subject,
        "body": n.body,
        "urgency": n.urgency,
        "dispatched_at": n.dispatched_at.isoformat() if n.dispatched_at else None,
        "delivery_status": n.delivery_status,
    }