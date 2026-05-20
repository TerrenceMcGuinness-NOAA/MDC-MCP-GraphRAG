# Requirements Document

## Introduction

The unified manifest system (`unified_manifest.json`) provides the operator view of knowledge-base health via the `list_all_sources` MCP tool. Three bugs render this view misleading: `last_ingested` is always null because no ingest script writes back to the manifest, the gap table `status` column always shows `missing` due to a key mismatch in the health-check response parsing, and `doc_count` values are static hand-entered numbers that drift from reality. This feature fixes all three bugs by adding a convenience writeback API, a standalone backfill script, and correcting the gap detector's response key handling.

## Glossary

- **Manifest_Registry**: The `ManifestRegistry` class in `mcp_server_python/src/manifest/registry.py` that provides the in-memory view of `unified_manifest.json` and exposes `update_source()` and `save()` methods.
- **Gap_Detector**: The `GapDetector` class in `mcp_server_python/src/manifest/gap_detector.py` that compares declared manifest sources against live OpenSearch index statistics.
- **Backfill_Script**: The standalone Python script `scripts/backfill_manifest_status.py` that queries OpenSearch for live document counts and writes them back to the manifest.
- **Unified_Manifest**: The JSON file `mcp_server_python/src/config/unified_manifest.json` that declares all ingest sources, their collection targets, document counts, and last-ingested timestamps.
- **OpenSearch_Adapter**: The vector database adapter that provides `health_check(deep=True)` returning per-index document counts.
- **Semantic_Search_Tool**: The `list_all_sources` MCP tool in `mcp_server_python/src/tools/semantic_search.py` that renders the gap detection table for operators.

## Requirements

### Requirement 1: Post-Ingest Writeback Convenience API

**User Story:** As a developer integrating ingest scripts, I want a single-call convenience method on the Manifest_Registry that stamps `last_ingested` and `doc_count` together, so that ingest scripts can write back status without manually constructing ISO timestamps.

#### Acceptance Criteria

1. THE Manifest_Registry SHALL expose an `update_source_from_ingest` method that accepts a source name and a document count as parameters.
2. WHEN `update_source_from_ingest` is called, THE Manifest_Registry SHALL set the `last_ingested` field of the named source to the current UTC timestamp in ISO-8601 format.
3. WHEN `update_source_from_ingest` is called, THE Manifest_Registry SHALL set the `doc_count` field of the named source to the provided document count value.
4. IF `update_source_from_ingest` is called with a source name that does not exist in the manifest, THEN THE Manifest_Registry SHALL raise a `KeyError` with a message identifying the unknown source name.

### Requirement 2: Standalone Backfill Script

**User Story:** As an operator, I want a standalone script that queries OpenSearch for live document counts and writes them back to the manifest, so that I can populate `last_ingested` and `doc_count` for all sources without re-running every ingest pipeline.

#### Acceptance Criteria

1. THE Backfill_Script SHALL accept a `--manifest` argument specifying the path to the unified manifest JSON file.
2. THE Backfill_Script SHALL accept an `--opensearch-endpoint` argument specifying the OpenSearch cluster URL.
3. THE Backfill_Script SHALL accept a `--region` argument specifying the AWS region for request signing.
4. THE Backfill_Script SHALL accept a `--dry-run` flag that prints proposed changes without modifying the manifest file.
5. WHEN executed, THE Backfill_Script SHALL query the OpenSearch `_cat/indices?format=json` API to retrieve live document counts for all indices.
6. WHEN executed, THE Backfill_Script SHALL map each physical OpenSearch index back to its corresponding manifest source name using the `resolve_index` function.
7. WHEN a source has a matching OpenSearch index with a document count greater than zero, THE Backfill_Script SHALL call `update_source_from_ingest` with the live document count.
8. WHEN `--dry-run` is specified, THE Backfill_Script SHALL print the source name, matched index, and document count for each source without calling `save()`.
9. WHEN `--dry-run` is not specified, THE Backfill_Script SHALL call `registry.save()` to persist the updated manifest to disk.

### Requirement 3: Gap Detector Key Mismatch Fix

**User Story:** As an operator viewing the gap table, I want the `status` column to reflect actual OpenSearch data presence, so that I can distinguish between sources that are genuinely missing and sources that have been successfully ingested.

#### Acceptance Criteria

1. WHEN `_get_actual_counts` receives a health-check response, THE Gap_Detector SHALL log the top-level keys of the response dict at DEBUG level.
2. WHEN the `indices_detail` key is absent from the health-check response, THE Gap_Detector SHALL attempt to read the actual per-index counts from alternative key names returned by the OpenSearch_Adapter.
3. WHEN `_get_actual_counts` resolves to an empty dictionary despite a successful health check, THE Gap_Detector SHALL log a warning message identifying the available keys in the response.
4. THE Gap_Detector SHALL return a dictionary keyed by physical index name with integer document counts for all indices reported by the OpenSearch_Adapter.

### Requirement 4: Semantic Search Tool Fallback Handling

**User Story:** As an operator, I want the `list_all_sources` tool to inform me when gap detection data is unavailable due to empty actual counts, so that I do not mistake a data-retrieval failure for a healthy state.

#### Acceptance Criteria

1. WHEN `actual_counts` resolves to an empty dictionary after a successful health check call, THE Semantic_Search_Tool SHALL log a warning indicating that per-index counts could not be retrieved.
2. WHEN `actual_counts` is empty and `include_gaps` is true, THE Semantic_Search_Tool SHALL render a notice in the gap detection section stating that actual counts are unavailable.

### Requirement 5: Manifest Document Count Accuracy

**User Story:** As an operator, I want the `doc_count` field in the manifest to reflect live OpenSearch data, so that the gap table's declared-vs-actual comparison is meaningful.

#### Acceptance Criteria

1. WHEN the Backfill_Script updates a source, THE Backfill_Script SHALL set `doc_count` to the live document count retrieved from OpenSearch for that source's physical index.
2. WHEN the Backfill_Script completes without `--dry-run`, THE Unified_Manifest SHALL contain `doc_count` values that match the live OpenSearch counts within a 5% tolerance for all sources with active indices.
3. WHEN the Backfill_Script completes without `--dry-run`, THE Unified_Manifest SHALL contain non-null `last_ingested` timestamps for all sources whose corresponding OpenSearch index has a document count greater than zero.
