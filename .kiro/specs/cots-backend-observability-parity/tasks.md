# Implementation Plan: COTS Backend Observability Parity

## Overview

Add `count_documents` and `sample_metadata` to the ChromaDB adapter; wire three
tools through the backend-abstract interface so they report real data on COTS.

## Tasks

- [x] 1. ChromaDB adapter — add `count_documents` and `sample_metadata`
  - [x] 1.1 Implement `count_documents(collection) -> int` (ChromaDB `collection.count()`; 0 on missing)
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.2 Implement `sample_metadata(collection, limit=50) -> list[dict]` (ChromaDB `collection.get()`; `[]` on missing/empty; legacy `n` kept as alias)
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 1.3 Ensure `VectorDBProtocol` declares both methods; add the OpenSearch adapter's equivalents under the canonical names (`_count_index`/`_sample_docs` did not exist — added `count_documents` + `sample_metadata`, the latter relocating the scroll sampler)
    - _Requirements: 1.3_

- [x] 2. Wire `get_knowledge_base_status` through backend-abstract count
  - [x] 2.1 Confirmed already backend-abstract: `_render_vector_status_block` uses `health_check(deep=True)` → `_filter_indices_by_tenant`, which reads `collections_detail` (ChromaDB) or `indices_detail` (OpenSearch) — no hard-wired OpenSearch `_count`. Added R3 render tests (healthy-with-docs + fresh-tenant).
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 2.2 AWS output unchanged: OpenSearch `health_check`/`query`/`_format_hits` untouched; only additive methods added. (Byte-identical re-run needs the live AWS stack.)
    - _Requirements: 3.4_

- [x] 3. Wire `check_knowledge_integrity` to use the sampler
  - [x] 3.1 Path Consistency + Stale Embeddings already run via `_build_vector_sampler` → `sample_metadata`; both adapters now expose it (ChromaDB had it, OpenSearch added). No `[SKIP] ... metadata sampler` on COTS.
    - _Requirements: 4.1, 4.2_
  - [x] 3.2 AWS output unchanged: OpenSearch `sample_metadata` faithfully replicates the prior inline scroll sampler (same `random_score` query, same empty-metadata inclusion).
    - _Requirements: 4.3_

- [x] 4. Wire `list_all_sources --include_gaps` backend-agnostic actuals
  - [x] 4.1 `GapDetector._get_actual_counts` + `_tool_list_all_sources` now read `collections_detail` (ChromaDB) as well as `indices_detail`, and dispatch through `backend.vector.count_documents(collection)` when the health payload returns only names
    - _Requirements: 5.1, 5.2_
  - [x] 4.2 AWS output unchanged: `indices_detail` is still checked first; `collections_detail`/`count_documents` are additive fallbacks
    - _Requirements: 5.3_

- [x] 5. Contract test
  - [x] 5.1 Parametrized unit test: both adapters pass `count_documents` (existing → int > 0, missing → 0) and `sample_metadata` (existing → list[dict], missing → `[]`), + `n` alias + UnifiedDataAccess reachability
    - _Requirements: 6.1, 6.2_

- [x] 6. Functional verification (COTS) — verified read-only against the live ChromaDB on localhost:8080 (17 collections, 223,148 docs)
  - [x] 6.1 `get_knowledge_base_status` (gw scope) → `Total Documents: 220,538`, status `[OK] Healthy` (was the false `0` / `Unhealthy`)
  - [x] 6.2 `check_knowledge_integrity` → Path Consistency `[OK] 0/50` and Stale Embeddings `[WARN] 50/50 older than source` both EXECUTE (no `[SKIP]`); the WARN is a real, previously-masked finding
  - [x] 6.3 `list_all_sources --include_gaps` actuals → GapDetector resolves 17/17 collections with docs > 0 (coverage > 0%, was 0% across the board)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1", "5.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.2"] },
    { "id": 3, "tasks": ["6.1", "6.2", "6.3"] }
  ]
}
```
