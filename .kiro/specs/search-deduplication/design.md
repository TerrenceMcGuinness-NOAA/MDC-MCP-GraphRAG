# Search Deduplication Bugfix Design

## Overview

The `search_documentation` tool returns duplicate search results because (1) the ESMF docs crawler followed multiple navigation paths to the same page, creating duplicate documents with different IDs in the `mdc-workflow-docs-titan1024` index, and (2) `OpenSearchAdapter.multi_collection_query()` performs no content-based deduplication after merging results. The fix is two-pronged: a query-time fingerprint filter in `multi_collection_query()` (immediate, ~5 lines), and an ingest-time deterministic ID scheme plus a one-time cleanup script to remove existing duplicates.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — a merged result set from `multi_collection_query()` contains two or more hits whose first 200 characters of `content` are identical
- **Property (P)**: The desired behavior — each returned result has a unique content fingerprint (first 200 chars), so no result budget is wasted on duplicates
- **Preservation**: Existing query behavior for non-duplicate result sets, mouse/keyboard interactions, latency characteristics, and unique content count in the index must remain unchanged
- **`multi_collection_query()`**: The method in `mcp_server_python/src/data/opensearch_adapter.py` that queries multiple OpenSearch collections concurrently, merges results by score, and returns top-k
- **Content Fingerprint**: The first 200 characters of a document's `content` field, used as a lightweight deduplication key
- **Deterministic ID**: A document ID derived from `SHA-256(source_name + first_500_chars_of_content)[:16]`, ensuring identical content always maps to the same ID regardless of crawl path or timing
- **`mdc-workflow-docs-titan1024`**: The primary OpenSearch index containing documentation chunks embedded with Titan Embed Text V2 (1024 dimensions)

## Bug Details

### Bug Condition

The bug manifests when a user queries documentation content that was indexed multiple times under different document IDs (due to the crawler following multiple navigation paths to the same page, or overlapping crawl runs). The `multi_collection_query()` method merges and sorts results purely by score without checking for content-identical hits, so all duplicate copies appear as separate results consuming the user's limited result budget (typically k=5–10).

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type SearchQuery (collections, query_text, k)
  OUTPUT: boolean
  
  results ← multi_collection_query(input.collections, input.query_text, k=input.k)
  fingerprints ← SET()
  FOR EACH r IN results DO
    fp ← r.content[0:200]
    IF fp IN fingerprints THEN
      RETURN true
    END IF
    fingerprints.ADD(fp)
  END FOR
  RETURN false
