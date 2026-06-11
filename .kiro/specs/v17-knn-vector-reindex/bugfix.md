# Bugfix Requirements Document

## Introduction

The v17 tenant's three OpenSearch indices (`gw_v17_mdc-code-titan1024`, `gw_v17_mdc-workflow-docs-titan1024`, `gw_v17_mdc-jjobs-titan1024`) were created via auto-indexing during bulk ingestion without the correct index mapping. The `embedding` field was dynamically mapped as `float` instead of `knn_vector`, which causes all k-NN similarity searches to fail with `RequestError(400, ... Field 'embedding' is not knn_vector type)`. The indices contain ~57,000 correctly embedded documents, but no semantic search can execute against them. This bug was exposed after the `opensearch-tenant-resolution-fix` [8.36.2] corrected index resolution order, allowing queries to actually reach the v17 indices where the mapping error surfaces.

The root cause is that `create-opensearch-indices.js` only creates unprefixed `mdc-*-<model>` indices (no `--prefix` parameter), so tenant-prefixed indices were never pre-created with the correct `knn_vector` mapping. When bulk ingestion ran, OpenSearch auto-created the `gw_v17_mdc-*` indices with dynamic mapping that maps float arrays as `float` type. OpenSearch does not support changing a field's mapping type on a live index — the only fix is delete + recreate + re-ingest.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a k-NN similarity search is executed against any `gw_v17_mdc-*` index (e.g. via `find_similar_code(tenant_id="gw_v17")`) THEN the system returns `RequestError(400, ... Field 'embedding' is not knn_vector type)` and no results

1.2 WHEN `create-opensearch-indices.js` is invoked with `--model titan1024` THEN the system only creates unprefixed indices (e.g. `mdc-code-context-titan1024`) and provides no mechanism to create tenant-prefixed indices

1.3 WHEN a bulk ingestion writes documents to a non-existent tenant-prefixed index (e.g. `gw_v17_mdc-code-titan1024`) THEN OpenSearch auto-creates the index with dynamic mapping that maps the `embedding` field as `float` type instead of `knn_vector`

1.4 WHEN the v17 index `gw_v17_mdc-code-titan1024` is queried via `_mapping/field/embedding` THEN the mapping shows `type: float` instead of `type: knn_vector` with HNSW/nmslib/cosinesimil parameters

### Expected Behavior (Correct)

2.1 WHEN a k-NN similarity search is executed against any `gw_v17_mdc-*` index THEN the system SHALL return ranked results based on cosine similarity without errors

2.2 WHEN `create-opensearch-indices.js` is invoked with `--prefix gw_v17_ --model titan1024` THEN the system SHALL create tenant-prefixed indices (e.g. `gw_v17_mdc-code-context-titan1024`) with the correct `knn_vector` mapping (HNSW, nmslib, cosinesimil, 1024-dim)

2.3 WHEN the v17 indices are recreated with the correct mapping and documents are re-ingested THEN the `embedding` field SHALL be mapped as `knn_vector` with dimension 1024, HNSW method, nmslib engine, and cosinesimil space type

2.4 WHEN the recreated index `gw_v17_mdc-code-context-titan1024` is queried via `_mapping/field/embedding` THEN the mapping SHALL show `type: knn_vector` with the full HNSW parameters

2.5 WHEN the fix is applied THEN the index SHALL be named `gw_v17_mdc-code-context-titan1024` directly (matching production naming convention) and the old alias pointing from `gw_v17_mdc-code-context-titan1024` to `gw_v17_mdc-code-titan1024` SHALL be removed

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a k-NN similarity search is executed against default-tenant (gw) indices (e.g. `mdc-code-context-titan1024`) THEN the system SHALL CONTINUE TO return ranked results without errors

3.2 WHEN `create-opensearch-indices.js` is invoked without a `--prefix` parameter THEN the system SHALL CONTINUE TO create unprefixed indices with the same mapping as before

3.3 WHEN bulk ingestion writes documents to existing correctly-mapped indices (gw default) THEN the system SHALL CONTINUE TO index documents with their embeddings stored as `knn_vector` type

3.4 WHEN any other tenant's indices (e.g. `gw_sfs_*`, `gw_jedi_gfs_*`) are queried THEN the system SHALL CONTINUE TO behave as before (no side effects from the v17 fix)

3.5 WHEN the destructive operations (index deletion, recreation) are invoked THEN the system SHALL require explicit operator confirmation before proceeding and SHALL NOT execute automatically

3.6 WHEN the re-ingestion runs THEN the system SHALL use the existing ingestion scripts (`ingest_documentation_v8.py`, `ingest_code_v8.py`, `ingest_jjobs_v8.py`) without any code modifications to those scripts

---

## Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type OpenSearchQuery
  OUTPUT: boolean
  
  // Returns true when the query targets a v17 index whose embedding field
  // was auto-mapped as float instead of knn_vector
  RETURN X.index STARTS WITH "gw_v17_mdc-" 
     AND X.index.mapping("embedding").type = "float"
     AND X.query_type = "knn"
END FUNCTION
```

```pascal
// Property: Fix Checking — v17 k-NN search works after reindex
FOR ALL X WHERE isBugCondition(X) DO
  result ← knn_search'(X)
  ASSERT result.status_code ≠ 400
     AND result.hits.length > 0
     AND result.hits ARE ranked by cosine similarity
END FOR
```

```pascal
// Property: Preservation Checking — gw (default) indices unaffected
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT knn_search(X) = knn_search'(X)
END FOR
```
