"""Work Order Agent: converts risked issues into actionable work orders."""
from datetime import datetime, timezone
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.prompts.workorder import WORKORDER_SYSTEM_PROMPT, WORKORDER_USER_PROMPT
from src.schemas.risk import RiskAssessment
from src.schemas.workorder import WorkOrder
from src.utils.structured_output import invoke_with_retry


class _LLMWorkOrderOutput(BaseModel):
    """The portion the LLM produces."""
    work_orders: list[WorkOrder] = Field(default_factory=list)
    summary: Annotated[str, Field(min_length=10, max_length=1000)]


class WorkOrderResult(BaseModel):
    work_orders: list[WorkOrder]
    summary: str
    model_used: str


class WorkOrderAgent(BaseAgent[RiskAssessment, WorkOrderResult]):
    """Converts a RiskAssessment into a list of WorkOrders."""

    name = "workorder"

    def run(self, assessment: RiskAssessment) -> WorkOrderResult:
        """Produce one work order per risked issue."""
        self.logger.info("workorder.start", issues_count=len(assessment.issues))

        if not assessment.issues:
            self.logger.info("workorder.skip", reason="no_issues")
            return WorkOrderResult(
                work_orders=[],
                summary="No issues to act on.",
                model_used=f"{self.provider}:{self.model or 'default'}",
            )

        issues_text = self._format_issues(assessment)

        messages = [
            SystemMessage(content=WORKORDER_SYSTEM_PROMPT),
            HumanMessage(
                content=WORKORDER_USER_PROMPT.format(
                    now_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    issues_text=issues_text,
                )
            ),
        ]
        llm_output = invoke_with_retry(self.llm, _LLMWorkOrderOutput, messages)

        # Defensive: ensure 1:1 mapping between issues and work orders.
        # If LLM dropped one, log it; do not crash.
        issue_ids = {iss.issue_id for iss in assessment.issues}
        wo_ids = {wo.issue_id for wo in llm_output.work_orders}
        missing = issue_ids - wo_ids
        extra = wo_ids - issue_ids
        if missing:
            self.logger.warning("workorder.missing_issues", issue_ids=list(missing))
        if extra:
            self.logger.warning("workorder.unknown_issues", issue_ids=list(extra))

        return WorkOrderResult(
            work_orders=llm_output.work_orders,
            summary=llm_output.summary,
            model_used=f"{self.provider}:{self.model or 'default'}",
        )

    @staticmethod
    def _format_issues(assessment: RiskAssessment) -> str:
        lines = []
        for iss in assessment.issues:
            lines.append(
                f"issue_id: {iss.issue_id}\n"
                f"  title: {iss.title}\n"
                f"  category: {iss.category.value}\n"
                f"  severity: {iss.severity.value}\n"
                f"  priority: {iss.priority.value}\n"
                f"  risk_score: {iss.risk_score}\n"
                f"  description: {iss.description[:300]}"
            )
        return "\n\n".join(lines)