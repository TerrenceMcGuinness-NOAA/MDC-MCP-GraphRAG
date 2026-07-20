# Implementation Plan: COTS Backend Observability Parity

## Overview

Add `count_documents` and `sample_metadata` to the ChromaDB adapter; wire three
tools through the backend-abstract interface so they report real data on COTS.

## Tasks

- [ ] 1. ChromaDB adapter — add `count_documents` and `sample_metadata`
  - [ ] 1.1 Implement `count_documents(collection) -> int` (ChromaDB `collection.count()`; 0 on missing)
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ] 1.2 Implement `sample_metadata(collection, limit=50) -> list[dict]` (ChromaDB `collection.get()`; `[]` on missing/empty)
    - _Requirements: 2.1, 2.2, 2.3_
  - [ ] 1.3 Ensure `VectorDBProtocol` declares both methods; align OpenSearch adapter's existing equivalents under the canonical names
    - _Requirements: 1.3_

- [ ] 2. Wire `get_knowledge_base_status` through backend-abstract count
  - [ ] 2.1 Replace the hard-wired OpenSearch `_count` path with `backend.vector.count_documents(coll)` iteration
    - _Requirements: 3.1, 3.2, 3.3_
  - [ ] 2.2 Verify AWS output unchanged (byte-identical modulo timestamp)
    - _Requirements: 3.4_

- [ ] 3. Wire `check_knowledge_integrity` to use the sampler
  - [ ] 3.1 Replace the `[SKIP] adapter does not expose a metadata sampler` branches with calls to `backend.vector.sample_metadata(coll, 50)`
    - _Requirements: 4.1, 4.2_
  - [ ] 3.2 Verify AWS output unchanged
    - _Requirements: 4.3_

- [ ] 4. Wire `list_all_sources --include_gaps` backend-agnostic actuals
  - [ ] 4.1 Gap detector "actual" side dispatches through `backend.vector.count_documents(coll)` instead of assuming OpenSearch
    - _Requirements: 5.1, 5.2_
  - [ ] 4.2 Verify AWS output unchanged
    - _Requirements: 5.3_

- [ ] 5. Contract test
  - [ ] 5.1 Parametrized unit test: both adapters pass `count_documents` (existing → int > 0, missing → 0) and `sample_metadata` (existing → list[dict], missing → `[]`)
    - _Requirements: 6.1, 6.2_

- [ ] 6. Functional verification (COTS)
  - [ ] 6.1 `get_knowledge_base_status` → `Total Documents > 0`, status `[OK] Healthy`
  - [ ] 6.2 `check_knowledge_integrity` → Path Consistency and Stale Embeddings execute (no SKIP except Coverage Gap — Phase 72)
  - [ ] 6.3 `list_all_sources --include_gaps` → coverage > 0% for collections with documents

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
