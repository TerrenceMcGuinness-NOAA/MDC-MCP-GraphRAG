# Implementation Plan: Manifest Status Writeback

## Overview

Fix three operational bugs in the unified manifest system: `last_ingested` always null, `doc_count` values stale, and gap detector key mismatch. Implementation adds a convenience writeback API on `ManifestRegistry`, a standalone backfill script querying OpenSearch for live counts, and corrects key-handling logic in `GapDetector._get_actual_counts()` and the `list_all_sources` tool.

## Tasks

- [x] 1. Add `update_source_from_ingest` convenience method to ManifestRegistry
  - [x] 1.1 Implement `update_source_from_ingest` method on `ManifestRegistry`
    - Add method to `mcp_server_python/src/manifest/registry.py`
    - Accepts `name: str` and `doc_count: int`
    - Sets `last_ingested` to `datetime.now(timezone.utc).isoformat()`
    - Delegates to existing `update_source()` with the computed timestamp and count
    - Raises `KeyError` with descriptive message for unknown source names
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Fix GapDetector key mismatch in `_get_actual_counts`
  - [x] 2.1 Add diagnostic logging and fallback key handling to `_get_actual_counts`
    - Modify `mcp_server_python/src/manifest/gap_detector.py`
    - Log top-level keys of health dict at DEBUG level
    - After checking `indices_detail`, add fallback loop over `index_details`, `index_counts`, `per_index_counts`
    - Log WARNING when result is empty despite a successful health check (status is `healthy` or `degraded`), listing available keys
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Add warning and notice to `list_all_sources` tool
  - [x] 3.1 Add empty actual_counts warning and gap notice to `_tool_list_all_sources`
    - Modify `mcp_server_python/src/tools/semantic_search.py`
    - After resolving `actual_counts` from health check, log WARNING if empty despite successful health response
    - In the gap detection section, when `include_gaps` is true and reports are empty with empty `actual_counts`, render a notice stating actual counts are unavailable
    - _Requirements: 4.1, 4.2_

- [ ] 4. Checkpoint - Verify registry and gap detector changes
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Create standalone backfill script
  - [ ] 5.1 Implement `scripts/backfill_manifest_status.py`
    - Create `mcp_server_python/scripts/backfill_manifest_status.py`
    - Parse CLI args: `--manifest`, `--opensearch-endpoint`, `--region`, `--dry-run`
    - Implement `fetch_live_counts()` using `requests` + `AWS4Auth` to query `_cat/indices?format=json`
    - Implement `build_reverse_index_map()` iterating registry sources and calling `resolve_index`
    - Main loop: for each live index with `doc_count > 0` that maps to a source, call `update_source_from_ingest`
    - In `--dry-run` mode, print proposed changes without calling `save()`
    - Without `--dry-run`, call `registry.save()` to persist
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 5.1, 5.2, 5.3_

- [ ] 6. Final checkpoint - Verify end-to-end
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- No new unit tests are required per user direction — existing tests cover the registry; the backfill script is tested via dry-run + live verification.
- The design uses Python throughout; no language selection needed.
- The backfill script reuses existing dependencies (`requests`, `requests_aws4auth`, `boto3`) already in the project.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["3.1"] },
    { "id": 2, "tasks": ["5.1"] }
  ]
}
```
