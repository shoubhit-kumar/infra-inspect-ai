"""Risk Agent: deduplicates findings/violations across photos and assigns priorities."""
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.base import BaseAgent
from src.prompts.risk import RISK_SYSTEM_PROMPT, RISK_USER_PROMPT
from src.schemas.risk import RiskAssessment
from src.schemas.state import AgentState
from src.utils.structured_output import invoke_with_retry


class RiskAgent(BaseAgent[AgentState, RiskAssessment]):
    """Aggregates findings and violations into a deduplicated risk register."""

    name = "risk"

    def run(self, state: AgentState) -> RiskAssessment:
        """Process the full state and produce a RiskAssessment.

        Uses asset_memory and finding_classifications from state if present.
        """
        self.logger.info(
            "risk.start",
            building_id=state.building_id,
            photos=len(state.inspection_reports),
            violations=len(state.compliance_violations),
        )

        findings_text = self._format_findings(state)
        violations_text = self._format_violations(state)

        history_text = self._format_history(state)

        messages = [
            SystemMessage(content=RISK_SYSTEM_PROMPT),
            HumanMessage(
                content=RISK_USER_PROMPT.format(
                    building_id=state.building_id,
                    photo_count=len(state.inspection_reports),
                    findings_text=findings_text or "(none)",
                    violations_text=violations_text or "(none)",
                    history_text=history_text or "(none)",
                )
            ),
        ]
        assessment = invoke_with_retry(self.llm, RiskAssessment, messages)

        # System-controlled metadata
        assessment.model_used = f"{self.provider}:{self.model or 'default'}"

        # Defensive: ensure risk_score = impact * probability for every issue.
        # LLMs sometimes do the math wrong. Recompute and warn on drift.
        for issue in assessment.issues:
            expected = round(issue.impact_score * issue.probability_score, 2)
            if abs(issue.risk_score - expected) > 0.5:
                self.logger.warning(
                    "risk.score_drift",
                    issue_id=issue.issue_id,
                    llm_score=issue.risk_score,
                    recomputed=expected,
                )
                issue.risk_score = expected

        self.logger.info(
            "risk.done",
            issues_count=len(assessment.issues),
            top_category=(
                assessment.highest_risk_category.value
                if assessment.highest_risk_category else None
            ),
        )
        return assessment

    @staticmethod
    def _format_findings(state: AgentState) -> str:
        lines = []
        for report in state.inspection_reports:
            photo_name = Path(report.photo_path).name
            for i, f in enumerate(report.findings):
                lines.append(
                    f"[{photo_name} #{i}] sev={f.severity.value} cat={f.category.value}\n"
                    f"    issue: {f.issue}\n"
                    f"    evidence: {f.visual_evidence[:200]}"
                )
        return "\n\n".join(lines)

    @staticmethod
    def _format_violations(state: AgentState) -> str:
        lines = []
        for v in state.compliance_violations:
            citation = v["citation"]
            lines.append(
                f"- {citation['source']} {citation['code']} | sev={v['severity']}\n"
                f"  title: {citation['title']}\n"
                f"  issue: {v['violation_description'][:200]}"
            )
        return "\n".join(lines)
    
    @staticmethod
    def _format_history(state: AgentState) -> str:
        """Format asset memory + classifications for the prompt."""
        lines: list[str] = []

        if state.asset_memory:
            summary = state.asset_memory.get("summary", {})
            total = summary.get("total_inspections", 0)
            if total > 0:
                lines.append(f"Building has been inspected {total} time(s) before.")

            open_wos = state.asset_memory.get("open_work_orders", [])
            if open_wos:
                lines.append("Currently-open work orders from prior inspections:")
                for wo in open_wos:
                    lines.append(
                        f"  - issue_id={wo['issue_id']}  priority={wo['priority']}  "
                        f"title={wo['title'][:80]}"
                    )

        if state.finding_classifications:
            persist = [c for c in state.finding_classifications if c["status"] == "persisting"]
            worsen = [c for c in state.finding_classifications if c["status"] == "worsening"]
            improve = [c for c in state.finding_classifications if c["status"] == "improving"]
            new = [c for c in state.finding_classifications if c["status"] == "new"]
            lines.append(
                f"Finding classifications: "
                f"new={len(new)}, persisting={len(persist)}, "
                f"worsening={len(worsen)}, improving={len(improve)}"
            )
            for c in worsen:
                lines.append(
                    f"  WORSENING: '{c['new_issue'][:60]}' "
                    f"(was {c['old_severity']}, now {c['new_severity']})"
                )

        return "\n".join(lines)