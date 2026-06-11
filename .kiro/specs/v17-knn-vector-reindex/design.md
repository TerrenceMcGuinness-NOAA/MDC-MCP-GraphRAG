# v17 k-NN Vector Reindex — Bugfix Design

## Overview

The three `gw_v17_mdc-*` OpenSearch indices were auto-created during bulk ingestion without the correct `knn_vector` mapping — the `embedding` field was dynamically mapped as `float`, causing all k-NN similarity searches to fail with `RequestError(400, ... Field 'embedding' is not knn_vector type)`. OpenSearch does not support changing a field's type on a live index, so the fix is: delete the broken indices, recreate them with the correct mapping (using an enhanced `create-opensearch-indices.js` that accepts a `--prefix` parameter), and re-ingest all ~57,000 documents.

This is primarily an **ops/data-fix spec** with a single, minimal code change (adding `--prefix` to the index creation script). The majority of work is gated operator steps: deletion of broken indices, recreation, and re-ingestion using existing scripts.

## Glossary

- **Bug_Condition (C)**: A k-NN query targets a `gw_v17_mdc-*` index whose `embedding` field is mapped as `float` instead of `knn_vector` — the query always 400s.
- **Property (P)**: After reindex, k-NN queries against `gw_v17_mdc-*-titan1024` return HTTP 200 with ranked cosine-similarity hits.
- **Preservation**: Default-tenant (`gw`) indices (`mdc-*-titan1024`) remain completely untouched — same mapping, same documents, same query results.
- **`create-opensearch-indices.js`**: The script in `mcp_server_node/scripts/` that creates OpenSearch indices with correct `knn_vector` mappings. Currently only creates unprefixed indices.
- **`--prefix`**: The new optional CLI argument that prepends a string to each generated index name, enabling tenant-prefixed index creation.
- **Dynamic mapping**: OpenSearch's auto-creation of index mappings when documents are indexed into a non-existent index — maps float arrays as `float` type, not `knn_vector`.

## Bug Details

### Bug Condition

The bug manifests when any k-NN similarity search targets the v17 tenant's indices. The `embedding` field was dynamically mapped as `float` (due to auto-index creation during bulk ingestion) instead of `knn_vector` with HNSW/nmslib/cosinesimil parameters. OpenSearch's k-NN plugin requires the explicit `knn_vector` type to execute approximate nearest-neighbor queries.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type OpenSearchQuery
  OUTPUT: boolean
  
  RETURN input.index STARTS WITH "gw_v17_mdc-"
         AND input.index.mapping("embedding").type = "float"
         AND input.query_type = "knn"
