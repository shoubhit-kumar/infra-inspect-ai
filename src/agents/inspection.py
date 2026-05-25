"""Inspection Agent: vision-based photo analysis."""
import base64
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from typing import Annotated

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent
from src.prompts.inspection import INSPECTION_SYSTEM_PROMPT, INSPECTION_USER_PROMPT
from src.schemas.inspection import InspectionFinding, InspectionReport


class _LLMInspectionOutput(BaseModel):
    """The slice of InspectionReport the LLM is allowed to produce.

    Excludes metadata (photo_path, analyzed_at, model_used) which we set
    ourselves to prevent hallucinated timestamps and model names.
    """

    findings: list[InspectionFinding] = Field(default_factory=list)
    overall_assessment: Annotated[str, Field(min_length=20, max_length=2000)]


class InspectionAgent(BaseAgent[Path, InspectionReport]):
    """Analyzes a single inspection photo and returns structured findings.

    Always uses the vision-capable LLM (settings.vision_llm_provider).
    A multimodal model is required regardless of what the default text
    LLM provider is, because the agent sends an image with each prompt.
    """

    name = "inspection"

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> None:
        # Vision agent forces the vision provider unless caller overrides explicitly.
        if provider is None:
            from src.config.settings import get_settings
            provider = get_settings().vision_llm_provider
        super().__init__(provider=provider, model=model, temperature=temperature)

    def run(
        self,
        photo_path: Path,
        inspector_notes: str = "",
        history_text: str = "",
    ) -> InspectionReport:
        """Analyze one photo.

        Args:
            photo_path: Path to image file (jpg, png, webp).
            inspector_notes: Optional context from the human inspector.

        Returns:
            InspectionReport with findings and overall assessment.
        """
        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")

        self.logger.info("inspection.start", photo=str(photo_path))

        # Read image as base64
        image_b64 = self._encode_image(photo_path)
        mime_type = self._mime_type(photo_path)
        

        # Build the multimodal message: text + image
        messages = [
            SystemMessage(content=INSPECTION_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": INSPECTION_USER_PROMPT.format(
                            inspector_notes=inspector_notes or "(none)",
                            history_text=history_text or "(no prior inspections recorded)",
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": f"data:{mime_type};base64,{image_b64}",
                    },
                ]
            ),
        ]

        # Call the LLM with resilient structured output (retries on validation errors).
        from src.utils.structured_output import invoke_with_retry
        llm_output = invoke_with_retry(self.llm, _LLMInspectionOutput, messages)

        # Compose the full report. Metadata fields are set by us, not the LLM.
        report = InspectionReport(
            photo_path=str(photo_path),
            findings=llm_output.findings,
            overall_assessment=llm_output.overall_assessment,
            model_used=f"{self.provider}:{self.model or 'default'}",
        )

        self.logger.info(
            "inspection.done",
            photo=str(photo_path),
            findings_count=len(report.findings),
        )
        return report

    @staticmethod
    def _encode_image(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    @staticmethod
    def _mime_type(path: Path) -> str:
        ext = path.suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(ext, "image/jpeg")