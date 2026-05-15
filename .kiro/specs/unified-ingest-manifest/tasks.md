# Implementation Plan: Unified Ingest Manifest

## Overview

This plan implements the Unified Ingest Manifest feature for the MDC MCP RAG Python server. The implementation extends the SPOT protocol from a URL-only `documentation_sources.json` to a unified manifest that registers all 7 source types. Work is organized into: data models → registry → loader → gap detector → MCP tools → CLI scripts → server integration → tests.

## Tasks

- [ ] 1. Create manifest package with data models
  - [ ] 1.1 Create `src/manifest/__init__.py` with package exports
    - Create the `mcp_server_python/src/manifest/` package directory
    - Define `__init__.py` exporting `ManifestRegistry`, `GapDetector`, `SourceEntry`, `SourceType`, `UnifiedManifest`
    - _Requirements: 1.1, 1.2, 1.10_

  - [ ] 1.2 Implement `src/manifest/models.py` with SourceType enum, SourceEntry, and UnifiedManifest dataclasses
    - Define `SourceType(str, Enum)` with all 7 values: `url_crawl`, `on_disk_submodule`, `code_parse`, `config_parse`, `standards`, `community_summary`, `jjob_docs`
    - Define frozen `SourceEntry` dataclass with common fields (`name`, `source_type`, `collection_target`, `embedding_profile`, `enabled`, `description`, `last_ingested`, `ingestion_script`, `doc_count`) and `type_fields: dict[str, Any]`
    - Define `UnifiedManifest` dataclass with `version`, `description`, `generated_at`, `sources`
    - Add `to_dict()` and `from_dict()` class methods for JSON serialization/deserialization
    - Validate type-specific required fields per source_type in `from_dict()` (url_crawl needs `url`, `crawl_type`, `max_pages`, `tier`; on_disk_submodule needs `local_path`, `file_patterns`, `parser`; etc.)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10_

  - [ ]* 1.3 Write property test for manifest round-trip fidelity
    - **Property 1: Manifest Round-Trip Fidelity**
    - Use Hypothesis to generate arbitrary `UnifiedManifest` instances, serialize to dict, deserialize back, and assert equality
    - Verify field ordering in JSON output is deterministic (sorted keys)
    - **Validates: Requirements 1.1, 1.2, 8.1**

- [ ] 2. Implement ManifestRegistry
  - [ ] 2.1 Implement `src/manifest/registry.py` with ManifestRegistry class
    - Implement `__init__(self, manifest: UnifiedManifest)` building `_by_name` index
    - Implement `load(cls, path: Path | None = None) -> ManifestRegistry` class method
    - Implement `get_sources(*, source_type, collection, enabled_only) -> list[SourceEntry]` with filter logic
    - Implement `get_url_sources() -> list[SourceEntry]` returning only `url_crawl` entries
    - Implement `get_legacy_format() -> dict[str, Any]` producing `documentation_sources.json`-compatible output
    - Implement `update_source(name, *, last_ingested, doc_count) -> None` for post-ingestion metadata
    - Implement `save(path: Path | None = None) -> None` persisting to JSON with sorted keys
    - Implement `version`, `total_sources`, `enabled_sources` properties
    - _Requirements: 1.11, 2.2, 2.4, 5.1, 5.2, 5.3, 5.4_

  - [ ]* 2.2 Write property test for filter completeness
    - **Property 3: Filter Completeness**
    - Use Hypothesis to generate manifests with mixed source types, verify `get_sources(source_type=X)` returns exactly entries where `entry.source_type == X` and `entry.enabled == True`
    - Assert no entries are dropped or duplicated
    - **Validates: Requirements 3.2, 3.3**

  - [ ]* 2.3 Write property test for legacy equivalence
    - **Property 2: Legacy Equivalence**
    - Use Hypothesis to generate `url_crawl` entries, verify `get_legacy_format()` output is structurally identical to `documentation_sources.json` format — same field names, value types, ordering
    - **Validates: Requirements 2.1, 2.3, 2.4**

  - [ ]* 2.4 Write unit tests for ManifestRegistry
    - Test `load()` from valid JSON with all source types
    - Test `get_sources()` with each filter combination (type, collection, enabled_only)
    - Test `get_url_sources()` returns only url_crawl entries
    - Test `update_source()` modifies in-memory state correctly
    - Test `save()` + `load()` round-trip preserves data
    - Test empty manifest (no sources) handled gracefully
    - Test `KeyError` raised for `update_source()` with unknown name
    - _Requirements: 2.2, 2.4, 5.4_