END FUNCTION
```

### Examples

- `find_similar_code(code_or_symbol="setuprad", tenant_id="gw_v17")` → `RequestError(400, Field 'embedding' is not knn_vector type)` (expected: ranked code hits)
- `search_documentation(query="GEMPAK", tenant_id="gw_v17")` → 400 error on the k-NN portion of the hybrid query (expected: document hits with similarity scores)
- `GET gw_v17_mdc-code-titan1024/_mapping/field/embedding` → `{"type": "float"}` (expected: `{"type": "knn_vector", "dimension": 1024, ...}`)
- `GET mdc-code-context-titan1024/_mapping/field/embedding` → correctly shows `knn_vector` (default tenant unaffected — this is the preservation baseline)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Default-tenant (`gw`) indices (`mdc-code-context-titan1024`, `mdc-workflow-docs-titan1024`, `mdc-jjobs-titan1024`, etc.) must retain their existing mapping, document count, and query behavior
- `create-opensearch-indices.js` invoked without `--prefix` must continue to create unprefixed indices identically to current behavior
- Other tenants' indices (`gw_sfs_*`, `gw_jedi_gfs_*`, `gw_gefs_v12_*`) must not be affected
- Existing ingestion scripts (`ingest_documentation_v8.py`, `ingest_code_v8.py`, `ingest_jjobs_v8.py`) must not require any code modifications
- The `--model` flag behavior must remain unchanged

**Scope:**
All inputs that do NOT involve the `gw_v17_mdc-*` indices should be completely unaffected by this fix. This includes:
- Queries against the default `gw` tenant
- Queries against other non-default tenants
- The `create-opensearch-indices.js` script when invoked without `--prefix`
- All ingestion pipelines (no code changes to ingesters)

## Hypothesized Root Cause

Based on the bug description and code analysis, the root cause is confirmed (not hypothesized):

1. **Missing `--prefix` capability in `create-opensearch-indices.js`**: The script only generates index names as `${base}-${modelName}` (e.g., `mdc-code-context-titan1024`). There is no mechanism to prepend a tenant prefix. This meant tenant-prefixed indices could never be pre-created with the correct mapping.

2. **Auto-index creation during bulk ingestion**: When `ingest_code_v8.py --tenant gw_v17` ran, it wrote documents to `gw_v17_mdc-code-titan1024`. Since that index didn't exist, OpenSearch auto-created it with dynamic mapping. A float array is mapped as `float` type — not `knn_vector`.

3. **Immutable field type**: OpenSearch does not allow changing a field's mapping type on a live index. The only remedy is delete → recreate with correct mapping → re-ingest.

4. **Naming convention mismatch**: The original v17 code index was named `gw_v17_mdc-code-titan1024` (missing the `-context-` segment). The prior spec's Task 5 created an alias `gw_v17_mdc-code-context-titan1024 → gw_v17_mdc-code-titan1024` as a workaround, but the underlying mapping error remained. After this fix, the index will be named `gw_v17_mdc-code-context-titan1024` directly (matching production convention), eliminating the need for the alias.

## Correctness Properties

Property 1: Bug Condition - k-NN Queries Return Ranked Hits After Reindex

_For any_ k-NN query targeting a `gw_v17_mdc-*-titan1024` index after the reindex is complete, the query SHALL return HTTP 200 with a non-empty list of hits ranked by cosine similarity, with no `RequestError(400)`.

**Validates: Requirements 2.1, 2.3**

Property 2: Preservation - Default Tenant Indices Untouched

_For any_ query targeting the default-tenant (`gw`) indices (`mdc-*-titan1024`), the system SHALL produce exactly the same results as before the fix — same mapping, same document count, same query responses — with no side effects from the v17 reindex operations.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

Property 3: Mapping Verification - Correct knn_vector Configuration

_For any_ `gw_v17_mdc-*-titan1024` index created by `create-opensearch-indices.js --prefix gw_v17_ --model titan1024`, the `embedding` field mapping SHALL show `type: knn_vector` with `dimension: 1024`, `method.engine: nmslib`, `method.space_type: cosinesimil`, and `method.name: hnsw`.

**Validates: Requirements 2.2, 2.4**

## Fix Implementation

### Changes Required

**File**: `mcp_server_node/scripts/create-opensearch-indices.js`

**Change**: Add optional `--prefix <string>` CLI argument

**Specific Changes**:

1. **Parse `--prefix` from CLI args**: Add prefix extraction alongside the existing `--model` parsing. Default to empty string when not provided.
   ```javascript
   const prefixIdx = args.indexOf('--prefix');
   const prefix = prefixIdx !== -1 ? args[prefixIdx + 1] || '' : '';
   ```

2. **Prepend prefix to generated index names**: Change the index name construction from `${base}-${modelName}` to `${prefix}${base}-${modelName}`.
   ```javascript
   // Before: const index = `${base}-${modelName}`;
   const index = `${prefix}${base}-${modelName}`;
   ```

3. **Log the prefix in the info banner**: Add a line showing the active prefix so operators can confirm correct invocation.
   ```javascript
   console.log(`[INFO] Prefix: ${prefix || '(none)'}`);
   ```

4. **Update the script header doc comment**: Document the new `--prefix` flag in the usage section.
   ```
   * Usage:
   *   node scripts/create-opensearch-indices.js [--model <short_name|all>] [--prefix <string>]
   ```

5. **No other logic changes**: The same `indexBody(dimensions)` mapping factory, same idempotent skip-if-exists behavior, same error handling. The prefix is purely a name transformation.

### Operator Steps (Gated, Destructive)

These steps require explicit operator confirmation and must NOT execute automatically:

**Step 1 — Delete broken v17 indices:**
```bash
# Confirm current state first
curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-code-titan1024/_mapping/field/embedding" | jq .
# Should show type: float (confirming the bug)

