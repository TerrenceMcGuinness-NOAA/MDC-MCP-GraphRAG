# Implementation Plan: Backend-Agnostic Refactor

## Overview

Refactor the Python MCP server's wiring code to remove AWS-specific assumptions above the protocol layer. Adds a backend registry pattern, a typed `HealthReport` dataclass, and a `resolve_collection` method on adapters. After this refactor, adding a new backend (e.g. ChromaDB+Neo4j for Parallel Works) is a single-file registration with no changes to the selector, gap detector, or any of the 51 tool modules.

**Branching**: Implementation happens on `feature/backend-agnostic-refactor`. Spec lives on `develop_aws`. Sync via `git merge develop_aws` periodically.

## Tasks

- [ ] 1. Add `HealthReport` dataclass and protocol method signatures
  - [ ] 1.1 Add `HealthReport` dataclass to `mcp_server_python/src/data/protocols.py`
    - Fields: `status` (Literal), `connected` (bool), `collections` (dict[str, int]), `metrics` (dict[str, Any]), `error` (str | None)
    - Add `HealthStatus` Literal type alias
    - _Requirements: 3.1_

  - [ ] 1.2 Add `resolve_collection(logical_name: str) -> str` to `VectorDBProtocol`
    - Document contract: passthrough on unmapped names
    - _Requirements: 2.1, 2.5_

  - [ ] 1.3 Update `health_check()` signatures on both protocols to return `HealthReport`
    - Update docstrings to describe the logical-name contract
    - _Requirements: 3.2, 3.3_

- [ ] 2. Implement `BackendBuilder` and registry in `backend_selector.py`
  - [ ] 2.1 Add `BackendBuilder` ABC with `build(config) -> tuple[VectorDBProtocol | None, GraphDBProtocol | None]`
    - _Requirements: 1.1_

  - [ ] 2.2 Add `BACKEND_REGISTRY` dict, `register_backend()`, and `list_registered_backends()` functions
    - `register_backend` is idempotent (re-registering replaces)
    - _Requirements: 1.2, 1.6_

  - [ ] 2.3 Implement `AwsBackendBuilder` and register `"aws"` at module load
    - Wraps existing `_build_vector_db()` + `_build_graph_db()`
    - _Requirements: 1.3_

  - [ ] 2.4 Refactor `create_data_access()` to use registry lookup
    - Preserve test-injection path (vector_db= / graph_db= kwargs)
    - Update error message for unknown backend to list registered names
    - _Requirements: 1.4, 1.5_

- [ ] 3. Update `OpenSearchAdapter` to implement new protocol surface
  - [ ] 3.1 Add `resolve_collection()` method using existing `aws_config.PRODUCTION_INDICES_BY_PROFILE`
    - _Requirements: 2.2_

  - [ ] 3.2 Refactor `health_check()` to return `HealthReport` with logical collection names
    - Build reverse map from physical index name → logical collection
    - Populate `HealthReport.collections` using logical names
    - Move backend-specific extras (cluster_status, queries_executed) into `metrics`
    - _Requirements: 3.4_

  - [ ] 3.3 Resolve `embedding_profile == "default"` to `"titan1024"` internally
    - Adapter handles the "default" sentinel; ServerConfig stays generic
    - _Requirements: 4.2, 4.4_

- [ ] 4. Update `NeptuneAdapter` to implement new protocol surface
  - [ ] 4.1 Refactor `health_check()` to return `HealthReport`
    - `collections` field empty (graph backend); populate `metrics` with nodes_total, relationships_total, per-label counts
    - _Requirements: 3.5_

- [ ] 5. Checkpoint — Verify protocol changes compile and existing tests pass
  - Run `python3.12 -m pytest tests/unit/ -q --tb=short`
  - All 752 tests should pass with the new dataclass + protocol method signatures
  - _Requirements: 8.1_

- [ ] 6. Update `ServerConfig` and `load_config()` for explicit backend selection
  - [ ] 6.1 Change `db_backend` default from `"aws"` to empty string in `ServerConfig`
    - _Requirements: 5.1_

  - [ ] 6.2 Change `embedding_profile` default from `"titan1024"` to `"default"`
    - _Requirements: 4.1_

  - [ ] 6.3 Update `load_config()` to raise `ConfigError` when `DB_BACKEND` is unset/empty
    - Error message lists registered backends from `list_registered_backends()`
    - Hint that `DB_BACKEND=aws` selects the AWS backend
    - _Requirements: 5.2, 5.3_

