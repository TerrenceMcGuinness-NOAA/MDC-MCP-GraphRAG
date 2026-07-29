# Design Document

## Overview

Add two methods (`count_documents`, `sample_metadata`) to the ChromaDB vector
adapter so the three observability tools (`get_knowledge_base_status`,
`check_knowledge_integrity`, `list_all_sources --include_gaps`) report real
data on COTS instead of false zeros/SKIPs. The OpenSearch adapter already has
these; this is parity.

## Changes

### 1. ChromaDB adapter (`src/data/chromadb_adapter.py`)

```python
def count_documents(self, collection: str) -> int:
    col = self._get_collection_or_none(collection)
    return col.count() if col else 0

def sample_metadata(self, collection: str, limit: int = 50) -> list[dict]:
    col = self._get_collection_or_none(collection)
    if col is None:
        return []
    result = col.get(limit=limit, include=["metadatas", "documents"])
    return result.get("metadatas") or []
```

Both methods are non-raising; missing/empty collections return 0 / `[]`.

### 2. `UnifiedDataAccess` / `VectorDBProtocol`

Ensure the protocol declares `count_documents` and `sample_metadata` so both
adapters fulfill the same interface. The OpenSearch adapter already has
equivalent methods (`_count_index`, `_sample_docs`); wire them under the
canonical names if not already aligned.

### 3. Tool consumers

| Tool | Current (COTS) | After |
|---|---|---|
| `get_knowledge_base_status` | Hard-wires OpenSearch `_count` → 0 on COTS | Calls `backend.vector.count_documents(coll)` per collection |
| `check_knowledge_integrity` | SKIPs Path/Stale when no sampler | Calls `backend.vector.sample_metadata(coll, 50)` |
| `list_all_sources --include_gaps` | "Actual" side assumes OpenSearch → 0 | Dispatches through `backend.vector.count_documents(coll)` |

### 4. Contract test

A parametrized unit test (pytest) with a mock ChromaDB collection fixture and
a mock OpenSearch index fixture. Asserts:
- `count_documents("existing")` → int > 0
- `count_documents("missing")` → 0
- `sample_metadata("existing", 5)` → list of 5 dicts with `file_path` key
- `sample_metadata("missing", 5)` → `[]`

## Testing

- Unit: contract test (both adapters), `get_knowledge_base_status` with mocked
  3-collection adapter, integrity check with mocked sampler returning docs.
- Functional (COTS): `get_knowledge_base_status` → `Total Documents > 0`,
  `[OK] Healthy`; `check_knowledge_integrity` → no SKIPs (except Coverage Gap
  which is Phase 72); `list_all_sources --include_gaps` → coverage > 0%.
- Regression (AWS): output byte-identical modulo timestamp.
