# Requirements Document

## Introduction

Add PDF document ingestion capability to the RAG knowledge base pipeline. The system creates a standalone Python script (`mcp_server_node/scripts/ingest_pdf_sources.py`) that reads the unified manifest for sources with `crawl_type == "pdf_download"`, downloads PDFs, extracts text via pypdf, chunks at 512 tokens with 64-token overlap, embeds with Amazon Titan Text Embeddings v2 (1024 dimensions), and indexes to the `mdc-workflow-docs-titan1024` OpenSearch index. The four target sources are ESMF, ESMC, NUOPC, and ESMPy reference PDFs hosted on earthsystemmodeling.org.

## Glossary

- **PDF_Ingestion_Script**: The Python script `mcp_server_node/scripts/ingest_pdf_sources.py` responsible for downloading, extracting, chunking, embedding, and indexing PDF documents
- **Unified_Manifest**: The JSON configuration file at `mcp_server_python/src/config/unified_manifest.json` that declares all knowledge base sources with their metadata and ingestion parameters
- **Titan_Embedder**: The Amazon Bedrock Titan Text Embeddings v2 model (`amazon.titan-embed-text-v2:0`) producing 1024-dimensional vectors via the BedrockProvider
- **OpenSearch_Index**: The `mdc-workflow-docs-titan1024` OpenSearch index where embedded PDF chunks are stored for semantic retrieval
- **Chunk**: A segment of extracted PDF text sized at 512 tokens with 64-token overlap between consecutive chunks
- **Manifest_Source_Entry**: A JSON object in the Unified_Manifest representing a single documentation source, including fields `name`, `crawl_type`, `enabled`, `url`, `last_ingested`, and `doc_count`

## Requirements

### Requirement 1: Manifest-Driven Source Discovery

**User Story:** As a knowledge base operator, I want the PDF ingestion script to discover PDF sources from the unified manifest, so that source management remains centralized and consistent with the existing pipeline.

#### Acceptance Criteria

1. WHEN the PDF_Ingestion_Script is executed, THE PDF_Ingestion_Script SHALL load the Unified_Manifest and select only Manifest_Source_Entry objects where `crawl_type` equals `"pdf_download"` and `enabled` equals `true`.
2. WHEN the `--source` flag is provided with a source name, THE PDF_Ingestion_Script SHALL process only the Manifest_Source_Entry matching that name.
3. IF a `--source` value does not match any enabled `pdf_download` entry in the Unified_Manifest, THEN THE PDF_Ingestion_Script SHALL exit with a non-zero status code and print an error message identifying the unrecognized source name.

### Requirement 2: PDF Download and Text Extraction

**User Story:** As a knowledge base operator, I want the script to download PDF files and extract their text content, so that PDF-only reference documentation becomes available for semantic search.

#### Acceptance Criteria

1. WHEN the PDF_Ingestion_Script processes a Manifest_Source_Entry, THE PDF_Ingestion_Script SHALL download the PDF from the entry's `url` field using an HTTP GET request with a timeout of 60 seconds.
2. WHEN a PDF is downloaded successfully, THE PDF_Ingestion_Script SHALL extract text from each page using pypdf's `PdfReader` and `page.extract_text()`.
3. THE PDF_Ingestion_Script SHALL concatenate extracted page texts with page boundary markers in the format `\n\n--- Page N ---\n\n` where N is the 1-based page number.
4. IF a PDF download fails due to a network error or HTTP error status, THEN THE PDF_Ingestion_Script SHALL log the error with the source name and URL, skip that source, and continue processing remaining sources.
5. IF a page yields empty text from `extract_text()`, THEN THE PDF_Ingestion_Script SHALL skip that page and continue extraction from subsequent pages.

### Requirement 3: Token-Based Chunking

**User Story:** As a knowledge base operator, I want extracted PDF text chunked at consistent token boundaries, so that each chunk fits within the Titan embedding model's input limits and provides coherent retrieval units.

#### Acceptance Criteria

1. THE PDF_Ingestion_Script SHALL split extracted text into Chunks of 512 tokens with a sliding window overlap of 64 tokens between consecutive chunks.
2. THE PDF_Ingestion_Script SHALL use whitespace-based token approximation (splitting on whitespace) for token counting.
3. IF the remaining text at the end of a document is fewer than 64 tokens, THEN THE PDF_Ingestion_Script SHALL append that text to the final Chunk rather than creating a separate Chunk.

### Requirement 4: Embedding via Titan

**User Story:** As a knowledge base operator, I want chunks embedded using the Titan Text Embeddings v2 model, so that the PDF content is searchable in the same vector space as existing documentation.

#### Acceptance Criteria

