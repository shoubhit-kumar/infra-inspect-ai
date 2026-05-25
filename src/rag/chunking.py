"""Document chunking with structure-aware splitting.

Strategy:
1. If a document looks structured (heading patterns detected), split at those
   boundaries first, then sub-split any oversized sections.
2. Otherwise, fall back to recursive character splitting.

Heading detection is heuristic - regulation documents typically have
patterns like 'Part 4', 'Section 3.4.1', 'CHAPTER 5'. We treat those as
natural boundaries.
"""
import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.utils.logging import get_logger

logger = get_logger(__name__)


# Heading patterns common in regulation PDFs.
# Order matters: most-specific first.
HEADING_PATTERNS = [
    re.compile(r"^\s*PART\s+\d+\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*CHAPTER\s+\d+\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*SECTION\s+\d+(\.\d+)*\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\d+\.\d+(\.\d+)+\s+\w", re.MULTILINE),  # e.g. "3.4.1 Fire ..."
    re.compile(r"^\s*CLAUSE\s+\d+(\.\d+)*\b", re.IGNORECASE | re.MULTILINE),
]


def _detect_headings(text: str) -> bool:
    """Return True if the text appears structured enough to split on headings."""
    matches = sum(len(p.findall(text)) for p in HEADING_PATTERNS)
    # Need at least 3 heading hits to consider the doc structured.
    return matches >= 3


def _structure_split(text: str) -> list[str]:
    """Split text at detected heading boundaries.

    Produces sections each starting with a heading line. The text before
    the first heading (preamble) becomes its own section if non-trivial.
    """
    # Find all heading positions
    positions: list[int] = []
    for pattern in HEADING_PATTERNS:
        for m in pattern.finditer(text):
            positions.append(m.start())

    if not positions:
        return [text]

    positions = sorted(set(positions))
    sections: list[str] = []
    prev = 0
    for pos in positions:
        chunk = text[prev:pos].strip()
        if chunk:
            sections.append(chunk)
        prev = pos
    tail = text[prev:].strip()
    if tail:
        sections.append(tail)
    return sections


def chunk_documents(
    docs: list[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> list[Document]:
    """Split documents into chunks, preferring structural boundaries.

    For each document:
    - If headings are detected, split there first, then sub-split any
      sections still larger than chunk_size using recursive splitting.
    - Else, fall back to recursive character splitting.

    Always preserves metadata from the parent document.
    """
    recursive = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
        length_function=len,
    )

    output: list[Document] = []
    structured_count = 0

    for doc in docs:
        text = doc.page_content
        meta = doc.metadata or {}

        if _detect_headings(text):
            sections = _structure_split(text)
            for section in sections:
                if len(section) <= chunk_size:
                    output.append(Document(page_content=section, metadata=dict(meta)))
                else:
                    # Section still too big; sub-split it.
                    for sub in recursive.split_text(section):
                        output.append(Document(page_content=sub, metadata=dict(meta)))
            structured_count += 1
        else:
            # No detected structure; recursive split.
            for chunk_text in recursive.split_text(text):
                output.append(Document(page_content=chunk_text, metadata=dict(meta)))

    # Add per-page chunk index for traceability
    page_counters: dict[tuple[str, int], int] = {}
    for chunk in output:
        key = (chunk.metadata.get("source_file", ""), chunk.metadata.get("page", 0))
        page_counters[key] = page_counters.get(key, 0) + 1
        chunk.metadata["chunk_index"] = page_counters[key]

    logger.info(
        "chunking.complete",
        input_docs=len(docs),
        output_chunks=len(output),
        structured_docs=structured_count,
        recursive_only_docs=len(docs) - structured_count,
    )
    return output