"""Follow-up Agent: generates notifications and schedules future tasks."""
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.base import BaseAgent
from src.prompts.followup import FOLLOWUP_SYSTEM_PROMPT, FOLLOWUP_USER_PROMPT
from src.schemas.followup import FollowUpPlan
from src.schemas.state import AgentState
from src.utils.structured_output import invoke_with_retry


class FollowUpAgent(BaseAgent[AgentState, FollowUpPlan]):
    """Produces notifications and scheduled re-inspection tasks."""

    name = "followup"

    def run(self, state: AgentState) -> FollowUpPlan:
        self.logger.info(
            "followup.start",
            building=state.building_id,
            work_orders=len(state.work_orders),
        )

        if not state.work_orders:
            self.logger.info("followup.skip", reason="no_work_orders")
            return FollowUpPlan(
                summary="No work orders to follow up on.",
                model_used=f"{self.provider}:{self.model or 'default'}",
            )

        has_critical = any(
            v.get("severity") == "critical"
            for v in state.compliance_violations
        )

        messages = [
            SystemMessage(content=FOLLOWUP_SYSTEM_PROMPT),
            HumanMessage(
                content=FOLLOWUP_USER_PROMPT.format(
                    building_id=state.building_id,
                    now_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    has_critical_violations=str(has_critical).lower(),
                    workorders_text=self._format_workorders(state),
                )
            ),
        ]
        plan = invoke_with_retry(self.llm, FollowUpPlan, messages)
        plan.model_used = f"{self.provider}:{self.model or 'default'}"

        # Side effect: dispatch notifications via MCP if available, else console.
        self._dispatch_notifications(plan, building_id=state.building_id)

        self.logger.info(
            "followup.done",
            notifications=len(plan.notifications),
            scheduled_tasks=len(plan.scheduled_tasks),
        )
        return plan

    @staticmethod
    def _format_workorders(state: AgentState) -> str:
        lines = []
        for wo in state.work_orders:
            lines.append(
                f"- issue_id: {wo['issue_id']}\n"
                f"  title: {wo['title']}\n"
                f"  priority: {wo['priority']}\n"
                f"  assigned_team: {wo['assigned_team']}\n"
                f"  cost_inr: {wo['estimated_cost_inr']}\n"
                f"  sla_deadline: {wo['sla_deadline']}\n"
                f"  requires_approval: {wo.get('requires_approval', False)}"
            )
        return "\n\n".join(lines)

    def _dispatch_notifications(
        self,
        plan: FollowUpPlan,
        building_id: str | None = None,
    ) -> None:
        """Dispatch each notification via MCP (preferred) or fall back to console log.

        Day 14: notifications now flow through the notification MCP server,
        which persists them to SQLite and routes per channel. If the MCP
        manager isn't available, we log to console as we did in Week 2.
        """
        from src.mcp_clients.connections import get_mcp

        mcp = get_mcp()

        for n in plan.notifications:
            urgency = "URGENT" if n.urgent else "normal"

            if mcp is not None:
                try:
                    mcp.call_tool(
                        "notification",
                        "send_notification",
                        {
                            "channel": n.channel.value,
                            "audience": n.audience.value,
                            "subject": n.subject,
                            "body": n.body,
                            "urgency": urgency,
                            **({"building_id": building_id} if building_id else {}),
                        },
                    )
                    self.logger.info(
                        "notification.dispatched_via_mcp",
                        channel=n.channel.value,
                        urgency=urgency,
                        subject=n.subject[:80],
                    )
                    continue
                except Exception as e:
                    self.logger.warning(
                        "notification.mcp_dispatch_failed",
                        error=str(e),
                        channel=n.channel.value,
                        fallback="console log",
                    )

            # Fallback: console log
            self.logger.info(
                "notification.dispatched",
                channel=n.channel.value,
                audience=n.audience.value,
                urgency=urgency,
                subject=n.subject[:80],
            )