1. THE PDF_Ingestion_Script SHALL embed each Chunk using the Titan_Embedder (`amazon.titan-embed-text-v2:0`) producing a 1024-dimensional vector.
2. THE PDF_Ingestion_Script SHALL use the existing `BedrockProvider` from `embedding_provider.py` with the `titan1024` profile from `embedding_registry.py`.
3. IF the Titan_Embedder returns an error for a Chunk, THEN THE PDF_Ingestion_Script SHALL log the error with the source name and chunk index, skip that chunk, and continue processing.

### Requirement 5: OpenSearch Indexing

**User Story:** As a knowledge base operator, I want embedded chunks indexed to the correct OpenSearch index, so that the search_documentation tool can retrieve PDF content.

#### Acceptance Criteria

1. THE PDF_Ingestion_Script SHALL index each embedded Chunk to the OpenSearch_Index (`mdc-workflow-docs-titan1024`).
2. THE PDF_Ingestion_Script SHALL include the following metadata fields with each indexed document: `source` (manifest source name), `url` (PDF URL), `page` (page number where the chunk originated), `chunk_index` (sequential chunk number within the source), `tier` (from manifest entry), and `crawl_type` (value `"pdf_download"`).
3. THE PDF_Ingestion_Script SHALL use the `OpenSearchVectorClient` from `aws_backend.py` with `DB_BACKEND=aws` for indexing.
4. THE PDF_Ingestion_Script SHALL generate deterministic document IDs in the format `{source_name}-chunk-{chunk_index}` to enable idempotent re-ingestion.

### Requirement 6: Manifest Status Writeback

**User Story:** As a knowledge base operator, I want the manifest updated after successful ingestion, so that monitoring tools reflect current ingestion state.

#### Acceptance Criteria

1. WHEN all chunks for a Manifest_Source_Entry are successfully embedded and indexed, THE PDF_Ingestion_Script SHALL update that entry's `last_ingested` field with the current ISO 8601 timestamp.
2. WHEN all chunks for a Manifest_Source_Entry are successfully embedded and indexed, THE PDF_Ingestion_Script SHALL update that entry's `doc_count` field with the total number of chunks indexed for that source.
3. THE PDF_Ingestion_Script SHALL write the updated Unified_Manifest back to disk atomically (write to a temporary file then rename).

### Requirement 7: Dry-Run Mode

**User Story:** As a knowledge base operator, I want a dry-run mode that validates the pipeline without writing to OpenSearch, so that I can verify PDF accessibility and chunking quality before committing resources.

#### Acceptance Criteria

1. WHEN the `--dry-run` flag is provided, THE PDF_Ingestion_Script SHALL download PDFs, extract text, and produce chunks, but skip embedding and indexing steps.
2. WHEN the `--dry-run` flag is provided, THE PDF_Ingestion_Script SHALL print a summary for each source including: source name, PDF size in MB, number of pages extracted, number of chunks produced, and a sample of the first chunk's text (first 200 characters).
3. WHEN the `--dry-run` flag is provided, THE PDF_Ingestion_Script SHALL NOT modify the Unified_Manifest.

### Requirement 8: CLI Interface

**User Story:** As a knowledge base operator, I want a clear command-line interface with standard flags, so that the script integrates with existing operational workflows.

#### Acceptance Criteria

1. THE PDF_Ingestion_Script SHALL accept a `--manifest` argument specifying the path to the Unified_Manifest file, defaulting to `mcp_server_python/src/config/unified_manifest.json`.
2. THE PDF_Ingestion_Script SHALL accept a `--region` argument specifying the AWS region for Bedrock and OpenSearch calls, defaulting to `us-east-1`.
3. THE PDF_Ingestion_Script SHALL accept a `--source` argument to limit processing to a single named source.
4. THE PDF_Ingestion_Script SHALL accept a `--dry-run` flag to enable dry-run mode.
5. THE PDF_Ingestion_Script SHALL print a final summary line reporting total sources processed, total chunks indexed, and elapsed time.

### Requirement 9: Independence from HTML Crawler

**User Story:** As a knowledge base operator, I want the PDF ingestion to operate independently from the HTML crawler, so that the existing `.pdf` URL exclusion in `ingestion_base.py` remains intact and the two pipelines do not interfere.

#### Acceptance Criteria

1. THE PDF_Ingestion_Script SHALL operate as a standalone script that does not import from or modify `ingestion_base.py`.
2. THE PDF_Ingestion_Script SHALL route exclusively on the `crawl_type == "pdf_download"` manifest field, independent of the HTML crawler's URL filtering logic.
3. THE PDF_Ingestion_Script SHALL not remove or modify the `.pdf` exclusion pattern in `ingestion_base.py`'s URL skip list.
