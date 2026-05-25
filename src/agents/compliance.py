"""Compliance Agent (grounded with RAG).

Pipeline per inspection report:
  For each finding:
    1. Build a retrieval query (issue + category + key evidence terms)
    2. Run CodeRetriever to get top-K reranked chunks
    3. Filter chunks below MIN_RETRIEVAL_SCORE
  Then:
    4. Pass findings + their retrieved excerpts to LLM
    5. LLM produces violations grounded in those excerpts
    6. Post-process: attach retrieval_score and source_excerpts to each violation
"""
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.prompts.compliance import (
    COMPLIANCE_SYSTEM_PROMPT,
    COMPLIANCE_USER_PROMPT,
)
from src.rag.retriever import CodeRetriever, RetrievalResult
from src.schemas.compliance import ComplianceViolation
from src.schemas.inspection import InspectionFinding, InspectionReport
from src.utils.structured_output import invoke_with_retry



class _LLMComplianceOutput(BaseModel):
    """The portion of the compliance result the LLM produces."""

    violations: list[ComplianceViolation] = Field(default_factory=list)
    summary: Annotated[str, Field(min_length=10, max_length=2000)]


class ComplianceResult(BaseModel):
    """Full compliance output, including system metadata."""

    violations: list[ComplianceViolation]
    summary: str
    findings_reviewed: int
    grounded_count: int
    """How many of the violations are RAG-grounded (vs LLM-only fallback)."""
    model_used: str


class ComplianceAgent(BaseAgent[InspectionReport, ComplianceResult]):
    """Reviews findings and grounds violations in retrieved regulation excerpts."""

    name = "compliance"

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        retriever: CodeRetriever | None = None,
    ) -> None:
        super().__init__(provider=provider, model=model, temperature=temperature)
        # Load RAG thresholds from settings (configurable via .env)
        from src.config.settings import get_settings
        settings = get_settings()
        self.min_retrieval_score = settings.min_retrieval_score
        self.chunks_per_finding = settings.chunks_per_finding

        # Lazy-load the retriever. If the corpus isn't built yet, the agent
        # falls back to ungrounded mode (logs a warning, proceeds without RAG).
        try:
            self.retriever = retriever or CodeRetriever()
            self._rag_available = True
        except FileNotFoundError as e:
            self.logger.warning("compliance.rag_unavailable", error=str(e))
            self.retriever = None  # type: ignore[assignment]
            self._rag_available = False

    def run(
        self,
        report: InspectionReport,
        building_context: str = "",
    ) -> ComplianceResult:
        """Map findings to violations, grounded in retrieved regulations."""
        self.logger.info(
            "compliance.start",
            photo=report.photo_path,
            findings_count=len(report.findings),
            rag_available=self._rag_available,
            min_retrieval_score=self.min_retrieval_score,
        )

        if not report.findings:
            self.logger.info("compliance.skip", reason="no_findings")
            return ComplianceResult(
                violations=[],
                summary="No findings to review.",
                findings_reviewed=0,
                grounded_count=0,
                model_used=f"{self.provider}:{self.model or 'default'}",
            )

        # ---- Stage 1: per-finding retrieval ----
        per_finding_chunks: dict[int, list[RetrievalResult]] = {}
        if self._rag_available:
            for idx, finding in enumerate(report.findings):
                query = self._build_query(finding)
                try:
                    hits = self.retriever.search(query, top_k=self.chunks_per_finding)
                except Exception as e:
                    self.logger.error(
                        "compliance.retrieval_failed",
                        finding_index=idx,
                        error=str(e),
                    )
                    hits = []

                # Filter low-confidence retrievals.
                strong = [h for h in hits if h.score >= self.min_retrieval_score]
                per_finding_chunks[idx] = strong
                self.logger.info(
                    "compliance.retrieved",
                    finding_index=idx,
                    total_hits=len(hits),
                    kept_hits=len(strong),
                )

        # ---- Stage 2: call LLM with grounded context ----
        findings_text = self._format_findings(report)
        retrieved_text = self._format_retrieved(per_finding_chunks)

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(
                content=COMPLIANCE_USER_PROMPT.format(
                    findings_text=findings_text,
                    retrieved_text=retrieved_text or "(no excerpts retrieved)",
                )
            ),
        ]
        llm_output = invoke_with_retry(self.llm, _LLMComplianceOutput, messages)

        # ---- Stage 3: post-process - attach grounding metadata ----
        violations = self._attach_grounding(llm_output.violations, per_finding_chunks)
        grounded_count = sum(1 for v in violations if v.grounded)

        result = ComplianceResult(
            violations=violations,
            summary=llm_output.summary,
            findings_reviewed=len(report.findings),
            grounded_count=grounded_count,
            model_used=f"{self.provider}:{self.model or 'default'}",
        )

        self.logger.info(
            "compliance.done",
            violations=len(violations),
            grounded=grounded_count,
            findings_reviewed=result.findings_reviewed,
        )
        return result

    # ---------- helpers ----------

    @staticmethod
    def _build_query(finding: InspectionFinding) -> str:
        """Construct a retrieval query from a finding.

        We combine category + key terms from issue/evidence. We do NOT use
        the entire issue/evidence verbatim because long queries can drift.
        """
        parts = [finding.category.value, finding.issue]
        # Pull a short slice of evidence to add domain terms.
        evidence_slice = finding.visual_evidence[:120]
        parts.append(evidence_slice)
        query = " ".join(parts)
        return query[:500]  # cap query length

    @staticmethod
    def _format_findings(report: InspectionReport) -> str:
        lines = []
        for i, f in enumerate(report.findings):
            lines.append(
                f"[{i}] severity={f.severity.value} category={f.category.value}\n"
                f"    issue: {f.issue}\n"
                f"    evidence: {f.visual_evidence}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _format_retrieved(
        per_finding_chunks: dict[int, list[RetrievalResult]]
    ) -> str:
        """Format retrieved chunks for the LLM prompt."""
        if not per_finding_chunks:
            return ""

        lines = []
        for idx in sorted(per_finding_chunks.keys()):
            hits = per_finding_chunks[idx]
            lines.append(f"--- Finding [{idx}] excerpts ---")
            if not hits:
                lines.append("  (no relevant regulation excerpts found)")
                continue
            for j, hit in enumerate(hits, start=1):
                lines.append(
                    f"  [excerpt {j}] score={hit.score:.3f}  {hit.citation()}\n"
                    f"  {hit.text[:600]}"
                )
        return "\n\n".join(lines)

    @staticmethod
    def _attach_grounding(
        violations: list[ComplianceViolation],
        per_finding_chunks: dict[int, list[RetrievalResult]],
    ) -> list[ComplianceViolation]:
        """For each violation, attach the best-matching retrieval excerpt(s).

        We pick the top chunk across all the violation's finding_indices.
        This is a heuristic - a violation might span multiple findings each
        with their own retrievals. We pick the most confident.
        """
        for v in violations:
            best_score = 0.0
            excerpts: list[str] = []
            for idx in v.finding_indices:
                for hit in per_finding_chunks.get(idx, []):
                    if hit.score > best_score:
                        best_score = hit.score
                    # Collect a short excerpt as audit text.
                    excerpts.append(
                        f"[{hit.citation()}] {hit.text[:300]}"
                    )

            if best_score > 0:
                v.grounded = True
                v.retrieval_score = best_score
                v.source_excerpts = excerpts[:3]  # cap at 3 for clarity
        return violations