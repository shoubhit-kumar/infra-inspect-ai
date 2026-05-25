"""Manual test for the Inspection Agent.

Run with: python -m scripts.test_inspection
"""
from pathlib import Path

from src.agents.inspection import InspectionAgent
from src.utils.logging import configure_logging


def main() -> None:
    configure_logging()

    samples_dir = Path("data/sample_photos")
    photos = sorted(
        p for p in samples_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )

    if not photos:
        print(f"No photos found in {samples_dir}/. Add some images first.")
        return

    agent = InspectionAgent()
    photo = photos[0]
    print(f"\nAnalyzing: {photo.name}\n")

    report = agent.run(
        photo,
        inspector_notes="Routine annual safety inspection.",
    )

    # Pretty print
    print("=" * 70)
    print(f"INSPECTION REPORT - {report.photo_path}")
    print(f"Model: {report.model_used}")
    print(f"Time:  {report.analyzed_at.isoformat()}")
    print("=" * 70)
    print(f"\nOverall assessment:\n  {report.overall_assessment}\n")
    print(f"Findings ({len(report.findings)}):\n")

    for i, f in enumerate(report.findings, 1):
        print(f"  [{i}] {f.severity.value.upper()} | {f.category.value}")
        print(f"      Issue:      {f.issue}")
        print(f"      Location:   {f.location_hint}")
        print(f"      Evidence:   {f.visual_evidence}")
        print(f"      Confidence: {f.confidence:.2f}")
        print(f"      Action:     {f.recommended_action}\n")


if __name__ == "__main__":
    main()