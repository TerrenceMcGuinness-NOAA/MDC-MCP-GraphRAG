# Technical Design Document

## Overview

This design describes the execution orchestration for ingesting 12 pending `url_crawl` sources into the `mdc-workflow-docs-titan1024` OpenSearch collection. The work uses the existing `ingest_documentation_v8.py` pipeline with the `titan1024` embedding profile (Amazon Titan Embed Text v2, 1024 dimensions via Bedrock). No new library code is written — the design focuses on the operator-driven crawl orchestration sequence, the verification approach, and the empty-site handling logic that distinguishes between "site has no content" and "site is unreachable."

## Architecture

The ingestion flow uses three existing components in sequence:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Crawl Orchestrator (operator)                     │
│                                                                       │
│  1. Reachability check (curl HEAD per URL)                           │
│  2. Tiered execution: tier1 → tier2 → tier3 → tier4                 │
│  3. Within-tier: up to 3 concurrent ingest processes                 │
│  4. Post-crawl: backfill manifest, verify via search queries         │
└───────────┬───────────────────────────────────────────┬──────────────┘
            │                                           │
            ▼                                           ▼
┌───────────────────────┐               ┌──────────────────────────────┐
│  ingest_documentation │               │  backfill_manifest_status.py │
│  _v8.py               │               │  (Phase 57)                  │
│                       │               │                              │
│  - URLCrawler         │               │  - Queries OpenSearch for    │
│  - SemanticChunker    │               │    live doc_count per source │
│  - Bedrock Titan 1024 │               │  - Writes back to           │
│  - OpenSearch indexer  │               │    unified_manifest.json    │
└───────────┬───────────┘               └──────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────┐
│  OpenSearch: mdc-workflow-docs-titan1024│
│  (append-only, source-tagged docs)     │
└────────────────────────────────────────┘
```

## Components and Interfaces

### 1. Reachability Checker

A pre-flight smoke test that validates all 12 source URLs are reachable before committing to the full crawl.

**Interface:**
```bash
# For each URL, issue an HTTP HEAD request and check status code
curl -sL -o /dev/null -w "%{http_code}" "$url"
```

**Behavior:**
- HTTP 200: Source is reachable, proceed with crawl
- HTTP 301/302: Follow redirect (curl -L handles this), accept if final response is 200
- HTTP 404: Mark source as unreachable, skip crawl, log error
- HTTP 5xx: Mark source as unreachable, skip crawl, log error

**Output:** A reachability report mapping each source name to its HTTP status code and a go/no-go decision.

### 2. Tiered Execution Scheduler

The orchestrator processes sources in strict tier order with concurrency control within each tier.

**Execution Order:**

| Phase | Tier | Sources | Concurrency |
|-------|------|---------|-------------|
| 1 | tier1_critical | gsi-user-guide | 1 (single source) |
| 2 | tier2_workflow | uwtools | 1 (single source) |
| 3 | tier3_models | mpas-atmosphere, catchem, cece, cdeps, land-da, ufs-srweather-app, hafs | up to 3 |
| 4 | tier4_build | kokkos-api, nceplibs-sfcio | up to 2 |
| 5 | tier3_models (pre-existing) | cmeps | 1 |

**Within-tier ordering for tier3_models:**
- Newly added sources first: mpas-atmosphere, catchem, cece, cdeps, land-da, ufs-srweather-app, hafs
- Pre-existing source last: cmeps

**Concurrency model:**
- Maximum 3 concurrent `ingest_documentation_v8.py` processes
- Each process handles one source end-to-end (crawl → chunk → embed → index)
- Bedrock API concurrency is implicitly bounded by the 3-process limit (each process makes sequential embedding calls)
- When a process completes, the next pending source in the current tier starts

**Invocation per source:**
```bash
cd /mdc-mcp-rag/eib-mcp-rag-server
python3 mcp_server_node/scripts/ingest_documentation_v8.py \
  --model titan1024 \
  --tiers <tier_containing_source> \
  --delay 1.5
