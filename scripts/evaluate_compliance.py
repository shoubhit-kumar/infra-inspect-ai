"""End-to-end compliance agent eval using DeepEval.

Tests whether the compliance agent's verdicts are faithful to the
retrieved excerpts, not just whether retrieval works.

Manually constructed test cases - small but high-signal.
"""
from deepeval import evaluate
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric
from deepeval.test_case import LLMTestCase
from deepeval.models import GeminiModel

from src.agents.compliance import ComplianceAgent
from src.schemas.enums import FindingSeverity, FindingCategory
from src.schemas.inspection import InspectionFinding, InspectionReport
from src.utils.cache import enable_dev_cache
from src.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

# Hand-picked test cases. Real findings from your earlier runs,
# with expected verdicts based on domain knowledge.
TEST_CASES = [
    {
        "id": "frayed-wiring",
        "finding": InspectionFinding(
            issue="Exposed and frayed wiring with damaged insulation",
            severity=FindingSeverity.CRITICAL,
            category=FindingCategory.ELECTRICAL,
            visual_evidence="Multiple wires show signs of insulation damage, exposed copper visible",
            confidence=0.95,
            location_hint="main electrical panel",
        ),
        "expected_verdict": "MUST cite a wiring insulation regulation and recommend immediate repair",
    },
    {
        "id": "plumbing-corrosion",
        "finding": InspectionFinding(
            issue="Extensive rust and corrosion on plumbing pipe joints",
            severity=FindingSeverity.MAJOR,
            category=FindingCategory.PLUMBING,
            visual_evidence="Significant rust on pipe flanges, peeling paint",
            confidence=0.92,
            location_hint="utility room ceiling",
        ),
        "expected_verdict": "Should cite plumbing maintenance requirements",
    },
    {
        "id": "wall-crack",
        "finding": InspectionFinding(
            issue="Horizontal crack 2cm wide in interior wall",
            severity=FindingSeverity.MAJOR,
            category=FindingCategory.STRUCTURAL,
            visual_evidence="Significant horizontal crack across plastered wall, no visible reinforcement",
            confidence=0.88,
            location_hint="north interior wall",
        ),
        "expected_verdict": "Should classify as structural vs non-structural and recommend assessment",
    },
]


def build_test_cases() -> list[LLMTestCase]:
    """Run compliance agent on each finding, collect outputs as test cases."""
    agent = ComplianceAgent()
    cases: list[LLMTestCase] = []

    for tc in TEST_CASES:
        finding = tc["finding"]
        report = InspectionReport(
            photo_path="diagnostic.png",
            findings=[finding],
            overall_observation="Synthetic test case",
            inspector_notes="",
            model_used="test",
        )

        logger.info(f"compliance_eval.run  id={tc['id']}")
        result = agent.run(report)

        # Concatenate violations into a single "output" string for the eval
        if result.violations:
            actual_output = "\n\n".join(
                f"Violation: {v.regulation_violated}\nDescription: {v.description}\n"
                f"Severity: {v.severity.value}\nGrounded: {v.grounded}"
                for v in result.violations
            )
            # Collect the retrieved excerpts as context
            retrieval_context = []
            for v in result.violations:
                if v.source_excerpts:
                    retrieval_context.extend(v.source_excerpts)
        else:
            actual_output = "NO VIOLATIONS PRODUCED"
            retrieval_context = []

        if not retrieval_context:
            retrieval_context = ["No regulation excerpts were grounded for this finding."]

        cases.append(LLMTestCase(
            input=f"Finding: {finding.issue}\nEvidence: {finding.visual_evidence}",
            actual_output=actual_output,
            expected_output=tc["expected_verdict"],
            retrieval_context=retrieval_context,
        ))

    return cases


def main() -> None:
    configure_logging()
    enable_dev_cache()

    logger.info("compliance_eval.start  cases=3")
    cases = build_test_cases()
    logger.info(f"compliance_eval.collected  count={len(cases)}")

    # Use Gemini as judge for DeepEval metrics
    import os
    judge = GeminiModel(
        model_name="gemini-2.5-flash-lite",
        api_key=os.environ["GOOGLE_API_KEY"],
    )

    metrics = [
        FaithfulnessMetric(threshold=0.7, model=judge),
        AnswerRelevancyMetric(threshold=0.7, model=judge),
    ]

    print("\n" + "=" * 72)
    print("COMPLIANCE AGENT EVALUATION (DeepEval)")
    print("=" * 72)
    results = evaluate(test_cases=cases, metrics=metrics, print_results=True)
    print("\nEval complete.")


if __name__ == "__main__":
    main()