END FUNCTION
```

### Examples

- **ESMF coupling query**: Querying "ESMF coupling framework NUOPC component initialization" returns 4 identical text chunks from `esmf-user-guide` (all scoring 100%) plus 1 chunk from `nuopc-ref-pdf` — 3 of 5 result slots wasted on duplicates. Expected: 1 ESMF chunk + 4 distinct related results.
- **Overlapping crawl**: A page reachable via both `/docs/guide/coupling.html` and `/docs/reference/coupling.html` produces two documents with IDs `esmf-user-guide_abc123_0` and `esmf-user-guide_def456_0` but identical content. Expected: single document with deterministic ID.
- **Re-ingestion**: Running the crawler twice on the same source creates new sequential IDs for the same content. Expected: upsert (same ID → overwrite, no new document).
- **Non-duplicate query**: Querying "forecast model configuration" returns 5 topically related but textually distinct results — no deduplication needed, all results preserved as-is.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Queries that produce no content-identical results must return the same results in the same order with no latency change
- The total count of unique content in the index must not decrease after cleanup (only true duplicates are removed)
- Mouse clicks, other keyboard inputs, and all non-search interactions are unaffected
- The `query()` method (single-collection) behavior is unchanged — deduplication applies only at the `multi_collection_query()` merge layer
- The cleanup script with `--dry-run` leaves the index completely unmodified
- Running the cleanup script multiple times (idempotent) produces the same final state

**Scope:**
All inputs that do NOT produce content-identical hits in the merged result set are completely unaffected by the query-time fix. The ingest-time fix only changes ID generation for future crawls and does not alter existing documents (the cleanup script handles existing duplicates separately).

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **No query-time deduplication**: `multi_collection_query()` in `opensearch_adapter.py` (lines 213–240) merges results from multiple collections, sorts by score, and truncates to top-k — but never checks whether two hits contain the same text. This is the immediate cause of duplicate results reaching the user.

2. **Non-deterministic document IDs in legacy ingest**: The `ingest_documentation_v4_2_unified.py` script generates IDs as `f"{source_name}_{chunk['metadata'].get('content_hash', i)}"` — when `content_hash` is missing from metadata, it falls back to the sequential index `i`, meaning the same content crawled via different paths gets different IDs.

3. **Crawler path multiplicity**: The documentation crawler follows all navigation links, reaching the same page via multiple URL paths. Each path produces a separate document because the ID includes path-derived metadata rather than content-derived fingerprints.

4. **Overlapping crawl runs**: Re-running ingestion without clearing the index creates additional copies because the legacy ID scheme (`source_name_hash_index`) includes a chunk index that may differ between runs if chunking boundaries shift.

## Correctness Properties

Property 1: Bug Condition - No Duplicate Content in Search Results

_For any_ search query where the bug condition holds (merged results contain two or more hits with identical first-200-char content fingerprints), the fixed `multi_collection_query()` SHALL return only the highest-scoring copy of each unique fingerprint, ensuring all k returned results contain distinct content.

**Validates: Requirements 2.1, 2.2**

Property 2: Preservation - Non-Duplicate Queries Unchanged

_For any_ search query where the bug condition does NOT hold (all merged results have unique content fingerprints), the fixed `multi_collection_query()` SHALL produce exactly the same results in the same order as the original function, preserving result quality, ordering, and latency characteristics.

**Validates: Requirements 3.1, 3.2, 3.6**

Property 3: Preservation - Unique Content Count Non-Decreasing After Cleanup

_For any_ execution of the cleanup script against the `mdc-workflow-docs-titan1024` index, the number of unique content fingerprints in the index after cleanup SHALL be greater than or equal to the number before cleanup (only true duplicates are removed, never unique content).

**Validates: Requirements 2.5, 3.7**

Property 4: Preservation - Cleanup Idempotency

_For any_ two consecutive executions of the cleanup script against the same index, the second execution SHALL report zero duplicates found and remove zero documents, producing the same final state as after the first execution.

**Validates: Requirements 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `mcp_server_python/src/data/opensearch_adapter.py`

**Function**: `multi_collection_query()`

**Specific Changes (Fix 1 — Query-Time Dedup, ~5 lines)**:
1. **Add fingerprint set**: After the `merged.sort(...)` line, initialize `seen: set[str] = set()`
2. **Filter duplicates**: Replace the simple `merged[:k]` slice with a loop that:
   - Extracts `fp = row.get("content", "")[:200]` for each row
   - Skips the row if `fp in seen`
   - Otherwise adds `fp` to `seen` and appends to the deduped list
   - Stops when `len(deduped) == k`
3. **Return deduped list**: Return the deduped list instead of `merged[:k]`
4. **Complexity**: O(k) where k ≤ 20, negligible latency impact — no additional OpenSearch calls

**File**: `mcp_server_node/scripts/ingestion_base.py`

**Function**: `deterministic_id()`

**Specific Changes (Fix 2a — Ingest-Time Deterministic IDs)**:
1. **Change ID formula**: Replace `SHA-256(content|source|chunk_index|model_suffix)[:32]` with `SHA-256(source_name + first_500_chars_of_content)[:16]`
2. **Remove chunk_index dependency**: The new formula is independent of chunk ordering, so re-chunking the same content produces the same ID
3. **Shorter ID (16 hex chars)**: Sufficient for uniqueness within the index (~18 quintillion possible values)
4. **Backward compatibility**: Existing documents retain their old IDs; the cleanup script handles deduplication of legacy entries

**File**: `mcp_server_python/scripts/dedup_opensearch_index.py` (NEW)

**Specific Changes (Fix 2b — One-Time Cleanup Script)**:
1. **Scroll all documents**: Use OpenSearch scroll API to iterate through all documents in the target index
2. **Group by fingerprint**: Build a dict mapping `content[:200]` → list of `(doc_id, metadata)` tuples
3. **Select best document per group**: For groups with >1 document, keep the one with the richest metadata (highest field count, most recent timestamp)
4. **Delete duplicates**: Issue bulk delete requests for all non-best documents in each group
5. **CLI flags**: Support `--dry-run` (report only), `--index` (target index name), `--region` (AWS region)
6. **AWS SigV4 auth**: Use the same `boto3` + `AWSV4SignerAuth` pattern as `backfill_manifest_status.py`
7. **Reporting**: Print total docs before, duplicates found, docs after, unique content preserved

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that construct an `OpenSearchAdapter` with a mock client returning duplicate content hits, call `multi_collection_query()`, and assert that duplicates appear in the result set. Run these tests on the UNFIXED code to observe the duplication behavior.

**Test Cases**:
1. **Exact duplicate test**: Mock returns 3 hits with identical `content` fields from same collection (will show duplicates on unfixed code)
2. **Cross-collection duplicate test**: Mock returns same content from two different collections (will show duplicates on unfixed code)
3. **Partial overlap test**: Mock returns 5 hits where 2 share the same first-200-char prefix but differ after (will show duplicates on unfixed code)
4. **Score ordering with duplicates**: Mock returns duplicates at different scores — verify highest-scored copy is the one that would be kept (will show all copies on unfixed code)

**Expected Counterexamples**:
- All duplicate hits appear in the returned list consuming result slots
- Possible causes confirmed: no fingerprint check in `multi_collection_query()` merge logic

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  results := multi_collection_query_fixed(input.collections, input.query_text, k=input.k)
  fingerprints := SET()
  FOR EACH r IN results DO
    fp := r.content[0:200]
    ASSERT fp NOT IN fingerprints
    fingerprints.ADD(fp)
  END FOR
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT multi_collection_query(input) = multi_collection_query_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (random collections, query texts, k values)
- It catches edge cases that manual unit tests might miss (empty content, None content, single-char content)
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for queries that produce no duplicates, then write property-based tests capturing that behavior. For the cleanup script, verify idempotency by running twice and asserting identical final state.

**Test Cases**:
1. **Non-duplicate query preservation**: Generate random result sets with all-unique content, verify fixed function returns identical results to original
2. **Score ordering preservation**: Verify that among non-duplicate results, score ordering is maintained exactly
3. **Collection attribution preservation**: Verify that the `collection` field on each result is preserved correctly
4. **Empty/None content handling**: Verify that results with empty or None content fields don't crash the fingerprint logic

### Unit Tests

- Test `multi_collection_query()` with mock returning exact duplicates — verify only one copy returned
- Test `multi_collection_query()` with mock returning all-unique results — verify identical output to unfixed version
- Test fingerprint edge cases: empty string content, None content, content shorter than 200 chars
- Test that the highest-scored duplicate is the one retained
- Test cleanup script `--dry-run` mode reports but doesn't delete
- Test cleanup script idempotency (second run finds zero duplicates)
- Test deterministic ID generation produces same ID for same content regardless of chunk index

### Property-Based Tests

- Generate random lists of search results (some with duplicate content, some without) and verify the dedup filter always produces unique fingerprints while preserving score ordering
- Generate random result sets with all-unique content and verify the fixed function is a no-op (identical output)
- Generate random document sets for the cleanup script and verify unique content count never decreases
- Generate random document sets, run cleanup twice, verify second run is a no-op (idempotency)

### Integration Tests

- End-to-end test: ingest a document twice via different paths, query it, verify only one copy returned
- Cleanup script integration: populate a test index with known duplicates, run cleanup, verify correct documents remain
- Manifest update: after cleanup, run `backfill_manifest_status.py` and verify `doc_count` reflects the reduced total
- AgentCore deployment: after image rebuild with Fix 1, verify `search_documentation` tool returns deduplicated results for the known ESMF query