# Delete the three broken indices
curl -XDELETE "$OPENSEARCH_ENDPOINT/gw_v17_mdc-code-titan1024"
curl -XDELETE "$OPENSEARCH_ENDPOINT/gw_v17_mdc-workflow-docs-titan1024"
curl -XDELETE "$OPENSEARCH_ENDPOINT/gw_v17_mdc-jjobs-titan1024"
```

**Step 2 — Remove the stale alias:**
```bash
# Remove alias created by opensearch-tenant-resolution-fix Task 5
curl -XPOST "$OPENSEARCH_ENDPOINT/_aliases" -H 'Content-Type: application/json' -d '{
  "actions": [{"remove": {"index": "gw_v17_mdc-code-titan1024", "alias": "gw_v17_mdc-code-context-titan1024"}}]
}'
```

**Step 3 — Recreate indices with correct mapping:**
```bash
node mcp_server_node/scripts/create-opensearch-indices.js --model titan1024 --prefix gw_v17_
# Expected output:
# [INFO] Models: titan1024
# [INFO] Prefix: gw_v17_
# [INFO] Base indices: 5
# [INFO] Total indices to ensure: 5
# [OK]    gw_v17_mdc-code-context-titan1024 — created (1024-dim)
# [OK]    gw_v17_mdc-workflow-docs-titan1024 — created (1024-dim)
# [OK]    gw_v17_mdc-jjobs-titan1024 — created (1024-dim)
# [OK]    gw_v17_mdc-community-summaries-titan1024 — created (1024-dim)
# [OK]    gw_v17_mdc-ee2-standards-titan1024 — created (1024-dim)
```

**Step 4 — Verify mapping:**
```bash
curl -s "$OPENSEARCH_ENDPOINT/gw_v17_mdc-code-context-titan1024/_mapping/field/embedding" | jq .
# Must show: type: knn_vector, dimension: 1024, method.engine: nmslib, method.space_type: cosinesimil
```

**Step 5 — Re-ingest (three collections):**
```bash
# Documentation (~28,458 docs, ~2h)
DB_BACKEND=aws OPENSEARCH_ENDPOINT=$OPENSEARCH_ENDPOINT AWS_REGION=us-east-1 MCP_EMBEDDING_PROFILE=titan1024 \
  python3.12 mcp_server_python/scripts/ingest_documentation_v8.py --tenant gw_v17 --model titan1024

# Code (~28,559 docs, ~3h)
DB_BACKEND=aws OPENSEARCH_ENDPOINT=$OPENSEARCH_ENDPOINT AWS_REGION=us-east-1 MCP_EMBEDDING_PROFILE=titan1024 \
  python3.12 mcp_server_python/scripts/ingest_code_v8.py --tenant gw_v17 --model titan1024

# J-Jobs (~92 docs, ~5min)
DB_BACKEND=aws OPENSEARCH_ENDPOINT=$OPENSEARCH_ENDPOINT AWS_REGION=us-east-1 MCP_EMBEDDING_PROFILE=titan1024 \
  python3.12 mcp_server_python/scripts/ingest_jjobs_v8.py --tenant gw_v17 --model titan1024
