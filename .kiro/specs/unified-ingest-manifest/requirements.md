# Requirements Document

## Introduction

The MDC MCP RAG Server knowledge base contains content from seven distinct source types (URL-crawled documentation, on-disk submodule reads, code-context parsing, Rocoto/config ingestion, EE2 compliance standards, community summaries, and J-Job documentation). The current ingest manifest (`documentation_sources.json`) and its associated MCP tools (`list_ingested_urls`, `get_ingested_urls_array`) only track URL-based documentation sources — roughly 40 of the 120,255 documents across 5 OpenSearch indices. This feature extends the SPOT (Source of Production Truth) protocol to a unified manifest that registers every source type, enabling complete observability, gap detection, and provenance tracking across the entire knowledge base.

## Glossary

- **Unified_Manifest**: A JSON configuration file that declares all ingestion sources across all source types, replacing the URL-only `documentation_sources.json` as the single source of truth for what the knowledge base should contain.
- **Source_Entry**: A single record within the Unified_Manifest describing one ingestion source, including its type, target collection, embedding profile, and metadata.
- **Source_Type**: A classification of how content enters the knowledge base. Valid values: `url_crawl`, `on_disk_submodule`, `code_parse`, `config_parse`, `standards`, `community_summary`, `jjob_docs`.
- **Manifest_Registry**: The in-memory representation of the Unified_Manifest loaded by the MCP server at boot time, used by tools to report knowledge base contents.
- **Gap_Detector**: A component that compares declared Source_Entries in the Unified_Manifest against actual document counts in OpenSearch indices to identify missing or stale ingestions.
- **Embedding_Profile**: The embedding model configuration used to vectorize documents for a given source (e.g., `titan1024` for Bedrock Titan Embed Text V2 at 1024 dimensions).
- **Collection_Target**: The logical OpenSearch index that a Source_Entry's documents are stored in (e.g., `mdc-code-context-titan1024`, `mdc-workflow-docs-titan1024`).
- **SPOT_Protocol**: Source of Production Truth — the principle that the manifest file is the authoritative declaration of what the knowledge base should contain.
- **MCP_Server**: The Python FastMCP server (`mcp_server_python/`) that exposes tools to AI agents via the Model Context Protocol.
- **Ingestion_Script**: A Python script in `mcp_server_node/scripts/` that parses source material and writes documents into OpenSearch and Neptune.

## Requirements

### Requirement 1: Unified Manifest Schema

**User Story:** As a knowledge base operator, I want a single manifest file that declares all ingestion sources regardless of type, so that I have one authoritative registry of everything in the knowledge base.

#### Acceptance Criteria

1. THE Unified_Manifest SHALL contain a top-level `version` field with a semantic version string.
2. THE Unified_Manifest SHALL contain a top-level `sources` array where each element is a Source_Entry.
3. WHEN a Source_Entry has `source_type` of `url_crawl`, THE Source_Entry SHALL include `url`, `crawl_type`, `max_pages`, and `tier` fields.
4. WHEN a Source_Entry has `source_type` of `on_disk_submodule`, THE Source_Entry SHALL include `local_path`, `file_patterns`, and `parser` fields.
5. WHEN a Source_Entry has `source_type` of `code_parse`, THE Source_Entry SHALL include `root_path`, `languages`, and `chunk_strategy` fields.
6. WHEN a Source_Entry has `source_type` of `config_parse`, THE Source_Entry SHALL include `config_root`, `file_patterns`, and `parser` fields.
7. WHEN a Source_Entry has `source_type` of `standards`, THE Source_Entry SHALL include `standards_source` and `document_count` fields.
8. WHEN a Source_Entry has `source_type` of `community_summary`, THE Source_Entry SHALL include `graph_source` and `community_algorithm` fields.
9. WHEN a Source_Entry has `source_type` of `jjob_docs`, THE Source_Entry SHALL include `job_script_root` and `documentation_format` fields.
10. THE Source_Entry SHALL include common fields: `name`, `source_type`, `collection_target`, `embedding_profile`, `enabled`, `description`, `last_ingested`, and `ingestion_script` for all source types.
11. THE Unified_Manifest SHALL validate that each `collection_target` maps to a known OpenSearch index in the active Embedding_Profile.

### Requirement 2: Backward Compatibility with URL Manifest

**User Story:** As a developer, I want the unified manifest to preserve the existing URL source declarations, so that current ingestion workflows continue to function without modification.

#### Acceptance Criteria

1. THE Unified_Manifest SHALL include all sources currently declared in `documentation_sources.json` as Source_Entries with `source_type` of `url_crawl`.
2. WHEN the Unified_Manifest is loaded, THE Manifest_Registry SHALL expose a filtered view containing only `url_crawl` sources for backward-compatible tool responses.
3. THE Unified_Manifest SHALL preserve the `tier`, `priority`, and `max_pages` fields from the existing `documentation_sources.json` schema within `url_crawl` Source_Entries.
4. WHEN a legacy tool requests URL-only data, THE Manifest_Registry SHALL return results identical in structure to the current `documentation_sources.json` output.

### Requirement 3: MCP Tool — List All Sources

**User Story:** As an AI agent, I want an MCP tool that reports all knowledge base sources across all types, so that I can understand the complete contents of the knowledge base.

#### Acceptance Criteria

