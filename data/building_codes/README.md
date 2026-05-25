# Building Codes Corpus

This directory should contain the source PDFs used to build the RAG index.
For licensing reasons, they are not included in the repository.

## Required PDFs

| File | Source | Notes |
|------|--------|-------|
| `nbc-2016-volume-1.pdf` | [Bureau of Indian Standards](https://www.bis.gov.in/) | National Building Code Vol. 1 |
| `nbc-2016-volume-2.pdf` | Bureau of Indian Standards | National Building Code Vol. 2 |
| `is.2190.2010.pdf` | Bureau of Indian Standards | Fire extinguishers - selection and installation |
| `is.732.2019.pdf` | Bureau of Indian Standards | Electrical wiring installation |
| (others as needed) | various | NFPA, ASHRAE, IFC, etc. |

## Building the Index

After placing the PDFs in this folder:

```bash
python -m scripts.ingest_codes        # extracts text, OCRs scanned pages, chunks, embeds
python -m scripts.build_bm25          # builds BM25 sparse index
```

Output goes to `data/vector_db/`. Total: ~500 MB, ~25k chunks.