# Implementation Plan

## Overview

Two-pronged fix for duplicate search results in `search_documentation`:
- **Fix 1**: ~5 lines in `opensearch_adapter.py` — query-time content fingerprint dedup in `multi_collection_query()`, plus image rebuild/deploy to AgentCore
- **Fix 2**: New `dedup_opensearch_index.py` cleanup script + deterministic ID change in `ingest_documentation_v8.py` + manifest update

Verification is via live search queries and dry-run output (no property-based tests per user direction).

## Tasks

## Fix 1: Query-Time Deduplication (~5 lines in opensearch_adapter.py)

- [x] 1. Verify bug exists — reproduce duplicate results on UNFIXED code
  - **Property 1: Bug Condition** - Duplicate Content in Search Results
  - **IMPORTANT**: Run this verification BEFORE implementing the fix
  - **GOAL**: Confirm the bug condition holds for the known ESMF query
  - Query `search_documentation` with "ESMF coupling framework NUOPC component initialization" (k=5)
  - Observe: multiple results with identical first-200-char content fingerprints appear in the result set
  - Document the duplicate count and wasted result slots (expected: 3-4 of 5 slots wasted)
  - Optionally run a second query ("UFS model configuration") to confirm pattern is not isolated
  - **EXPECTED OUTCOME**: Duplicates confirmed — validates the bug condition from design
  - _Requirements: 1.1, 1.2_

- [x] 2. Verify preservation baseline — confirm non-duplicate queries return correct results on UNFIXED code
  - **Property 2: Preservation** - Non-Duplicate Query Behavior
  - **IMPORTANT**: Follow observation-first methodology on UNFIXED code
  - Query `search_documentation` with a topic that produces all-unique results (e.g., "forecast model GFS configuration")
  - Record the exact result set: count, ordering, scores, content snippets
  - Query a second non-duplicate topic and record results
  - These recorded baselines will be compared after the fix to confirm no regressions
  - **EXPECTED OUTCOME**: Results are all unique, well-ordered by score — baseline captured
  - _Requirements: 3.1, 3.2, 3.6_

- [x] 3. Implement query-time dedup in `multi_collection_query()`

  - [x] 3.1 Add fingerprint-based deduplication to `opensearch_adapter.py`
    - File: `mcp_server_python/src/data/opensearch_adapter.py`, method `multi_collection_query()` (line ~232)
    - After `merged.sort(key=lambda r: r.get("score", 0.0), reverse=True)`, replace `return merged[:k]` with:
      ```python
      seen: set[str] = set()
      deduped: list[dict[str, Any]] = []
      for row in merged:
          fp = (row.get("content") or "")[:200]
          if fp not in seen:
              seen.add(fp)
              deduped.append(row)
              if len(deduped) == k:
                  break
      return deduped
      ```
    - This is ~5 lines, O(k) complexity, no additional OpenSearch calls
    - _Bug_Condition: isBugCondition(input) where merged results contain content-identical hits_
    - _Expected_Behavior: each returned result has a unique content fingerprint (first 200 chars)_
    - _Preservation: non-duplicate queries return identical results since no fingerprints collide_
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.6_

  - [x] 3.2 Verify bug condition query now returns deduplicated results
    - **Property 1: Expected Behavior** - No Duplicate Content in Search Results
    - **IMPORTANT**: Re-run the SAME query from task 1 — do NOT write a new test
    - Re-run "ESMF coupling framework NUOPC component initialization" (k=5)
    - **EXPECTED OUTCOME**: All 5 results have distinct content fingerprints — no duplicates
    - _Requirements: 2.1, 2.2_

  - [x] 3.3 Verify preservation queries still return identical results
    - **Property 2: Preservation** - Non-Duplicate Query Behavior
    - **IMPORTANT**: Re-run the SAME queries from task 2 — do NOT write new tests
    - Re-run the non-duplicate queries recorded in task 2
    - Compare result count, ordering, scores, and content to the baseline
    - **EXPECTED OUTCOME**: Results are identical to the pre-fix baseline — no regressions
    - _Requirements: 3.1, 3.2, 3.6_

  - [x] 3.4 Rebuild and deploy Docker image with Fix 1
    - Rebuild the Python MCP server image with the dedup change
    - Tag as `python-all-tools-v4` (next version after current `python-all-tools-v3`)
    - Push to ECR: `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-all-tools-v4`
    - Update AgentCore runtime `mdc_mcp_rag_server_python-v5K2F8BGrN` to the new image
    - Smoke-test via `get_server_info` — confirm 51 tools, 9 modules
    - _Requirements: 2.1, 2.2_

  - [x] 3.5 Verify deduplication works on live AgentCore runtime
    - Run "ESMF coupling framework NUOPC component initialization" via the deployed runtime
    - Confirm deduplicated results (no duplicate fingerprints in response)
    - Run a non-duplicate query and confirm results unchanged
    - _Requirements: 2.1, 2.2, 3.1, 3.2_

## Fix 2: Ingest-Time Deterministic IDs + Index Cleanup

