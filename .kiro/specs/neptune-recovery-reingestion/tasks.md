# Implementation Plan: Neptune Recovery — Track B Re-Ingestion

## Overview

Re-ingest the global-workflow source tree into the recovered Neptune cluster to capture changes since the April 7 S3 dump. Track A (bulk load) is complete. All ingestion scripts use MERGE (idempotent upsert). The SigV4 HTTP adapter (`neptune-python-sigv4-ingestion` spec) is implemented and tested — `get_graph_driver()` now returns a `NeptuneHTTPAdapter` when `DB_BACKEND=aws`.

## Tasks

- [x] 0. Track A: Neptune bulk load recovery from S3 (COMPLETE)
  - Admin attached `mdc-mcp-rag-neptune-s3-loader` role to `mdc-mcp-graprag-neptune-1`
  - Bulk load restored ~59,759 nodes and ~2,633,374 relationships
  - _Completed prior to this spec_

- [x] 1. Update Neptune endpoint configuration (COMPLETE)
  - `start-aws-mcp.sh` already points to `mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`
  - `run-track-b-ingestion.sh` has the correct endpoint
  - SigV4 HTTP adapter implemented in `aws_backend.py` (neptune-python-sigv4-ingestion spec)
  - _Requirements: 7.1, 7.2_

- [ ] 2. Assess source tree drift since April 7
  - [ ] 2.1 Count commits since April 7: `cd supported_repos/global-workflow && git log --oneline --since="2026-04-07" | wc -l`
  - [ ] 2.2 Identify changed subsystems: `cd supported_repos/global-workflow && git diff --stat HEAD@{2026-04-07} -- sorc/ ush/ jobs/ parm/ scripts/`
  - [ ] 2.3 Summarize: number of commits, files changed by type (Fortran, Shell, Python)
    - _Requirements: 1.1, 1.2, 1.3_

- [ ] 3. Re-run Fortran graph ingestion
  - [ ] 3.0 Enhance `ingest_fortran_graph.py` logging and observability
    - Add per-file logging with timestamps showing which file is being parsed and ingested
    - Add memory usage reporting (RSS) at progress checkpoints
    - Reduce progress interval from every 500 files to every 50 files
    - Add elapsed time and ETA calculation at each progress checkpoint
    - Add per-file node/relationship counts in verbose output
    - Log phase transitions: "PARSING file X" → "INGESTING file X" → "DONE file X"
    - Flush stdout after each log line to ensure real-time visibility
    - _Requirements: 8.1, 8.2, 8.3_
  - [ ] 3.1 Run Fortran ingestion against Neptune via SigV4 adapter
    - Working directory: `mcp_server_node`
    - Command: `DB_BACKEND=aws NEPTUNE_ENDPOINT="wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182" AWS_REGION=us-east-1 python3.12 scripts/ingest_fortran_graph.py`
    - Note: `CREATE INDEX` warnings from Neptune are expected and non-fatal (Neptune doesn't support Neo4j index syntax)
    - MERGE ensures no duplicates with bulk-loaded baseline
    - _Requirements: 2.1, 2.2, 2.3_

- [ ] 4. Re-run Shell script graph ingestion
  - [ ] 4.1 Run Shell ingestion against Neptune via SigV4 adapter
    - Working directory: `mcp_server_node`
    - Command: `DB_BACKEND=aws NEPTUNE_ENDPOINT="wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182" AWS_REGION=us-east-1 python3.12 scripts/ingest_shell_graph_v8.py`
    - Updates SOURCES, INVOKES, DEPENDS_ON_ENV relationships
    - _Requirements: 3.1, 3.2, 3.3_

- [ ] 5. Re-run cross-language bridge ingestion
  - [ ] 5.1 Run cross-language bridge ingestion against Neptune via SigV4 adapter
    - Working directory: `mcp_server_node`
    - Command: `DB_BACKEND=aws NEPTUNE_ENDPOINT="wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182" AWS_REGION=us-east-1 python3.12 scripts/ingest_cross_language_bridges.py`
    - Rebuilds EXECUTES (Shell→Fortran) and INVOKES (Shell→Python) bridges
    - Depends on steps 3 and 4 completing first
    - _Requirements: 4.1, 4.2_

- [ ] 6. Re-run Python graph ingestion
  - [ ] 6.1 Run Python ingestion against Neptune via SigV4 adapter
    - Working directory: `mcp_server_node`
    - Command: `DB_BACKEND=aws NEPTUNE_ENDPOINT="wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182" AWS_REGION=us-east-1 OPENSEARCH_ENDPOINT="https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com" python3.12 scripts/ingest_code_v8.py --model mpnet768`
    - Updates Python module, function, and class nodes
    - Can run in parallel with step 5
    - _Requirements: 5.1, 5.2_

- [ ] 7. Validate post-ingestion counts
  - [ ] 7.1 Query Neptune for node and relationship counts
    - Use the SigV4 adapter: `DB_BACKEND=aws NEPTUNE_ENDPOINT="wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182" AWS_REGION=us-east-1 python3.12 -c "from aws_backend import get_graph_driver; d=get_graph_driver(); s=d.session(); print('Nodes:', s.run('MATCH (n) RETURN count(n) AS c').single()['c']); print('Rels:', s.run('MATCH ()-[r]->() RETURN count(r) AS c').single()['c'])"`
    - Compare against pre-ingestion baseline (59,759 nodes / 2,633,374 rels)
    - _Requirements: 6.1_

- [ ] 8. Validate tool parity
  - [ ] 8.1 Run representative graph-dependent tools against AWS backend
    - `get_code_context("setuprad")` — should return graph neighborhood
    - `trace_full_execution_chain("JGLOBAL_FORECAST")` — should return cross-language chain
    - `find_callers_callees("setuprad")` — should return callers and callees
    - `search_architecture("GFS forecast job")` — should return L1/L2 communities
    - _Requirements: 6.2, 6.3, 6.4_
  - [ ] 8.2 Compare results against legacy eib-mcp-gateway for parity
    - _Requirements: 6.3_

- [ ] 9. Update CHANGELOG and SDD
  - [ ] 9.1 Update `CHANGELOG.md` with Phase 53 Track B completion
  - [ ] 9.2 Update `sdd_framework/workflows/phase53_neptune_recovery_incremental_ingestion.md` with actual results

## Notes

- All ingestion scripts are in `mcp_server_node/scripts/` and use `DB_BACKEND=aws` env var (not `--backend` flag)
- Python 3.12 is required (`python3.12`) — packages (fparser, sentence-transformers, opensearch-py, boto3) are installed there
- `CREATE INDEX` errors from Neptune are expected and non-fatal — the scripts catch them with try/except
- Community detection is deferred — requires Neo4j GDS, not available on Neptune
- The SigV4 HTTP adapter normalizes `wss://` endpoints to `https://` automatically
- WORKFLOW_ROOT should be set to the global-workflow repo path if scripts need it
