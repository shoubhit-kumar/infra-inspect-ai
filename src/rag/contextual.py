"""Contextual retrieval - Anthropic's technique for boosting RAG quality.

For each chunk, prepend a short context line describing what document and
section the chunk is from. The embedding then captures both the chunk's
content AND its provenance, dramatically improving retrieval recall.

We use deterministic metadata-driven context (no LLM call per chunk),
which avoids API cost but still captures the structural signal.

Reference: Anthropic blog 2024, 'Introducing Contextual Retrieval'.
"""
import re

from langchain_core.documents import Document

from src.utils.logging import get_logger

logger = get_logger(__name__)


# Extract a section/clause label from chunk text if present.
_SECTION_RE = re.compile(
    r"(PART\s+\d+|CHAPTER\s+\d+|SECTION\s+\d+(\.\d+)*|CLAUSE\s+\d+(\.\d+)*"
    r"|\d+\.\d+(\.\d+)+\s+\w[\w ]{0,60})",
    re.IGNORECASE,
)


def _extract_section_label(text: str) -> str | None:
    """Return the first detected section/clause label, if any."""
    m = _SECTION_RE.search(text)
    if not m:
        return None
    label = m.group(0).strip()
    # Trim very long matches (the pattern can grab a heading + start of body).
    return label[:120]


def add_context(chunks: list[Document]) -> list[Document]:
    """Prepend a contextual prefix to each chunk before embedding.

    Mutates and returns the list. The original raw chunk text is preserved
    in metadata['raw_text'] so we can show users the clean version while
    embedding the contextualized version.

    Example prefix:
        'Context: NBC document nbc_part_4.pdf, page 12, Section 3.4.1.
         The following is a chunk from this section.'
    """
    enriched: list[Document] = []
    for chunk in chunks:
        meta = chunk.metadata or {}
        raw = chunk.page_content
        section_label = _extract_section_label(raw)

        parts = [
            f"Source: {meta.get('regulation_source', 'INTERNAL')} document "
            f"'{meta.get('source_file', 'unknown')}'",
            f"page {meta.get('page', '?')}",
        ]
        if section_label:
            parts.append(f"section: {section_label}")
        context_prefix = "Context: " + ", ".join(parts) + ".\n\nContent:\n"

        new_text = context_prefix + raw

        new_meta = dict(meta)
        new_meta["raw_text"] = raw  # preserve original for display
        new_meta["section_label"] = section_label

        enriched.append(Document(page_content=new_text, metadata=new_meta))

    logger.info("contextual.applied", chunks=len(enriched))
    return enriched