1. THE MCP_Server SHALL expose a tool named `list_all_sources` that returns all Source_Entries from the Unified_Manifest.
2. WHEN `list_all_sources` is called with a `source_type` filter, THE MCP_Server SHALL return only Source_Entries matching that source type.
3. WHEN `list_all_sources` is called with a `collection` filter, THE MCP_Server SHALL return only Source_Entries targeting that Collection_Target.
4. WHEN `list_all_sources` is called with `format` set to `summary`, THE MCP_Server SHALL return aggregated counts grouped by source type and collection.
5. WHEN `list_all_sources` is called with `format` set to `detailed`, THE MCP_Server SHALL return full Source_Entry metadata for each source.
6. THE `list_all_sources` tool SHALL include actual document counts from OpenSearch alongside declared counts from the manifest.

### Requirement 4: Updated Existing Tools

**User Story:** As an AI agent using the existing `list_ingested_urls` and `get_ingested_urls_array` tools, I want these tools to continue working with their current interface, so that existing workflows are not disrupted.

#### Acceptance Criteria

1. THE MCP_Server SHALL continue to expose `list_ingested_urls` with its current parameter interface (`format`, `source_filter`).
2. THE MCP_Server SHALL continue to expose `get_ingested_urls_array` with its current parameter interface (`include_failed`).
3. WHEN `list_ingested_urls` is called, THE MCP_Server SHALL return URL-based sources from the Unified_Manifest filtered to `source_type` of `url_crawl`.
4. WHEN `get_ingested_urls_array` is called, THE MCP_Server SHALL return the same JSON structure as the current implementation, sourced from `url_crawl` entries in the Unified_Manifest.
5. WHEN `list_ingested_urls` is called with `format` set to `detailed`, THE MCP_Server SHALL append a summary section showing non-URL source counts to inform agents that additional sources exist.

### Requirement 5: Per-Source Metadata Tracking

**User Story:** As a knowledge base operator, I want each source entry to track when it was last ingested and by which script, so that I can identify stale sources and trace ingestion provenance.

#### Acceptance Criteria

1. THE Source_Entry SHALL include a `last_ingested` field containing an ISO 8601 timestamp of the most recent successful ingestion.
2. THE Source_Entry SHALL include an `ingestion_script` field containing the relative path to the Python script responsible for ingesting that source.
3. THE Source_Entry SHALL include a `doc_count` field containing the expected number of documents produced by the most recent ingestion.
4. WHEN an Ingestion_Script completes successfully, THE Ingestion_Script SHALL update the `last_ingested` and `doc_count` fields in the Unified_Manifest for its corresponding Source_Entry.
5. IF an Ingestion_Script fails to update the Unified_Manifest after ingestion, THEN THE Gap_Detector SHALL flag that source as having an unknown ingestion state.

### Requirement 6: Gap Detection

**User Story:** As a knowledge base operator, I want to compare the manifest declarations against actual OpenSearch index contents, so that I can identify sources that are declared but missing or have fewer documents than expected.

#### Acceptance Criteria

1. THE Gap_Detector SHALL compare each Source_Entry's `doc_count` against the actual document count in the corresponding OpenSearch index.
2. WHEN the actual document count for a Collection_Target is less than 90% of the sum of declared `doc_count` values for that target, THE Gap_Detector SHALL report a coverage gap.
3. WHEN a Source_Entry has `enabled` set to `true` and `last_ingested` is older than 30 days, THE Gap_Detector SHALL report that source as potentially stale.
4. WHEN a Source_Entry has `enabled` set to `true` and `last_ingested` is null, THE Gap_Detector SHALL report that source as never ingested.
5. THE MCP_Server SHALL expose gap detection results through the `list_all_sources` tool when called with `include_gaps` set to `true`.
6. THE Gap_Detector SHALL produce a per-collection summary showing declared versus actual document counts.

### Requirement 7: Manifest Generation and Validation

**User Story:** As a developer, I want a script that generates the unified manifest from the current knowledge base state, so that I can bootstrap the manifest from existing ingestion artifacts.

#### Acceptance Criteria

1. THE MCP_Server SHALL include a generation script that produces a valid Unified_Manifest by scanning existing ingestion scripts and OpenSearch indices.
2. WHEN the generation script runs, THE generation script SHALL discover all Ingestion_Scripts in `mcp_server_node/scripts/` and map each to a Source_Entry.
3. WHEN the generation script runs, THE generation script SHALL query OpenSearch for actual document counts per index and populate `doc_count` fields.
4. THE MCP_Server SHALL include a validation script that checks a Unified_Manifest file against the schema and reports errors.
5. IF the validation script detects a Source_Entry with an invalid `source_type`, THEN THE validation script SHALL report the entry name and the invalid value.
6. IF the validation script detects a Source_Entry with a `collection_target` that does not map to a known OpenSearch index, THEN THE validation script SHALL report a warning.

### Requirement 8: Manifest File Location and Loading

**User Story:** As a developer, I want the unified manifest to be loadable from a configurable path with sensible defaults, so that both containerized and local development environments work without extra configuration.

#### Acceptance Criteria

1. THE MCP_Server SHALL load the Unified_Manifest from the path specified by the `MCP_UNIFIED_MANIFEST_PATH` environment variable when set.
2. WHEN `MCP_UNIFIED_MANIFEST_PATH` is not set, THE MCP_Server SHALL load the Unified_Manifest from `src/config/unified_manifest.json` within the server package.
3. IF the Unified_Manifest file does not exist at any candidate path, THEN THE MCP_Server SHALL fall back to loading the legacy `documentation_sources.json` and expose only URL sources.
4. WHEN the Unified_Manifest is loaded successfully, THE MCP_Server SHALL log the manifest version, total source count, and enabled source count at INFO level.
5. IF the Unified_Manifest fails JSON parsing, THEN THE MCP_Server SHALL log an error and fall back to the legacy manifest without crashing.
