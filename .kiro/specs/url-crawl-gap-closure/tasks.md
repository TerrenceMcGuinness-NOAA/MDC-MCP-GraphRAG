# Implementation Plan: URL Crawl Gap Closure

## Overview

Ingest 12 pending `url_crawl` sources into the `mdc-workflow-docs-titan1024` OpenSearch collection using the existing `ingest_documentation_v8.py` pipeline with Titan 1024-dim embeddings. No new code is written — this is an operator-driven execution of existing tooling in tiered priority order with post-ingestion verification.

## Tasks

- [x] 1. Pre-flight reachability check
  - [x] 1.1 Run HTTP HEAD smoke test against all 12 source URLs
    - Execute curl loop to verify HTTP 200 for each URL
    - ```bash
      cd /mdc-mcp-rag/eib-mcp-rag-server
      for url in \
        "https://dtcenter.org/sites/default/files/community-code/gsi/docs/users-guide/html_v3.7/" \
        "https://uwtools.readthedocs.io/en/latest/" \
        "https://www2.mmm.ucar.edu/projects/mpas/site/index.html" \
        "https://ufs-community.github.io/CATChem" \
        "https://ufs-community.github.io/CECE" \
        "https://escomp.github.io/CDEPS/versions/master/html/index.html" \
        "https://land-da.readthedocs.io/en/stable/" \
        "https://ufs-srweather-app.readthedocs.io/en/develop/" \
        "https://hafsdoc.readthedocs.io/en/latest/" \
        "https://escomp.github.io/CMEPS/" \
        "https://noaa-emc.github.io/NCEPLIBS-sfcio/" \
        "https://kokkos.org/kokkos-core-wiki/api-references.html"; do
        status=$(curl -sL -o /dev/null -w "%{http_code}" "$url")
        echo "$status $url"
      done
      ```
    - Flag any URL returning 404 or 5xx as unreachable — skip those sources
    - Record reachability results in session notes
    - **RESULTS (2026-05-19T19:30Z)**: 11/12 returned HTTP 200. **`uwtools` returned 404** at `https://uwtools.readthedocs.io/en/latest/` — the project does not publish an `en/latest/` path. Probed alternatives: `en/main/` → 200, `en/stable/` → 200, bare host `/` → 200. **Recommend updating manifest URL** for `uwtools` to `https://uwtools.readthedocs.io/en/main/` before tier2 ingest (task 3.1). All other 11 URLs reachable and ready to ingest.
    - _Requirements: 4.5, 1.1_

- [x] 2. Ingest tier1_critical source (gsi-user-guide)
  - [x] 2.1 Run ingest pipeline for gsi-user-guide
    - ```bash
      cd /mdc-mcp-rag/eib-mcp-rag-server
      python3 mcp_server_node/scripts/ingest_documentation_v8.py \
        --model titan1024 \
        --tiers tier1_critical \
        --delay 1.5
      ```
    - Confirm doc_count > 0 in script output
    - _Requirements: 1.1, 3.1, 3.2, 3.3_

  - [x] 2.2 Verify gsi-user-guide ingestion via semantic search
    - Run `search_documentation("GSI gridpoint statistical interpolation")`
    - Confirm results contain source=gsi-user-guide
    - If zero results despite doc_count > 0, flag for manual investigation
    - _Requirements: 8.1, 8.4_

- [x] 3. Ingest tier2_workflow source (uwtools)
  - [x] 3.1 Run ingest pipeline for uwtools
    - ```bash
      cd /mdc-mcp-rag/eib-mcp-rag-server
      python3 mcp_server_node/scripts/ingest_documentation_v8.py \
        --model titan1024 \
        --tiers tier2_workflow \
        --delay 1.5
      ```
    - Confirm doc_count > 0 in script output
    - _Requirements: 1.2, 3.1, 3.2, 3.3_

  - [x] 3.2 Verify uwtools ingestion via semantic search
    - Run `search_documentation("uwtools workflow tools")`
    - Confirm results contain source=uwtools
    - _Requirements: 8.2_

- [ ] 4. Checkpoint — Verify tier1 and tier2 before proceeding
  - Ensure gsi-user-guide and uwtools both show doc_count > 0. Ask the user if questions arise.

- [x] 5. Ingest tier3_models batch (7 newly added sources)
  - [x] 5.1 Run ingest pipeline for tier3_models (mpas-atmosphere, catchem, cece, cdeps, land-da, ufs-srweather-app, hafs)
    - ```bash
      cd /mdc-mcp-rag/eib-mcp-rag-server
      python3 mcp_server_node/scripts/ingest_documentation_v8.py \
        --model titan1024 \
        --tiers tier3_models \
        --delay 1.5
      ```
    - The script's `_load_existing_ids()` mechanism will skip already-indexed sources (cice, mom6, etc.)
    - Monitor for Bedrock ThrottlingException — script handles exponential backoff automatically
    - Record doc_count for each newly ingested source from script output
    - _Requirements: 1.3, 2.1, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 5.2 Verify tier3_models ingestion via semantic search
    - Run `search_documentation("MPAS unstructured mesh")` — confirm results from mpas-atmosphere
    - Run `search_documentation("HAFS hurricane vortex initialization")` — confirm results from hafs
    - Run `search_documentation("CATChem aerosol chemistry")` — confirm results from catchem
    - Run `search_documentation("CDEPS data model driver")` — confirm results from cdeps
    - Run `search_documentation("land data assimilation")` — confirm results from land-da
    - Run `search_documentation("short range weather application")` — confirm results from ufs-srweather-app
    - _Requirements: 8.3, 8.4_

