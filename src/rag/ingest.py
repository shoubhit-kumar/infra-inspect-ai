"""PDF ingestion for the RAG pipeline.

Pipeline:
  1. Try standard text extraction via PyPDFLoader (fast, lossless when it works).
  2. If extracted text is sparse (likely image-based PDF), fall back to OCR.
  3. Enrich each Document with metadata for citation and filtering.
"""
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from src.rag.ocr import needs_ocr, ocr_pdf
from src.utils.logging import get_logger

logger = get_logger(__name__)


_SOURCE_KEYWORDS = {
    "nbc": "NBC",
    "national_building_code": "NBC",
    "is_": "IS",
    "is-": "IS",
    "indian_standard": "IS",
    "nfpa": "NFPA",
    "osha": "OSHA",
}


def _guess_source(filename: str) -> str:
    lower = filename.lower()
    for needle, source in _SOURCE_KEYWORDS.items():
        if needle in lower:
            return source
    return "INTERNAL"


def _enrich_metadata(docs: list[Document], path: Path) -> None:
    """Add common metadata in place."""
    source_label = _guess_source(path.name)
    for doc in docs:
        existing = doc.metadata or {}
        doc.metadata = {
            "source_file": path.name,
            "source_path": str(path),
            "regulation_source": source_label,
            # pypdf gives 0-indexed pages, OCR path already gives 1-indexed
            "page": existing.get("page", 0) + (0 if existing.get("ocr_used") else 1),
            "ocr_used": existing.get("ocr_used", False),
        }


def load_pdf(path: Path) -> list[Document]:
    """Load a PDF, with OCR fallback for image-based pages."""
    # Pass 1: standard text extraction
    try:
        loader = PyPDFLoader(str(path))
        docs = loader.load()
    except Exception as e:
        logger.warning("ingest.pypdf_failed", file=path.name, error=str(e))
        docs = []

    if needs_ocr(docs):
        logger.info("ingest.ocr_fallback", file=path.name)
        docs = ocr_pdf(path)

    _enrich_metadata(docs, path)

    logger.info(
        "ingest.loaded_pdf",
        file=path.name,
        pages=len(docs),
        ocr=any(d.metadata.get("ocr_used") for d in docs),
    )
    return docs


def load_directory(directory: Path) -> list[Document]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    pdfs = sorted(directory.glob("*.pdf"))
    if not pdfs:
        logger.warning("ingest.no_pdfs", directory=str(directory))
        return []

    all_docs: list[Document] = []
    for pdf in pdfs:
        try:
            all_docs.extend(load_pdf(pdf))
        except Exception as e:
            logger.error("ingest.pdf_failed", file=pdf.name, error=str(e))

    logger.info("ingest.complete", pdfs=len(pdfs), total_pages=len(all_docs))
    return all_docs