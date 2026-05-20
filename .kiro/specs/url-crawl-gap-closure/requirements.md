# Requirements Document

## Introduction

The RAG knowledge base has 12 `url_crawl` sources declared in the unified manifest (`unified_manifest.json`) with `doc_count: 0` and `last_ingested: null`. These sources represent documentation sites that were either never successfully crawled (3 pre-existing entries) or newly added during the manifest expansion (9 entries from 2026-05-18). This feature ingests all 12 sources into the `mdc-workflow-docs-titan1024` OpenSearch collection using Amazon Titan 1024-dimensional embeddings via Bedrock, with tiered priority ordering and parallel execution support. Sources that contain no crawlable content are marked with an `empty_site` status rather than disabled.

## Glossary

- **Crawl_Orchestrator**: The ingestion execution process that coordinates crawling, chunking, embedding, and indexing of HTML documentation sources into OpenSearch.
- **Unified_Manifest**: The JSON file `mcp_server_python/src/config/unified_manifest.json` that declares all ingest sources, their collection targets, document counts, and last-ingested timestamps.
- **Backfill_Script**: The standalone Python script `scripts/backfill_manifest_status.py` (from Phase 57) that queries OpenSearch for live document counts and writes them back to the manifest.
- **Ingest_Pipeline**: The documentation ingestion script `scripts/ingest_documentation_v8.py` that crawls a URL source, chunks the HTML content, generates Titan 1024-dim embeddings via Bedrock, and indexes the resulting documents into OpenSearch.
- **Gap_Detector**: The `GapDetector` class that compares declared manifest sources against live OpenSearch index statistics and reports coverage gaps.
- **OpenSearch_Collection**: The target OpenSearch index `mdc-workflow-docs-titan1024` where all crawled documentation chunks are stored with their embedding vectors.
- **Empty_Site**: A manifest source whose target URL resolves successfully but contains no crawlable documentation content, resulting in zero indexed documents after a valid crawl attempt.
- **Tier_Priority**: The execution ordering scheme where tier1_critical sources are ingested first, followed by tier2_workflow, tier3_models, and tier4_build in sequence.

## Requirements

### Requirement 1: Tiered Priority Execution Order

**User Story:** As an operator, I want high-priority documentation sources ingested before lower-priority ones, so that critical knowledge (GSI, uwtools) becomes available in the RAG system as early as possible.

#### Acceptance Criteria

1. WHEN the Crawl_Orchestrator begins execution, THE Crawl_Orchestrator SHALL process tier1_critical sources (gsi-user-guide) before tier2_workflow sources (uwtools).
2. WHEN tier1_critical sources complete, THE Crawl_Orchestrator SHALL process tier2_workflow sources before tier3_models sources.
3. WHEN tier2_workflow sources complete, THE Crawl_Orchestrator SHALL process tier3_models sources (mpas-atmosphere, catchem, cece, cdeps, land-da, ufs-srweather-app, hafs) before tier4_build sources.
4. WHEN tier3_models sources complete, THE Crawl_Orchestrator SHALL process tier4_build sources (kokkos-api, nceplibs-sfcio).
5. THE Crawl_Orchestrator SHALL process the pre-existing sources (cmeps, nceplibs-sfcio, kokkos-api) after the newly added sources within their respective tiers.

### Requirement 2: Parallel Crawl Execution

**User Story:** As an operator, I want multiple sources crawled concurrently within a tier, so that the total ingestion time is reduced without overwhelming the Bedrock embedding API.

#### Acceptance Criteria

1. WHILE processing sources within a single tier, THE Crawl_Orchestrator SHALL execute up to 3 concurrent crawl processes.
2. THE Crawl_Orchestrator SHALL limit concurrent Bedrock InvokeModel calls to a maximum of 3 parallel requests across all active crawl processes.
3. WHEN a crawl process completes for one source, THE Crawl_Orchestrator SHALL start the next pending source in the current tier if fewer than 3 processes are active.
4. IF a crawl process encounters a Bedrock throttling error (ThrottlingException), THEN THE Crawl_Orchestrator SHALL apply exponential backoff starting at 2 seconds before retrying the failed embedding request.

### Requirement 3: Source Crawl and Embedding

**User Story:** As a developer, I want each documentation source crawled, chunked, and embedded using Titan 1024-dim vectors, so that the content is searchable via semantic queries in the RAG knowledge base.

#### Acceptance Criteria

1. WHEN the Ingest_Pipeline processes a source, THE Ingest_Pipeline SHALL crawl the source URL up to the `max_pages` limit declared in the Unified_Manifest for that source.
2. WHEN the Ingest_Pipeline extracts HTML content, THE Ingest_Pipeline SHALL chunk the content and generate embedding vectors using the Amazon Titan Embed Text model with 1024 dimensions via Bedrock.
3. WHEN the Ingest_Pipeline generates document chunks, THE Ingest_Pipeline SHALL index the chunks into the `mdc-workflow-docs-titan1024` OpenSearch_Collection.
4. WHEN the Ingest_Pipeline completes indexing for a source, THE Ingest_Pipeline SHALL record the source name, document count, and completion timestamp in the execution log.
5. THE Ingest_Pipeline SHALL tag each indexed document with the source name metadata field matching the manifest source name.

