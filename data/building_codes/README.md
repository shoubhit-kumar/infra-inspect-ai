# Building Codes Corpus

This directory holds the source PDFs that get ingested into the RAG index. They are **not committed** to the repository for licensing reasons - the source documents are copyrighted by their respective standards bodies (BIS, NFPA, etc.).

## What you need

To reproduce the inspection workflow, you'll need the following standards documents:

| File | Source | Description |
|------|--------|-------------|
| `nbc-2016-volume-1.pdf` | [Bureau of Indian Standards](https://www.bis.gov.in/) | National Building Code 2016, Volume 1 - General Building Requirements |
| `nbc-2016-volume-2.pdf` | Bureau of Indian Standards | National Building Code 2016, Volume 2 - Building Services |
| `is.2190.2010.pdf` | Bureau of Indian Standards | IS 2190:2010 - Selection, Installation and Maintenance of First-Aid Fire Extinguishers |
| `is.732.2019.pdf` | Bureau of Indian Standards | IS 732:2019 - Code of Practice for Electrical Wiring Installations |
| `is.875.part3.pdf` | Bureau of Indian Standards | IS 875 (Part 3) - Wind loads on buildings and structures |

Place all PDFs directly in this folder (no subdirectories).

## Where to get them

- **BIS standards (NBC, IS):** purchase or download from [bis.gov.in](https://www.bis.gov.in/). Some are available free; full copies require purchase.
- **NFPA standards:** purchase from [nfpa.org](https://www.nfpa.org/).
- **Local building codes:** check your municipal authority.

You can also use any other PDFs - the ingestion pipeline is corpus-agnostic. The agents will retrieve whatever you index.

## Building the RAG index

After placing the PDFs in this folder, run:

```bash
# Step 1: extract text (OCR scanned pages if needed), chunk, embed, build FAISS index
python -m scripts.ingest_codes

# Step 2: build the BM25 sparse index
python -m scripts.build_bm25
```

The first run takes 5-10 minutes depending on PDF count and CPU. Output:

```
data/vector_db/
  codes_index/                  # FAISS dense index (~500MB for 5-10 PDFs)
  bm25_index.pkl                # BM25 sparse index
```

These are also gitignored. You only build them once locally; the workflow loads them on every run.

## Verifying the index

```bash
python -m scripts.test_retrieval "Exposed and frayed electrical wiring"
```

Should return ~5 chunks with source citations from your indexed PDFs.