```

### Naming Convention Alignment

After the fix:
- The v17 code index is named `gw_v17_mdc-code-context-titan1024` (matching production convention `${prefix}${base}-${model}` where base is `mdc-code-context`)
- The old `gw_v17_mdc-code-titan1024` index and its alias are both deleted
- No alias is needed — the index name directly matches what the tenant resolver expects

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, confirm the bug exists on unfixed indices, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm the root cause (dynamic `float` mapping on v17 indices).

**Test Plan**: Query the live v17 indices to observe the 400 error and inspect the mapping directly.

**Test Cases**:
1. **k-NN query test**: `find_similar_code(code_or_symbol="setuprad", tenant_id="gw_v17")` → observe 400 error (will fail on unfixed indices)
2. **Hybrid search test**: `search_documentation(query="GEMPAK", tenant_id="gw_v17")` → observe 400 on k-NN component (will fail on unfixed indices)
3. **Mapping inspection**: `GET gw_v17_mdc-code-titan1024/_mapping/field/embedding` → confirm `type: float` (will show wrong type on unfixed indices)
4. **Default tenant baseline**: `find_similar_code(code_or_symbol="setuprad")` → confirm works fine (establishes preservation baseline)

**Expected Counterexamples**:
- All k-NN queries against `gw_v17_mdc-*` return `RequestError(400, Field 'embedding' is not knn_vector type)`
- Confirmed cause: dynamic mapping applied `float` type to the embedding field arrays

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed system produces the expected behavior.

**Pseudocode:**
```
FOR ALL query WHERE isBugCondition(query) DO
  // After reindex with correct knn_vector mapping
  result := knn_search_fixed(query)
  ASSERT result.status_code = 200
  ASSERT result.hits.length > 0
  ASSERT result.hits ARE ranked by cosine similarity
END FOR
```

**Live validation commands:**
```bash
# Verify k-NN search works
find_similar_code(code_or_symbol="setuprad", tenant_id="gw_v17")  # → ranked hits

# Verify documentation search works
search_documentation(query="GEMPAK", tenant_id="gw_v17")  # → document hits

# Verify knowledge base status shows correct counts
get_knowledge_base_status(tenant_id="gw_v17")  # → three indices with doc counts
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the system produces the same result as before.

**Pseudocode:**
```
FOR ALL query WHERE NOT isBugCondition(query) DO
  ASSERT knn_search_before(query) = knn_search_after(query)
END FOR
```

**Testing Approach**: Manual verification is appropriate for preservation checking in this spec because:
- The fix only touches v17 indices (operator-gated delete/recreate)
- Default-tenant indices are never modified, deleted, or recreated
- The code change (`--prefix`) has no effect when `--prefix` is not passed
- The idempotent skip-if-exists behavior prevents accidental recreation of existing indices

**Test Cases**:
1. **Default tenant search preservation**: `find_similar_code(code_or_symbol="setuprad")` returns same results before and after
2. **Default tenant doc search preservation**: `search_documentation(query="GEMPAK")` returns same results before and after  
3. **Default tenant index mapping preservation**: `GET mdc-code-context-titan1024/_mapping/field/embedding` shows unchanged `knn_vector` mapping
4. **Script backward compatibility**: `node create-opensearch-indices.js --model titan1024` (no prefix) still creates unprefixed indices with same behavior

### Unit Tests

- Test `--prefix` flag parsing: verify prefix is extracted from args correctly
- Test `--prefix` with empty/missing value: verify defaults to empty string
- Test index name generation: verify `${prefix}${base}-${modelName}` construction
- Test backward compatibility: verify no prefix produces same names as before
- Mock `client.indices.create` and verify the index name includes the prefix when `--prefix gw_v17_` is passed

### Property-Based Tests

- Generate random prefix strings (alphanumeric + underscore, 0-20 chars) and verify index names are constructed correctly
- Generate combinations of `--model` and `--prefix` flags and verify idempotent skip-if-exists behavior is preserved
- Verify that the mapping body (`indexBody(dimensions)`) is identical regardless of prefix value

### Integration Tests

- End-to-end: run `create-opensearch-indices.js --prefix gw_v17_ --model titan1024` against a test OpenSearch instance, then verify mapping via `_mapping` API
- Verify that re-running the same command skips all 5 indices (idempotent)
- Verify that `get_knowledge_base_status(tenant_id="gw_v17")` shows correct index names and doc counts after re-ingestion
