"""OCR fallback for image-based or low-text PDFs.

Standard pypdf extracts text from PDFs that have an embedded text layer.
Scanned documents and image-only PDFs return little or no text. For those,
we render each page to an image and run Tesseract OCR.

This is a production-grade hygiene step: building codes occasionally
appear as scans of older printed documents.
"""
import os
from pathlib import Path

import pytesseract
from langchain_core.documents import Document
from pdf2image import convert_from_path

from src.utils.logging import get_logger


# Locate Tesseract binary.
# Common Windows install locations - first match wins.
_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.environ.get("TESSERACT_CMD", ""),  # explicit override via env var
]
for _candidate in _TESSERACT_CANDIDATES:
    if _candidate and Path(_candidate).exists():
        pytesseract.pytesseract.tesseract_cmd = _candidate
        break

# Same for Poppler - use explicit path if discoverable.
_POPPLER_CANDIDATES = [
    r"C:\Program Files\poppler-26.02.0\Library\bin",
    r"C:\Program Files\poppler-25.07.0\Library\bin",
    os.environ.get("POPPLER_PATH", ""),
]
_POPPLER_PATH = next(
    (p for p in _POPPLER_CANDIDATES if p and Path(p).exists()),
    None,
)

logger = get_logger(__name__)

# Threshold: if a page has fewer than this many characters from pypdf,
# we treat it as failed text extraction and fall back to OCR.
MIN_CHARS_PER_PAGE = 50


def needs_ocr(docs: list[Document]) -> bool:
    """Decide whether a PDF needs OCR based on extracted text length."""
    if not docs:
        return True
    total_chars = sum(len(d.page_content.strip()) for d in docs)
    avg_chars = total_chars / len(docs)
    return avg_chars < MIN_CHARS_PER_PAGE


def ocr_pdf(path: Path, dpi: int = 200) -> list[Document]:
    """Run OCR on every page of a PDF and return Documents.

    Args:
        path: PDF file path.
        dpi: Image resolution for rendering. 200 is the sweet spot for
             OCR accuracy vs speed. 300+ is overkill for printed text.
    """
    logger.info("ocr.start", file=path.name, dpi=dpi)

    try:
        if _POPPLER_PATH:
            images = convert_from_path(str(path), dpi=dpi, poppler_path=_POPPLER_PATH)
        else:
            images = convert_from_path(str(path), dpi=dpi)
    except Exception as e:
        logger.error("ocr.pdf2image_failed", file=path.name, error=str(e))
        return []

    docs: list[Document] = []
    for i, image in enumerate(images, start=1):
        try:
            text = pytesseract.image_to_string(image)
        except Exception as e:
            logger.error("ocr.page_failed", file=path.name, page=i, error=str(e))
            text = ""

        docs.append(
            Document(
                page_content=text,
                metadata={
                    "source_file": path.name,
                    "source_path": str(path),
                    "page": i,
                    "ocr_used": True,
                },
            )
        )

    logger.info("ocr.done", file=path.name, pages=len(docs))
    return docs