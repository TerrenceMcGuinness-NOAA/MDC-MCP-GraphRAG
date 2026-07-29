# Requirements Document

## Introduction

This feature brings the ChromaDB (`DB_BACKEND=cots`) vector adapter to
**observability parity** with the OpenSearch (`DB_BACKEND=aws`) adapter. Three
MCP tools currently produce false/misleading results on COTS because the ChromaDB
adapter is missing two methods that the OpenSearch adapter implements:
`count_documents()` and `sample_metadata()`.

The result: `get_knowledge_base_status` reports `Total Documents: 0 [ERROR]
Unhealthy` despite 17 non-empty collections; `check_knowledge_integrity` skips
3/4 sub-checks; and `list_all_sources --include_gaps` reports 0% coverage across
the board. All three are false negatives that erode operator trust and mask real
problems.

This is Phase 70 from the SDD
(`sdd_framework/workflows/phase70_cots_backend_observability_parity.md`),
surfaced in the 2026-07-20 Docker MCP Gateway gap analysis.

## Requirements

### Requirement 1: ChromaDB `count_documents` method

**User Story:** As an operator on COTS, I want `get_knowledge_base_status` to
report the real document count so a healthy store isn't falsely reported as empty.

#### Acceptance Criteria

1. THE ChromaDB adapter SHALL expose `count_documents(collection: str) -> int`
   using ChromaDB's native `collection.count()` API.
2. WHEN the collection does not exist, THE method SHALL return `0` (not raise).
3. THE method SHALL be callable through the `UnifiedDataAccess` backend-abstract
   `vector.count(collection)` path so tools don't branch on backend type.

### Requirement 2: ChromaDB `sample_metadata` method

**User Story:** As an operator on COTS, I want integrity checks to actually run
instead of skipping with "adapter does not expose a metadata sampler."

#### Acceptance Criteria

1. THE ChromaDB adapter SHALL expose `sample_metadata(collection: str, limit:
   int = 50) -> list[dict]` using ChromaDB's `collection.get(limit=N,
   include=["metadatas", "documents"])`.
2. WHEN the collection does not exist or is empty, THE method SHALL return `[]`
   (not raise).
3. THE returned dicts SHALL include at minimum the fields that Path Consistency
   and Stale Embeddings checks read: `file_path` (or `source`), `ingested_at`
   (or equivalent timestamp).

### Requirement 3: `get_knowledge_base_status` uses backend-abstract count

**User Story:** As an operator, I want KB status to report correct counts
regardless of which backend is active.

#### Acceptance Criteria

1. THE `get_knowledge_base_status` tool SHALL iterate applicable collections
   via the active backend's `count_documents()` (not a hard-wired OpenSearch
   `_count` API call) and report the sum as `Total Documents`.
2. WHEN `Total Documents > 0`, THE status SHALL be `[OK] Healthy`.
3. WHEN a tenant has zero applicable collections (fresh tenant), THE status
   SHALL also be `[OK] Healthy` (not punish a fresh tenant).
4. ON `DB_BACKEND=aws`, THE tool's output SHALL be byte-identical (modulo
   timestamp) to the pre-change baseline (no regression).

### Requirement 4: `check_knowledge_integrity` runs all sub-checks on COTS

**User Story:** As an operator, I want all four integrity sub-checks to execute
so real problems aren't hidden behind SKIPs.

#### Acceptance Criteria

1. WHEN `sample_metadata` is available, THE Path Consistency and Stale
   Embeddings sub-checks SHALL execute (not SKIP).
2. THE sub-checks SHALL use `sample_metadata(collection, limit=50)` from the
   active backend adapter.
3. ON `DB_BACKEND=aws`, THE tool's output SHALL be unchanged (OpenSearch
   adapter already has the interface).

### Requirement 5: `list_all_sources --include_gaps` backend-agnostic actuals

**User Story:** As an operator, I want the gap detector to report real coverage
on COTS, not 0% across the board.

#### Acceptance Criteria

1. THE gap detector's "actual" document-count side SHALL dispatch through
   `backend.vector.count_documents(collection)` rather than assuming OpenSearch.
2. ON COTS with 17 non-empty collections, THE gap detector SHALL report
   coverage > 0% for each collection that has documents.
3. ON `DB_BACKEND=aws`, behavior SHALL be unchanged.

### Requirement 6: Backend adapter contract test

**User Story:** As a developer, I want a test that both adapters fulfill the
same contract so parity doesn't regress.

#### Acceptance Criteria

1. A new unit test SHALL assert that both the ChromaDB and OpenSearch adapters
   expose `count_documents(collection) -> int` and
   `sample_metadata(collection, limit) -> list[dict]` with the contracted
   return types and empty-collection behavior.
2. THE test SHALL be runnable in CI without a live store (mock/fixture).

### Requirement 7: Boundaries

#### Acceptance Criteria

1. THE feature SHALL NOT modify the OpenSearch adapter's existing behavior.
2. THE feature SHALL NOT address the Fortran coverage-gap path (Phase 72), the
   node-count scope documentation (Phase 73), or the nightly benchmark harness
   (Phase 71).
3. THE feature SHALL NOT auto-commit or auto-push (git policy 08).
