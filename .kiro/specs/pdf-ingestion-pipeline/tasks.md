# Implementation Plan: PDF Ingestion Pipeline

## Overview

Create a standalone Python script (`mcp_server_node/scripts/ingest_pdf_sources.py`) that downloads PDF documents declared in the unified manifest with `crawl_type == "pdf_download"`, extracts text via pypdf, chunks at 512-token windows with 64-token overlap, embeds with Amazon Titan Text Embeddings v2 (1024 dimensions), and indexes to the `mdc-workflow-docs-titan1024` OpenSearch index. Verification is done via `--dry-run` mode and live search queries — no new unit test files.

## Tasks

- [x] 1. Create the PDF ingestion script with CLI and manifest loading
  - [x] 1.1 Create `mcp_server_node/scripts/ingest_pdf_sources.py` with imports, `parse_args()`, and `load_pdf_sources()`
    - Add shebang, module docstring, and all required imports (`argparse`, `json`, `os`, `sys`, `io`, `re`, `time`, `datetime`, `requests`, `pypdf`)
    - Implement `parse_args()` with `--manifest`, `--region`, `--source`, `--dry-run` arguments per design
    - Implement `load_pdf_sources()` to filter manifest for `crawl_type == "pdf_download"` and `enabled == true`
    - Handle `--source` filter with non-zero exit on mismatch
    - _Requirements: 1.1, 1.2, 1.3, 8.1, 8.2, 8.3, 8.4_

- [x] 2. Implement PDF download and text extraction
  - [x] 2.1 Implement `download_pdf()` and `extract_text()` functions
    - `download_pdf()`: HTTP GET with 60s timeout, returns `None` on failure with logged error
    - `extract_text()`: pypdf `PdfReader` over `io.BytesIO`, concatenate non-empty pages with `--- Page N ---` markers
    - Skip pages that yield empty text from `extract_text()`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 3. Implement token-based chunking and embedding
  - [x] 3.1 Implement `chunk_text()` function
    - Whitespace-split tokenization, 512-token chunks with 64-token sliding overlap
    - Absorb final remainder < 64 tokens into the last chunk
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 3.2 Implement `embed_chunks()` function
    - Use existing `BedrockProvider` with `titan1024` profile from `embedding_registry.py`
    - Per-chunk error handling: log and skip failed chunks, continue processing
    - Return list of `(chunk_index, vector)` tuples
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 4. Implement OpenSearch indexing and manifest writeback
  - [x] 4.1 Implement `index_chunks()` and `_estimate_page()` functions
    - Generate deterministic IDs: `{source_name}-chunk-{chunk_index}`
    - Include all six metadata fields: `source`, `url`, `page`, `chunk_index`, `tier`, `crawl_type`
    - Use `OpenSearchVectorClient` from `aws_backend.py` with `get_or_create_collection()`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 4.2 Implement `update_manifest()` function
    - Atomic write via temp file + `os.replace()`
    - Update `last_ingested` (ISO 8601) and `doc_count` fields per source
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 5. Implement main orchestrator with dry-run support
  - [x] 5.1 Implement `main()` function wiring all components together
    - Initialize `BedrockProvider` and `OpenSearchVectorClient` (skip in dry-run)
    - Loop over PDF sources: download → extract → chunk → embed → index
    - Dry-run path: print source name, PDF size, pages extracted, chunks produced, first chunk sample
    - Update manifest entries after successful indexing (skip in dry-run)
    - Print final summary: sources processed, chunks indexed, elapsed time
    - Add `if __name__ == "__main__": main()` entry point
    - _Requirements: 7.1, 7.2, 7.3, 8.5, 9.1, 9.2_

- [x] 6. Checkpoint — Verify dry-run mode works end-to-end
  - Ensure all tests pass, ask the user if questions arise.
  - Run `python mcp_server_node/scripts/ingest_pdf_sources.py --dry-run` and confirm output shows PDF sizes, page counts, and chunk counts for all enabled pdf_download sources

- [x] 7. Add manifest entries and run live ingestion
  - [x] 7.1 Verify manifest entries exist for PDF sources
    - Confirm `mcp_server_python/src/config/unified_manifest.json` contains the ESMF, ESMC, NUOPC, and ESMPy entries with `crawl_type: "pdf_download"` and `enabled: true`
    - If missing, add the four source entries per the data model in the design document
    - _Requirements: 1.1_

  - [x] 7.2 Run live ingestion and verify via search queries
    - Execute `python mcp_server_node/scripts/ingest_pdf_sources.py --region us-east-1`
    - Verify manifest is updated with `last_ingested` timestamps and `doc_count` values
    - Verify indexed documents are retrievable via `search_documentation` tool queries for ESMF/NUOPC content
    - _Requirements: 5.1, 6.1, 6.2, 6.3_

- [x] 8. Final checkpoint — Confirm pipeline operational
  - Ensure all tests pass, ask the user if questions arise.
  - Confirm dry-run produces expected output, live ingestion indexes documents, and search queries return PDF-sourced results

## Notes

- No new unit test files are required — verification is via `--dry-run` mode and live search queries
- The script is fully standalone and does not import from `ingestion_base.py`
- The script reuses existing `BedrockProvider` and `OpenSearchVectorClient` infrastructure
- Existing `.pdf` exclusion in `ingestion_base.py` line 617 remains untouched
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["3.2", "4.1"] },
    { "id": 3, "tasks": ["4.2"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["7.1"] },
    { "id": 6, "tasks": ["7.2"] }
  ]
}
```