- [x] 4. Create `dedup_opensearch_index.py` cleanup script

  - [x] 4.1 Implement the cleanup script
    - File: `mcp_server_python/scripts/dedup_opensearch_index.py` (NEW)
    - Use OpenSearch scroll API to iterate all documents in target index
    - Group documents by content fingerprint (`content[:200]`)
    - For groups with >1 document, keep the one with richest metadata (highest field count, most recent timestamp)
    - Delete duplicates via bulk delete API
    - CLI flags: `--dry-run` (report only), `--index` (target index, default `mdc-workflow-docs-titan1024`), `--region` (AWS region, default `us-east-1`)
    - Use `boto3` + `AWSV4SignerAuth` pattern (same as `backfill_manifest_status.py`)
    - Print summary: total docs before, duplicates found, docs deleted, unique content preserved
    - _Bug_Condition: index contains multiple documents with identical content fingerprints_
    - _Expected_Behavior: only one document per unique fingerprint remains after cleanup_
    - _Preservation: unique content count must not decrease (Req 3.7), dry-run leaves index unmodified (Req 3.4)_
    - _Requirements: 2.5, 3.4, 3.5, 3.7_

  - [x] 4.2 Verify `--dry-run` mode reports duplicates without modifying index
    - Run: `python dedup_opensearch_index.py --dry-run --index mdc-workflow-docs-titan1024`
    - Confirm output reports duplicate count and which documents would be removed
    - Confirm index document count is unchanged after dry-run
    - _Requirements: 3.4_

  - [x] 4.3 Run cleanup (live) and verify results
    - Run: `python dedup_opensearch_index.py --index mdc-workflow-docs-titan1024`
    - Verify: unique content count after ≥ unique content count before
    - Verify: total document count decreased by the number of duplicates reported
    - _Requirements: 2.5, 3.7_

  - [x] 4.4 Verify idempotency — second run finds zero duplicates
    - Re-run: `python dedup_opensearch_index.py --dry-run --index mdc-workflow-docs-titan1024`
    - **EXPECTED OUTCOME**: Reports 0 duplicates found, 0 documents to remove
    - _Requirements: 3.5_

- [x] 5. Update ingestion pipeline with deterministic ID generation

  - [x] 5.1 Change ID formula in `ingest_documentation_v8.py`
    - File: `mcp_server_node/scripts/ingest_documentation_v8.py`
    - Replace current ID generation with: `SHA-256(source_name + first_500_chars_of_content)[:16]`
    - Remove dependency on chunk index — same content always produces same ID regardless of chunking order
    - Ensure existing documents are not affected (old IDs remain; cleanup script handles legacy dedup)
    - _Bug_Condition: re-ingestion of same content creates new documents with different IDs_
    - _Expected_Behavior: identical content produces identical ID → upsert, not insert_
    - _Preservation: genuinely new content still indexes successfully (Req 3.3)_
    - _Requirements: 2.3, 2.4, 3.3_

  - [x] 5.2 Update `documentation_sources_config.py` manifest if needed
    - File: `mcp_server_node/scripts/documentation_sources_config.py`
    - Ensure any source-level metadata or ID generation config aligns with the new deterministic scheme
    - No functional change if manifest only declares sources (not ID logic)
    - _Requirements: 2.3, 2.4_

## Data Integrity Verification

- [x] 6. End-to-end data integrity verification

  - [x] 6.1 Verify search quality post-cleanup
    - Run the ESMF duplicate query via live AgentCore runtime
    - Confirm: 1 ESMF result + 4 distinct related results (no duplicates)
    - Run 3-5 additional queries across different documentation sources
    - Confirm: all results contain unique content, scores are reasonable, no missing content
    - _Requirements: 2.1, 2.2, 3.1_

  - [x] 6.2 Verify index document counts via `get_knowledge_base_status`
    - Call `get_knowledge_base_status` tool
    - Record `mdc-workflow-docs-titan1024` document count
    - Compare to pre-cleanup count — difference should equal duplicates removed
    - Verify unique content count is preserved (≥ pre-cleanup unique count)
    - _Requirements: 3.7_

  - [x] 6.3 Verify manifest consistency
    - Run `backfill_manifest_status.py` to update manifest with current doc counts
    - Confirm manifest `doc_count` values reflect the post-cleanup totals
    - Verify no sources show unexpected zero counts (would indicate over-deletion)
    - _Requirements: 2.5, 3.7_

  - [x] 6.4 Verify re-ingestion produces upserts (not new duplicates)
    - Re-ingest a single known source using the updated `ingest_documentation_v8.py`
    - Confirm: document count for that source does NOT increase
    - Confirm: content is unchanged (same fingerprints present)
    - Run `dedup_opensearch_index.py --dry-run` — should report 0 new duplicates
    - _Requirements: 2.3, 2.4, 3.3, 3.5_

- [x] 7. Checkpoint — Ensure all verification passes
  - All live search queries return deduplicated results
  - Dry-run cleanup reports 0 remaining duplicates
  - Non-duplicate queries return same results as pre-fix baseline
  - Index unique content count is preserved
  - Manifest doc counts are consistent
  - Re-ingestion does not create new duplicates
  - Ask the user if questions arise

## Notes

- Fix 1 is the immediate user-facing improvement (query-time dedup) — deploy first
- Fix 2 prevents future duplicates at ingest time and cleans up existing index bloat
- The cleanup script must run AFTER Fix 1 is deployed so users benefit from dedup immediately
- Verification relies on live queries against the deployed AgentCore runtime, not unit/property tests
- Rollback: revert to `python-all-tools-v3` image tag if Fix 1 causes issues

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3"] },
    { "id": 3, "tasks": ["3.4"] },
    { "id": 4, "tasks": ["3.5"] },
    { "id": 5, "tasks": ["4.1", "5.1"] },
    { "id": 6, "tasks": ["4.2", "5.2"] },
    { "id": 7, "tasks": ["4.3"] },
    { "id": 8, "tasks": ["4.4"] },
    { "id": 9, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 10, "tasks": ["6.4"] },
    { "id": 11, "tasks": ["7"] }
  ]
}
```