- [ ] 3. Implement manifest loader with fallback chain
  - [ ] 3.1 Implement `src/manifest/loader.py` with path resolution and fallback logic
    - Implement `resolve_manifest_path() -> Path | None` checking `MCP_UNIFIED_MANIFEST_PATH` env var → `src/config/unified_manifest.json` bundled path → `None`
    - Implement `load_manifest(path: Path | None = None) -> ManifestRegistry` with full fallback chain
    - Implement `_migrate_legacy(legacy_path: Path) -> UnifiedManifest` converting `documentation_sources.json` entries to `url_crawl` SourceEntries
    - Log manifest version, total source count, and enabled source count at INFO level on successful load
    - Log ERROR and fall back to legacy on JSON parse failure (no crash)
    - Log WARNING when falling back to legacy manifest
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 3.2 Write property test for fallback safety
    - **Property 5: Fallback Safety**
    - Use Hypothesis to generate malformed JSON strings, verify `load_manifest()` never raises, always returns a valid `ManifestRegistry` (possibly with legacy-only sources)
    - Verify WARNING is logged when falling back
    - **Validates: Requirements 8.3, 8.5**

  - [ ]* 3.3 Write unit tests for manifest loader
    - Test env var path takes precedence over bundled path
    - Test bundled path used when env var unset
    - Test legacy fallback when unified manifest file missing
    - Test malformed JSON triggers fallback + error log (no crash)
    - Test `_migrate_legacy()` produces valid UnifiedManifest with correct source_type
    - Test INFO log emitted with version/count on successful load
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement GapDetector
  - [ ] 5.1 Implement `src/manifest/gap_detector.py` with GapDetector and GapReport
    - Define `GapReport` dataclass with `collection`, `declared_count`, `actual_count`, `coverage_pct`, `stale_sources`, `never_ingested`, `status`
    - Implement `GapDetector` class with `COVERAGE_THRESHOLD = 0.90` and `STALE_DAYS = 30`
    - Implement `async detect(registry, vector_db) -> list[GapReport]` comparing declared vs actual counts per collection
    - Implement `async _get_actual_counts(vector_db) -> dict[str, int]` querying OpenSearch cat.indices
    - Report coverage gap when actual < 90% of declared sum for a collection
    - Report stale when `enabled=True` and `last_ingested` > 30 days old
    - Report never-ingested when `enabled=True` and `last_ingested` is None
    - Return empty list (no crash) when OpenSearch is unreachable
    - Produce per-collection summary with declared vs actual counts
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 5.2 Write property test for gap detection monotonicity
    - **Property 4: Gap Detection Monotonicity**
    - Use Hypothesis to generate manifests where actual_count >= declared_count for all collections, verify `detect()` returns zero gap reports with status "healthy"
    - **Validates: Requirements 6.1, 6.2**

  - [ ]* 5.3 Write unit tests for GapDetector
    - Test all collections at 100% coverage → no gaps reported
    - Test one collection at 85% → gap reported with correct status
    - Test source with `last_ingested` > 30 days → stale status
    - Test source with `last_ingested` = None → never-ingested status
    - Test OpenSearch unreachable → empty report, no crash
    - Test per-collection summary math (declared vs actual sums)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [ ] 6. Implement MCP tools
  - [ ] 6.1 Add `list_all_sources` tool to `src/tools/semantic_search.py`
    - Register new `list_all_sources` tool with parameters: `source_type`, `collection`, `format` (summary/detailed), `include_gaps`
    - Implement summary format: aggregated counts grouped by source type and collection
    - Implement detailed format: full SourceEntry metadata for each source
    - When `include_gaps=True`, call `GapDetector.detect()` and append gap report
    - Include actual document counts from OpenSearch alongside declared counts
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 6.5_

  - [ ] 6.2 Update `list_ingested_urls` to read from ManifestRegistry
    - Refactor internal implementation to call `registry.get_url_sources()` instead of reading `documentation_sources.json` directly
    - Preserve existing parameter interface (`format`, `source_filter`) unchanged
    - When `format=detailed`, append summary section showing non-URL source counts
    - Fall back to legacy file-based behavior if registry is None
    - _Requirements: 4.1, 4.3, 4.5_

  - [ ] 6.3 Update `get_ingested_urls_array` to read from ManifestRegistry
    - Refactor internal implementation to call `registry.get_url_sources()` instead of reading file
    - Preserve existing parameter interface (`include_failed`) unchanged
    - Return same JSON structure as current implementation
    - Fall back to legacy file-based behavior if registry is None
    - _Requirements: 4.2, 4.4_

  - [ ] 6.4 Update `register()` function signature to accept `manifest_registry` parameter
    - Add `manifest_registry: ManifestRegistry | None = None` keyword parameter to `register()`
    - Pass registry to tool closures for `list_all_sources`, `list_ingested_urls`, `get_ingested_urls_array`
    - Preserve `documentation_sources_path` parameter for fallback
    - _Requirements: 2.2, 4.1, 4.2_

  - [ ]* 6.5 Write unit tests for MCP tools
    - Test `list_all_sources` with no filters returns all enabled sources
    - Test `list_all_sources` with `source_type` filter returns correct subset
    - Test `list_all_sources` with `collection` filter returns correct subset
    - Test `list_all_sources` summary vs detailed format output
    - Test `list_all_sources` with `include_gaps=True` includes gap report
    - Test `list_ingested_urls` returns only url_crawl sources from registry
    - Test `list_ingested_urls` detailed format appends non-URL summary
    - Test `get_ingested_urls_array` returns legacy-compatible JSON structure
    - Test all tools gracefully handle `registry=None` (fallback mode)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Create CLI scripts
  - [ ] 8.1 Implement `scripts/generate_unified_manifest.py` bootstrap script
    - Scan `mcp_server_node/scripts/` for ingestion scripts and map each to a SourceEntry
    - Query OpenSearch for actual document counts per index to populate `doc_count` fields
    - Discover source types by analyzing ingestion script names and content patterns
    - Generate valid `unified_manifest.json` with all discovered sources
    - Support `--output` flag for custom output path (default: `src/config/unified_manifest.json`)
    - Support `--dry-run` flag to print manifest without writing
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ] 8.2 Implement `scripts/validate_manifest.py` validation script
    - Validate all required common fields present on every SourceEntry
    - Validate type-specific required fields per `source_type`
    - Validate `collection_target` resolves to a known OpenSearch index
    - Validate no duplicate `name` values
    - Validate `embedding_profile` is a registered profile
    - Report invalid `source_type` with entry name and invalid value
    - Report warning for unknown `collection_target`
    - Support `--manifest` flag for custom manifest path
    - Exit with non-zero code on validation errors
    - _Requirements: 7.4, 7.5, 7.6_

  - [ ]* 8.3 Write unit tests for validation script
    - Test valid manifest passes validation
    - Test missing required field reports error
    - Test invalid source_type reports entry name and value
    - Test unknown collection_target reports warning
    - Test duplicate name detection
    - _Requirements: 7.4, 7.5, 7.6_

