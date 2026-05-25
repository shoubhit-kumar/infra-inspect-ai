"""Schemas for follow-up actions: notifications and scheduled re-inspections."""
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

from src.schemas.enums import Priority


class NotificationChannel(str, Enum):
    """Where a notification goes."""
    EMAIL = "email"
    SLACK = "slack"
    SMS = "sms"
    IN_APP = "in_app"


class NotificationAudience(str, Enum):
    """Who receives the notification."""
    ASSIGNED_TEAM = "assigned_team"
    BUILDING_MANAGER = "building_manager"
    COMPLIANCE_OFFICER = "compliance_officer"
    EXECUTIVE = "executive"
    INSPECTOR = "inspector"


class Notification(BaseModel):
    """A single notification payload, channel-agnostic."""

    audience: NotificationAudience
    channel: NotificationChannel
    subject: Annotated[str, Field(min_length=5, max_length=200)]
    body: Annotated[str, Field(min_length=20, max_length=2000)]
    related_work_order_ids: list[str] = Field(default_factory=list)
    """Work orders this notification relates to (by their issue_id)."""

    urgent: bool = False


class ScheduledTask(BaseModel):
    """A future action to be triggered later (e.g. re-inspection)."""

    task_type: Annotated[str, Field(min_length=3, max_length=50)]
    """e.g. 're_inspection', 'compliance_audit', 'work_order_followup'."""

    description: Annotated[str, Field(min_length=10, max_length=500)]
    scheduled_for: datetime
    related_issue_id: str | None = None
    related_work_order_id: str | None = None
    priority: Priority | None = None


class FollowUpPlan(BaseModel):
    """The full follow-up output: notifications to send + tasks to schedule."""

    notifications: list[Notification] = Field(default_factory=list)
    scheduled_tasks: list[ScheduledTask] = Field(default_factory=list)
    summary: Annotated[str, Field(min_length=20, max_length=1000)]
    model_used: str