### Requirement 4: Empty Site Handling

**User Story:** As an operator, I want sources with no crawlable content marked as empty rather than disabled, so that future re-crawl attempts can detect when content becomes available.

#### Acceptance Criteria

1. WHEN the Ingest_Pipeline completes a crawl attempt and produces zero documents, THE Crawl_Orchestrator SHALL mark the source with status `empty_site` in the execution results.
2. WHEN a source is marked as `empty_site`, THE Crawl_Orchestrator SHALL retain the source as `enabled: true` in the Unified_Manifest.
3. WHEN a source is marked as `empty_site`, THE Crawl_Orchestrator SHALL set `doc_count` to 0 and update `last_ingested` to the current UTC timestamp in the Unified_Manifest.
4. THE Crawl_Orchestrator SHALL apply `empty_site` handling to cmeps, nceplibs-sfcio, and kokkos-api if those sources produce zero documents after a valid crawl attempt.
5. IF a source URL returns HTTP 404 or 5xx during the crawl attempt, THEN THE Crawl_Orchestrator SHALL log the failure with the HTTP status code and skip the source without marking it as `empty_site`.

### Requirement 5: Manifest Status Writeback

**User Story:** As an operator, I want the manifest updated with live document counts and timestamps after ingestion completes, so that the gap detection table reflects the current state of the knowledge base.

#### Acceptance Criteria

1. WHEN all 12 sources have been attempted, THE Crawl_Orchestrator SHALL invoke the Backfill_Script to update `last_ingested` and `doc_count` for all successfully ingested sources.
2. WHEN the Backfill_Script updates a source, THE Unified_Manifest SHALL contain the live document count from OpenSearch in the `doc_count` field for that source.
3. WHEN the Backfill_Script updates a source with `doc_count` greater than zero, THE Unified_Manifest SHALL contain a non-null `last_ingested` timestamp in ISO-8601 format.
4. WHEN the Backfill_Script completes, THE Gap_Detector SHALL report zero pending sources for all successfully ingested entries when queried via `list_all_sources(include_gaps=True)`.

### Requirement 6: Acceptance Threshold

**User Story:** As an operator, I want a clear success threshold for the batch ingestion, so that I can determine whether the gap closure operation succeeded or requires investigation.

#### Acceptance Criteria

1. WHEN all 12 sources have been attempted, THE Crawl_Orchestrator SHALL report the total count of sources with `doc_count` greater than zero.
2. THE Crawl_Orchestrator SHALL consider the batch ingestion successful when at least 9 of the 12 sources have `doc_count` greater than zero after completion.
3. IF fewer than 9 sources achieve `doc_count` greater than zero, THEN THE Crawl_Orchestrator SHALL report the batch as requiring investigation and list the failed sources with their error details.
4. THE Crawl_Orchestrator SHALL produce a summary report listing each source name, final document count, status (ingested, empty_site, or failed), and elapsed crawl time.

### Requirement 7: Knowledge Base Integrity

**User Story:** As an operator, I want the ingestion to preserve existing knowledge base content, so that adding new sources does not degrade search quality for previously indexed documentation.

#### Acceptance Criteria

1. WHILE ingesting new sources, THE Ingest_Pipeline SHALL append documents to the OpenSearch_Collection without deleting or overwriting existing documents from other sources.
2. WHEN all ingestion completes, THE OpenSearch_Collection SHALL contain at least 27,222 total documents (the pre-ingestion baseline count).
3. WHEN all ingestion completes, THE Gap_Detector SHALL confirm that previously ingested sources retain their document counts within a 5% tolerance of their pre-ingestion values.

### Requirement 8: Verification via Search Queries

**User Story:** As an operator, I want to verify successful ingestion by running semantic search queries against the newly indexed content, so that I can confirm the documents are retrievable and relevant.

#### Acceptance Criteria

1. WHEN gsi-user-guide ingestion completes, THE OpenSearch_Collection SHALL return relevant results for a `search_documentation` query containing "GSI gridpoint statistical interpolation".
2. WHEN uwtools ingestion completes, THE OpenSearch_Collection SHALL return relevant results for a `search_documentation` query containing "uwtools workflow tools".
3. WHEN tier3_models ingestion completes, THE OpenSearch_Collection SHALL return relevant results for `search_documentation` queries containing "MPAS unstructured mesh" and "HAFS hurricane vortex initialization".
4. WHEN verification queries return zero results for a source that reported `doc_count` greater than zero, THE Crawl_Orchestrator SHALL flag that source for manual investigation.

