"""Documentation Agent: produces a formatted inspection report."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.prompts.documentation import (
    DOCUMENTATION_SYSTEM_PROMPT,
    DOCUMENTATION_USER_PROMPT,
)
from src.schemas.documentation import (
    InspectionDocument,
    ReportAudience,
    ReportSection,
)
from src.schemas.enums import ComplianceStatus
from src.schemas.state import AgentState
from src.utils.structured_output import invoke_with_retry


class _LLMDocOutput(BaseModel):
    """The portion the LLM produces."""

    title: Annotated[str, Field(min_length=10, max_length=200)]
    executive_summary: Annotated[str, Field(min_length=50, max_length=2000)]
    headline_metrics: dict[str, int | str | float]
    sections: list[ReportSection]


class DocumentationAgent(BaseAgent[AgentState, InspectionDocument]):
    """Generates a Markdown inspection report and saves it to disk."""

    name = "documentation"

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,  # slightly higher: report writing is creative
        audience: ReportAudience = ReportAudience.OPERATIONAL,
        output_dir: Path = Path("data/outputs"),
    ) -> None:
        super().__init__(provider=provider, model=model, temperature=temperature)
        self.audience = audience
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, state: AgentState) -> InspectionDocument:
        """Produce a Markdown report and write to data/outputs/."""
        self.logger.info(
            "documentation.start",
            building=state.building_id,
            audience=self.audience.value,
        )

        prompt_data = self._collect_prompt_data(state)
        messages = [
            SystemMessage(content=DOCUMENTATION_SYSTEM_PROMPT),
            HumanMessage(
                content=DOCUMENTATION_USER_PROMPT.format(
                    building_id=state.building_id,
                    audience=self.audience.value,
                    compliance_status=state.compliance_status.value,
                    **prompt_data,
                )
            ),
        ]
        llm_output = invoke_with_retry(self.llm, _LLMDocOutput, messages)

        doc = InspectionDocument(
            building_id=state.building_id,
            title=llm_output.title,
            audience=self.audience,
            executive_summary=llm_output.executive_summary,
            overall_status=state.compliance_status,
            headline_metrics=llm_output.headline_metrics,
            sections=llm_output.sections,
            model_used=f"{self.provider}:{self.model or 'default'}",
        )

        doc.output_path = str(self._save_markdown(doc))
        self.logger.info(
            "documentation.done",
            path=doc.output_path,
            sections=len(doc.sections),
        )
        return doc

    # ------------------------------------------------------------------

    def _collect_prompt_data(self, state: AgentState) -> dict:
        """Format the various pieces of state for the prompt."""
        # Findings text
        findings_lines = []
        for r in state.inspection_reports:
            findings_lines.append(f"\nPhoto: {Path(r.photo_path).name}")
            for i, f in enumerate(r.findings):
                findings_lines.append(
                    f"  [{i}] {f.severity.value} | {f.category.value} | {f.issue}"
                )

        # Violations text
        violations_lines = []
        for v in state.compliance_violations:
            c = v["citation"]
            violations_lines.append(
                f"- {v['severity']} | {c['source']} {c['code']} - {c['title']}"
            )

        # Risk text
        risk_lines = []
        if state.risk_assessment:
            for iss in state.risk_assessment["issues"]:
                risk_lines.append(
                    f"- [{iss['priority']}] risk={iss['risk_score']:.1f}  "
                    f"{iss['title']}"
                )

        # Work orders text + cost total
        wo_lines = []
        total_cost = 0.0
        for wo in state.work_orders:
            total_cost += wo.get("estimated_cost_inr", 0)
            wo_lines.append(
                f"- [{wo['priority']}] Rs.{wo['estimated_cost_inr']:,.0f}  "
                f"{wo['assigned_team']}  | {wo['title']}  "
                f"| SLA: {wo['sla_deadline']}"
            )

        risk_count = len(state.risk_assessment["issues"]) if state.risk_assessment else 0

        return {
            "photo_count": len(state.inspection_reports),
            "total_findings": sum(len(r.findings) for r in state.inspection_reports),
            "violations_count": len(state.compliance_violations),
            "risk_issues_count": risk_count,
            "workorders_count": len(state.work_orders),
            "total_cost": total_cost,
            "findings_text": "\n".join(findings_lines) or "(none)",
            "violations_text": "\n".join(violations_lines) or "(none)",
            "risk_text": "\n".join(risk_lines) or "(none)",
            "workorders_text": "\n".join(wo_lines) or "(none)",
            "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),  # ← add this
        }

    def _save_markdown(self, doc: InspectionDocument) -> Path:
        """Render the document as Markdown and save."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"report_{doc.building_id}_{doc.audience.value}_{timestamp}.md"
        path = self.output_dir / filename

        lines: list[str] = []
        lines.append(f"# {doc.title}")
        lines.append("")
        lines.append(f"**Building:** {doc.building_id}  ")
        lines.append(f"**Audience:** {doc.audience.value}  ")
        lines.append(f"**Generated:** {doc.generated_at.isoformat()}  ")
        lines.append(f"**Status:** `{doc.overall_status.value.upper()}`  ")
        lines.append("")
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(doc.executive_summary)
        lines.append("")

        if doc.headline_metrics:
            lines.append("## Headline Metrics")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            for k, v in doc.headline_metrics.items():
                lines.append(f"| {k} | {v} |")
            lines.append("")

        for section in doc.sections:
            body = section.body_markdown.strip()
            # The LLM tends to repeat the heading inside body_markdown. Defensively
            # strip a leading "## <heading>" line so we don't render duplicates.
            heading_prefix = f"## {section.heading}"
            if body.startswith(heading_prefix):
                body = body[len(heading_prefix):].lstrip()
            lines.append(f"## {section.heading}")
            lines.append("")
            lines.append(body)
            lines.append("")

        # Build the full markdown string from the accumulated lines.
        content = "\n".join(lines)

        # Prefer MCP filesystem server if available; fall back to direct write.
        from src.mcp_clients.connections import get_mcp
        mcp = get_mcp()

        if mcp is not None:
            try:
                # filesystem MCP root is data/outputs, so we pass just the filename.
                mcp.call_tool(
                    "filesystem",
                    "write_file",
                    {"path": path.name, "content": content},
                )
                self.logger.info(
                    "documentation.written_via_mcp",
                    path=path.name,
                )
            except Exception as e:
                self.logger.warning(
                    "documentation.mcp_write_failed",
                    error=str(e),
                    fallback="direct write",
                )
                path.write_text(content, encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")

        return path