# Implementation Plan: AWS Documentation Refresh Ingest

## Overview

Run a full doc re-ingest to refresh the 44 stale sources, attempt the 14
never-ingested sources, and resolve the Stale Embeddings + Path Consistency
integrity WARNs on the AWS backend.

## Tasks

- [ ] 1. Pre-flight
  - [ ] 1.1 Confirm AWS stores awake: `quickstart-wake.sh` or verify Neptune + OpenSearch responding
  - [ ] 1.2 Confirm ingester importable: `python3.12 -c "from mcp_server_python.scripts.ingest_documentation_v8 import ..."`
  - [ ] 1.3 Record baseline: `list_all_sources --include_gaps` (capture stale/never counts); `get_knowledge_base_status` (capture doc count)

- [ ] 2. Run the ingest
  - [ ] 2.1 Launch detached: `nohup python3.12 mcp_server_python/scripts/ingest_documentation_v8.py --mode full --tiers all --delay 0.5 > logs/aws_doc_refresh_<ts>.log 2>&1 &`
  - [ ] 2.2 Monitor progress: `tail -f logs/aws_doc_refresh_*.log`; watch for `[ERROR]` lines on the 14 never-ingested sources

- [ ] 3. Post-ingest verification
  - [ ] 3.1 `list_all_sources --include_gaps` → 0 stale sources (all `last_ingested` = today)
    - _Requirements: 2.1_
  - [ ] 3.2 `check_knowledge_integrity` → Stale Embeddings `[OK]`, Path Consistency `[OK]`
    - _Requirements: 3.1, 3.2_
  - [ ] 3.3 `get_knowledge_base_status` → doc count ≥ 20,155 (ideally ~21,248)
    - _Requirements: 4.1_

- [ ] 4. Document never-ingested source outcomes
  - [ ] 4.1 For each of the 14 never-ingested sources: record success (new `doc_count`) or failure (HTTP error, dead URL, rate limit)
    - _Requirements: 2.2, 2.3_
  - [ ] 4.2 Optionally disable truly-dead sources in the manifest (mark `enabled: false`)

- [ ] 5. Final report
  - [ ] 5.1 Record before/after counts, runtime, embed cost, and any source disposition changes in the run log

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 4, "tasks": ["4.1", "4.2"] },
    { "id": 5, "tasks": ["5.1"] }
  ]
}
```