```

Since the v8 script processes all sources in a tier, individual source targeting requires either:
1. Temporarily modifying `documentation_sources_config.py` to disable all but the target source, or
2. Running the full tier and relying on the incremental deduplication (existing IDs are skipped)

The recommended approach is option (2): run the full tier with `--tiers tier3_models` and let the ingester skip already-indexed sources via its `_load_existing_ids()` mechanism.

### 3. Bedrock Throttling Handler

The existing `ingest_documentation_v8.py` pipeline uses the embedding registry's `titan1024` profile to call `bedrock-runtime:InvokeModel` for each chunk. Throttling is handled at the orchestrator level:

**Retry strategy:**
- On `ThrottlingException`: wait 2s, then retry with exponential backoff (2s, 4s, 8s, 16s, max 60s)
- On `ServiceUnavailableException`: wait 5s, retry up to 3 times
- On persistent failure (3 consecutive retries exhausted): log error, skip remaining chunks for that page, continue to next page

**Rate limiting:**
- Inter-page delay: 1.5 seconds (via `--delay 1.5`)
- Maximum concurrent Bedrock calls: 3 (one per active process)

### 4. Empty Site Handler

Distinguishes between three terminal states for a source:

| Condition | Status | Manifest Update |
|-----------|--------|-----------------|
| Crawl succeeds, doc_count > 0 | `ingested` | `doc_count: N`, `last_ingested: <timestamp>` |
| Crawl succeeds, doc_count = 0 | `empty_site` | `doc_count: 0`, `last_ingested: <timestamp>`, `enabled: true` |
| HTTP 404/5xx during crawl | `failed` | No manifest update, error logged |

**Logic (pseudocode):**
```python
def determine_source_status(source_name, crawl_result):
    if crawl_result.http_error:
        return Status.FAILED, crawl_result.http_status_code
    elif crawl_result.doc_count == 0:
        return Status.EMPTY_SITE, None
    else:
        return Status.INGESTED, crawl_result.doc_count