- [ ] 7. Update consumers to use new protocol surface
  - [ ] 7.1 Refactor `mcp_server_python/src/manifest/gap_detector.py`
    - Remove `from src.config.aws_config import resolve_index` import
    - Replace `_get_actual_counts()` to consume `HealthReport.collections` directly
    - Replace `_lookup_actual_count()` with direct dict lookup
    - _Requirements: 2.3, 3.6, 7.1_

  - [ ] 7.2 Refactor `mcp_server_python/src/tools/semantic_search.py`
    - Remove any `aws_config` imports
    - Use `vector_db.resolve_collection()` where physical names were needed
    - Update `_tool_get_knowledge_base_status` to consume `HealthReport`
    - _Requirements: 2.4, 7.1, 7.4_

  - [ ] 7.3 Verify no other files in `src/tools/` import from `aws_config.py`
    - grep search for `aws_config` across `src/tools/` — should return zero hits
    - _Requirements: 7.1_

- [ ] 8. Register Mock backend in test fixtures
  - [ ] 8.1 Add `MockBackendBuilder` to `tests/conftest.py`
    - Constructs `MockVectorDB` + `MockGraphDB` from any ServerConfig (ignoring endpoints)
    - Register as `"mock"` at conftest module load
    - _Requirements: 6.1, 6.2, 6.4_

  - [ ] 8.2 Update `MockVectorDB.resolve_collection()` to mirror OpenSearchAdapter shape
    - Add a small logical→physical mapping table for cross-backend test parity
    - _Requirements: 6.5_

- [ ] 9. Add new tests for the registry pattern
  - [ ] 9.1 Create `tests/unit/test_backend_registry.py`
    - Test: register a `"foo"` backend with stub builder, verify `create_data_access` routes to it
    - Test: setting `DB_BACKEND=unknown` raises `UnsupportedBackendError` with registered backends in message
    - Test: setting `DB_BACKEND=` (empty) raises `ConfigError` with registered backends in message
    - Test: `register_backend()` is idempotent (re-registering replaces)
    - Test: `register_backend("", builder)` raises ValueError
    - _Requirements: 8.4, 8.5_

  - [ ] 9.2 Add HealthReport-specific test to `tests/unit/test_data_layer.py`
    - Test: `OpenSearchAdapter.health_check()` returns `HealthReport` with logical names
    - Test: passthrough behavior for unmapped collection names
    - _Requirements: 3.4, 2.5_

- [ ] 10. Checkpoint — Run full test suite, verify 0 failures
  - `python3.12 -m pytest tests/unit/ -v --tb=short`
  - All 752 existing tests + new registry tests must pass
  - Run grep verification: `grep -r "aws_config" mcp_server_python/src/tools/` returns nothing
  - _Requirements: 7.1, 8.1_

- [ ] 11. Update documentation
  - [ ] 11.1 Update module docstring of `backend_selector.py`
    - Describe registry pattern, include code example for registering a new backend
    - _Requirements: 9.1, 9.4_

  - [ ] 11.2 Update module docstring of `protocols.py`
    - Describe `HealthReport` shape and `resolve_collection` contract
    - _Requirements: 9.2_

  - [ ] 11.3 Add one-paragraph backend-agnostic design summary to `.kiro/steering/01-architecture-context.md`
    - _Requirements: 9.3_

- [ ] 12. Final checkpoint — Verify end-to-end on AgentCore
  - Build new image with refactored code
  - Deploy to AgentCore runtime as `python-all-tools-v6`
  - Smoke-test `mcp_health_check`, `search_documentation`, `get_knowledge_base_status`
  - Confirm output is identical to pre-refactor output
  - _Requirements: 7.5, 8.1_

## Notes

- This refactor does NOT implement Neo4jLegacyAdapter or ChromaDBLegacyAdapter. Those are deferred to a follow-on spec (`legacy-backend-adapters`) that drops them into the registry once this refactor is merged.
- The Mock backend registration in conftest demonstrates the registry pattern works without requiring real Neo4j/ChromaDB infrastructure during this refactor.
- Tool output stability (Property 4) is the most important regression check — if any of the 51 tools produces different output against the AWS backend after this refactor, something is wrong.
- The `_format_hits` field names (`_id`, `_source`) on the OpenSearch adapter remain — those are internal projection logic that doesn't leak to consumers.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4"] },
    { "id": 3, "tasks": ["3.1", "3.2", "3.3", "4.1"] },
    { "id": 4, "tasks": ["5"] },
    { "id": 5, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 6, "tasks": ["7.1", "7.2", "7.3"] },
    { "id": 7, "tasks": ["8.1", "8.2"] },
    { "id": 8, "tasks": ["9.1", "9.2"] },
    { "id": 9, "tasks": ["10"] },
    { "id": 10, "tasks": ["11.1", "11.2", "11.3"] },
    { "id": 11, "tasks": ["12"] }
  ]
}
```