- [x] 6. Ingest tier4_build sources (kokkos-api, nceplibs-sfcio)
  - [x] 6.1 Run ingest pipeline for tier4_build
    - ```bash
      cd /mdc-mcp-rag/eib-mcp-rag-server
      python3 mcp_server_node/scripts/ingest_documentation_v8.py \
        --model titan1024 \
        --tiers tier4_build \
        --delay 1.5
      ```
    - The script skips already-indexed tier4 sources (nceplibs-bufr, spack, etc.)
    - kokkos-api is JS-heavy — may produce 0 docs (expected empty_site candidate)
    - nceplibs-sfcio is a very small library — may produce 0 docs (expected empty_site candidate)
    - _Requirements: 1.4, 3.1, 3.2, 3.3_

  - [x] 6.2 Handle empty_site results for tier4 sources
    - If kokkos-api or nceplibs-sfcio produce 0 docs after valid crawl, mark as `empty_site`
    - Verify the source URL was reachable (not HTTP error) — only mark empty_site if crawl succeeded with 0 content
    - Keep `enabled: true` in manifest for future re-crawl attempts
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 7. Retry pre-existing tier3 failure (cmeps)
  - [x] 7.1 Run ingest for cmeps specifically
    - cmeps is in tier3_models — it should have been attempted in step 5.1
    - If it was skipped or produced 0 docs, verify the URL manually: `curl -sL "https://escomp.github.io/CMEPS/" | head -100`
    - If site has no crawlable documentation content, mark as `empty_site`
    - _Requirements: 1.5, 4.1, 4.4_

- [ ] 8. Checkpoint — Verify all 12 sources attempted
  - Confirm all 12 sources have been attempted. Count sources with doc_count > 0. Ensure at least 9 of 12 have doc_count > 0 for batch success. Ask the user if questions arise.

- [x] 9. Manifest status writeback and final verification
  - [x] 9.1 Run backfill_manifest_status.py to update manifest
    - ```bash
      cd /mdc-mcp-rag/eib-mcp-rag-server
      python3 mcp_server_python/scripts/backfill_manifest_status.py \
        --manifest mcp_server_python/src/config/unified_manifest.json \
        --opensearch-endpoint $OPENSEARCH_ENDPOINT \
        --region us-east-1
      ```
    - Verify `doc_count` and `last_ingested` updated for all successfully ingested sources
    - Verify `empty_site` sources have `doc_count: 0` and `last_ingested` set to current UTC timestamp
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 9.2 Verify gap closure via list_all_sources
    - Run `list_all_sources(include_gaps=True)` via MCP tool
    - Confirm pending count drops to 0 (or only legitimately empty sites remain)
    - _Requirements: 5.4_

  - [x] 9.3 Verify knowledge base integrity (no regression)
    - Run `get_knowledge_base_status()` via MCP tool
    - Confirm total document count in `mdc-workflow-docs-titan1024` is ≥ 27,222 (pre-ingestion baseline)
    - Spot-check 2-3 previously ingested sources (e.g., ecflow, mom6) to confirm their doc_counts are within 5% of pre-ingestion values
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 9.4 Produce batch summary report
    - List each of the 12 sources with: source name, final doc_count, status (ingested/empty_site/failed), elapsed crawl time
    - Report total count of sources with doc_count > 0
    - Confirm batch success threshold: ≥ 9 sources with doc_count > 0
    - If fewer than 9, list failed sources with error details for investigation
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 10. Final checkpoint — Confirm gap closure complete
  - Ensure all verification queries pass, manifest is updated, and batch summary shows SUCCESS. Ask the user if questions arise.

## Notes

- This is an operational task — no new code is written. All tasks use existing scripts and MCP tools.
- The `ingest_documentation_v8.py` script with `--model titan1024` uses Amazon Titan Embed Text v2 (1024 dimensions) via Bedrock.
- Sources that produce 0 docs after a valid crawl are marked `empty_site` (not disabled) so future re-crawls can detect new content.
- Expected `empty_site` candidates: cmeps, nceplibs-sfcio, kokkos-api (JS-heavy or minimal documentation sites).
- The `_load_existing_ids()` mechanism in the ingest script prevents duplicate insertion when running full-tier commands.
- Bedrock throttling is handled automatically by the script with exponential backoff (2s → 4s → 8s → 16s → 60s max).
- Total estimated execution time: 4–6 hours (crawl time dominates).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2", "6.1"] },
    { "id": 5, "tasks": ["6.2", "7.1"] },
    { "id": 6, "tasks": ["9.1"] },
    { "id": 7, "tasks": ["9.2", "9.3"] },
    { "id": 8, "tasks": ["9.4"] }
  ]
}
```