```

**Expected empty_site candidates:** cmeps, nceplibs-sfcio (very small libraries with minimal web documentation). kokkos-api may also produce 0 docs if the JS-heavy site doesn't render content for the crawler.

**Key invariant:** An `empty_site` source remains `enabled: true` in the manifest so that future re-crawl attempts can detect when content becomes available.

### 5. Manifest Status Writeback

After all 12 sources are attempted, the backfill script updates the manifest:

```bash
python3 scripts/backfill_manifest_status.py
```

This script:
1. Queries OpenSearch for document counts per source (using the `source` metadata field)
2. Updates `unified_manifest.json` with live `doc_count` values
3. Sets `last_ingested` to the current UTC timestamp for sources with `doc_count > 0`
4. For `empty_site` sources: sets `last_ingested` to current UTC, `doc_count` to 0

### 6. Verification Query Runner

Post-ingestion verification uses `search_documentation` to confirm semantic retrievability:

| Source | Verification Query | Expected |
|--------|-------------------|----------|
| gsi-user-guide | "GSI gridpoint statistical interpolation" | Results with source=gsi-user-guide |
| uwtools | "uwtools workflow tools" | Results with source=uwtools |
| mpas-atmosphere | "MPAS unstructured mesh" | Results with source=mpas-atmosphere |
| hafs | "HAFS hurricane vortex initialization" | Results with source=hafs |
| catchem | "CATChem aerosol chemistry" | Results with source=catchem |
| cdeps | "CDEPS data model driver" | Results with source=cdeps |
| land-da | "land data assimilation" | Results with source=land-da |
| ufs-srweather-app | "short range weather application" | Results with source=ufs-srweather-app |

**Anomaly detection:** If a source reports `doc_count > 0` but the verification query returns zero results, the source is flagged for manual investigation (possible embedding failure or metadata mismatch).

## Data Models

### Execution Log Entry

Each source produces a log entry with the following structure:

```python
{
    "source_name": "gsi-user-guide",
    "tier": "tier1_critical",
    "status": "ingested",        # ingested | empty_site | failed
    "doc_count": 87,
    "elapsed_seconds": 142.5,
    "start_time": "2026-05-19T14:00:00Z",
    "end_time": "2026-05-19T14:02:22Z",
    "error": null,               # HTTP status code or error message if failed
    "verification_passed": true  # search query returned results
}
```

### Manifest Source Entry (post-update)

```json
{
    "name": "gsi-user-guide",
    "source_type": "url_crawl",
    "collection_target": "mdc-workflow-docs-titan1024",
    "embedding_profile": "titan1024",
    "enabled": true,
    "doc_count": 87,
    "last_ingested": "2026-05-19T14:02:22+00:00",
    "url": "https://dtcenter.org/sites/default/files/community-code/gsi/docs/users-guide/html_v3.7/",
    "crawl_type": "readthedocs",
    "max_pages": 100,
    "tier": "tier1_critical"
}
```

### Summary Report

```
╔══════════════════════════════════════════════════════════════════════╗
║  URL CRAWL GAP CLOSURE — BATCH SUMMARY                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Total sources attempted:  12                                        ║
║  Successfully ingested:    9  (doc_count > 0)                        ║
║  Empty sites:              2  (valid crawl, no content)              ║
║  Failed:                   1  (HTTP error or crawl failure)          ║
║  Batch status:             SUCCESS (≥ 9 threshold met)               ║
║  Total new documents:      1,247                                     ║
║  Total elapsed time:       3h 42m                                    ║
╚══════════════════════════════════════════════════════════════════════╝
```

## Error Handling

### HTTP Errors During Crawl

| Error | Action |
|-------|--------|
| HTTP 404 | Log "Source URL not found", mark as `failed`, skip |
| HTTP 5xx | Log "Server error", mark as `failed`, skip |
| Connection timeout | Retry once after 10s, then mark as `failed` |
| SSL certificate error | Log warning, attempt with verify=False, log if succeeds |

### Bedrock API Errors

| Error | Action |
|-------|--------|
| ThrottlingException | Exponential backoff: 2s → 4s → 8s → 16s → 60s max |
| ValidationException | Log chunk that caused error, skip chunk, continue |
| ServiceUnavailableException | Wait 5s, retry 3x, then skip source |
| AccessDeniedException | Fatal — halt all processing, report IAM issue |

### OpenSearch Indexing Errors

| Error | Action |
|-------|--------|
| BulkIndexError (partial) | Log failed documents, continue with remaining |
| ConnectionError | Retry 3x with 5s delay, then mark source as failed |
| IndexNotFoundException | Fatal — halt, report missing index |

## Integrity Constraints

1. **Append-only indexing:** The ingest pipeline adds documents to OpenSearch without deleting existing documents. The `_load_existing_ids()` mechanism prevents duplicate insertion.
2. **Baseline preservation:** Post-ingestion total document count must be ≥ 27,222 (pre-ingestion baseline).
3. **Source isolation:** Each document is tagged with its `source` metadata field. Sources do not interfere with each other's documents.
4. **5% tolerance:** Previously ingested sources must retain their document counts within 5% of pre-ingestion values (accounts for minor deduplication adjustments on re-run).

## Testing Strategy

This feature is an operational task — no new code is written, so no unit tests or property-based tests are needed. Verification is performed inline during execution:

1. **Pre-flight smoke test:** HTTP HEAD requests to all 12 URLs confirm reachability before crawling begins.
2. **Post-ingestion integration checks:** Semantic search queries (`search_documentation`) verify that newly indexed content is retrievable.
3. **Manifest consistency check:** After backfill, compare manifest `doc_count` values against live OpenSearch index statistics.
4. **Regression check:** Verify total document count ≥ 27,222 and existing source counts within 5% tolerance.
5. **Gap detector validation:** `list_all_sources(include_gaps=True)` confirms pending count drops to 0 (or only legitimately empty sites remain).

All verification steps are executed as part of the orchestration workflow itself — they are not separate test suites.

## Correctness Properties

*This feature is primarily an operational task — running existing ingest scripts against new URL sources. The acceptance criteria are integration-level verifications (observing execution order, checking OpenSearch state, validating manifest updates) rather than pure-function properties amenable to property-based testing. No property-based tests are appropriate for this feature.*

**Rationale:** All 30 acceptance criteria fall into INTEGRATION, SMOKE, or EXAMPLE classifications:
- Requirements 1.x (tier ordering): Operational orchestration — verified by observing execution logs
- Requirements 2.x (concurrency): Infrastructure behavior — verified by monitoring active processes
- Requirements 3.x (crawl/embed/index): Existing pipeline behavior — verified by smoke tests
- Requirements 4.x (empty-site handling): Conditional logic on a fixed set of 3 sources — verified by example tests
- Requirements 5.x (manifest writeback): Data consistency — verified by comparing OpenSearch vs manifest
- Requirements 6.x (acceptance threshold): Numeric threshold — verified by counting results
- Requirements 7.x (integrity): Non-regression — verified by before/after comparison
- Requirements 8.x (search verification): Semantic retrieval — verified by running specific queries

None of these criteria satisfy the PBT decision guide:
1. Behavior does not vary meaningfully with random input (sources are a fixed set of 12)
2. We are testing external service behavior (OpenSearch, Bedrock, HTTP crawling), not pure functions
3. 100 iterations would not find more bugs than 1-2 iterations
4. Each iteration involves expensive external calls (Bedrock embeddings, OpenSearch indexing)

**Verification approach:** Integration tests with specific examples, executed as part of the orchestration workflow itself (reachability checks, post-ingestion search queries, manifest comparison).