- [ ] 9. Server boot integration and manifest file
  - [ ] 9.1 Create initial `src/config/unified_manifest.json` manifest file
    - Create the JSON file with `version: "9.0.0"`, `description`, `generated_at`
    - Include representative entries for each of the 7 source types based on current knowledge base state
    - Ensure all url_crawl entries match current `documentation_sources.json` content
    - _Requirements: 1.1, 1.2, 2.1, 2.3_

  - [ ] 9.2 Integrate ManifestRegistry loading into `src/mcp_server.py` boot sequence
    - Import `load_manifest` from `src.manifest.loader`
    - Call `load_manifest()` during server initialization
    - Pass resulting `ManifestRegistry` to `semantic_search.register(mcp, data, manifest_registry=registry)`
    - Ensure server boots successfully even if manifest loading fails (fallback)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 9.3 Write unit tests for server boot integration
    - Test server boots with valid unified manifest
    - Test server boots with missing manifest (fallback to legacy)
    - Test server boots with malformed manifest (fallback + error log)
    - Test registry is passed to semantic_search.register()
    - _Requirements: 8.3, 8.4, 8.5_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The project uses `pytest` with `hypothesis==6.152.2` for property-based testing
- Property tests go in `tests/properties/` following existing convention (`test_ggsr_props.py`, `test_sdd_session_props.py`)
- Unit tests go in `tests/unit/` following existing naming convention
- All new code lives under `mcp_server_python/` matching the Python server port structure

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "6.1", "6.4"] },
    { "id": 5, "tasks": ["6.2", "6.3"] },
    { "id": 6, "tasks": ["6.5", "8.1", "8.2"] },
    { "id": 7, "tasks": ["8.3", "9.1"] },
    { "id": 8, "tasks": ["9.2"] },
    { "id": 9, "tasks": ["9.3"] }
  ]
}
```
