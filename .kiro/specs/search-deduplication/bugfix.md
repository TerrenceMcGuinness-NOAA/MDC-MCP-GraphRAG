# Bugfix Requirements Document

## Introduction

The `search_documentation` tool in the AgentCore MCP server returns duplicate search results when querying content that was indexed multiple times in OpenSearch. For example, querying "ESMF coupling framework NUOPC component initialization" returns 4 identical text chunks from `esmf-user-guide` (all scoring 100%) plus 1 chunk from `nuopc-ref-pdf` with the same content in different formatting — effectively wasting 3-4 of the user's 5 result slots on redundant information.

The root cause is twofold: (1) the ESMF docs crawler followed multiple navigation paths to the same page, creating duplicate documents with different IDs in the `mdc-workflow-docs-titan1024` index, and (2) `OpenSearchAdapter.multi_collection_query()` performs no content-based deduplication after merging and sorting results from multiple collections.

This bug was identified in the parity assessment (Section 1.1 of `parity_assessment_soc_topology.md`) and is listed as a short-term fix candidate (Recommendation #3).

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a query matches documentation content that was indexed multiple times under different document IDs THEN the system returns all duplicate copies as separate results, consuming the user's result budget with identical content

1.2 WHEN `multi_collection_query()` merges results from multiple collections and the same text chunk exists in the index more than once THEN the system returns all copies sorted only by score with no content-based deduplication

1.3 WHEN the documentation crawler encounters the same page via multiple navigation paths THEN the system indexes the same content multiple times with different sequential document IDs, creating persistent duplicates in the `mdc-workflow-docs-titan1024` index

1.4 WHEN overlapping crawl runs re-index previously ingested content THEN the system creates additional duplicate documents because the ingestion pipeline uses sequential counters for document IDs rather than content-derived deterministic IDs

### Expected Behavior (Correct)

2.1 WHEN a query matches documentation content that was indexed multiple times THEN the system SHALL return only one copy of each unique text chunk, using the first 200 characters of content as a fingerprint for deduplication

2.2 WHEN `multi_collection_query()` merges and sorts results THEN the system SHALL skip any hit whose content fingerprint (first 200 characters) matches a previously seen result, ensuring all returned results contain distinct content

2.3 WHEN the documentation crawler encounters the same page via multiple navigation paths THEN the system SHALL generate a deterministic document ID based on SHA-256 of the first 500 characters of content combined with the source name, preventing duplicate indexing at ingest time

2.4 WHEN overlapping crawl runs re-index previously ingested content THEN the system SHALL produce the same document ID for identical content, causing an upsert rather than a new document insertion

2.5 WHEN a one-time cleanup script is run against `mdc-workflow-docs-titan1024` THEN the system SHALL identify and remove duplicate documents while preserving all unique content, supporting `--dry-run` mode and verifying document counts before and after

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a query matches distinct documents that happen to have similar scores THEN the system SHALL CONTINUE TO return all of them (deduplication only removes content-identical results, not topically similar ones)

3.2 WHEN `multi_collection_query()` is called with queries that produce no duplicates THEN the system SHALL CONTINUE TO return results sorted by score with no change in latency or result quality

3.3 WHEN the ingestion pipeline processes genuinely new content THEN the system SHALL CONTINUE TO index it successfully with the new deterministic ID scheme

3.4 WHEN the cleanup script is run with `--dry-run` THEN the system SHALL CONTINUE TO leave the index completely unmodified, only reporting what would be removed

3.5 WHEN the cleanup script is run multiple times (idempotent execution) THEN the system SHALL CONTINUE TO produce the same final state without removing additional documents on subsequent runs

3.6 WHEN query-time deduplication is applied THEN the system SHALL CONTINUE TO maintain query latency within acceptable bounds (fingerprint check is O(k) where k ≤ 20, adding negligible overhead)

3.7 WHEN the cleanup completes THEN the system SHALL CONTINUE TO have at least the same number of unique documents as before (total unique content count must not decrease)

---

## Bug Condition (Formal)

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type SearchQuery
  OUTPUT: boolean
  
  // Returns true when the query produces results containing
  // content-identical chunks (same first 200 chars) in the
  // merged result set
  results ← multi_collection_query(X.collections, X.query_text, k=X.k)
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

### Fix Checking Property

```pascal
// Property: Fix Checking — No duplicate content in results
FOR ALL X WHERE isBugCondition(X) DO
  results ← multi_collection_query'(X.collections, X.query_text, k=X.k)
  fingerprints ← SET()
  FOR EACH r IN results DO
    fp ← r.content[0:200]
    ASSERT fp NOT IN fingerprints
    fingerprints.ADD(fp)
  END FOR
END FOR
```

### Preservation Checking Property

```pascal
// Property: Preservation Checking — Non-duplicate queries unchanged
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT multi_collection_query(X) = multi_collection_query'(X)
END FOR
```
