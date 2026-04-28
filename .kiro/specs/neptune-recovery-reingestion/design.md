# Design Document: Neptune Recovery — Track B Re-Ingestion

## Overview

With Track A complete (59,759 nodes and 2,633,374 relationships restored from S3 bulk load), Track B brings the Neptune graph current by re-running the full ingestion suite against the live source tree. All scripts use MERGE (idempotent upsert), so they safely layer new/changed entities on top of the restored baseline.

## Ingestion Pipeline

The ingestion scripts run in a specific order due to dependencies:

```
1. ingest_fortran_graph.py    → Fortran subroutines, functions, modules
2. ingest_shell_graph_v8.py   → J-Jobs, ex-scripts, ush scripts, env vars
3. ingest_cross_language_bridges.py → Shell→Fortran EXECUTES, Shell→Python INVOKES
4. ingest_code_v8.py          → Python modules, classes, functions + embeddings
```

Steps 1–2 create the base nodes. Step 3 creates cross-language edges that reference nodes from steps 1–2. Step 4 adds Python nodes and can run in parallel with step 3.

All scripts accept `--backend aws` to route to Neptune + OpenSearch instead of Neo4j + ChromaDB.

## Neptune Endpoint

The recovered cluster uses a different endpoint than the deleted one:

| | Deleted Cluster | Recovered Cluster |
|---|---|---|
| Identifier | `mdc-mcp-rag-neptune` | `mdc-mcp-graprag-neptune-1` |
| Endpoint | `mdc-mcp-rag-neptune.cluster-ccdaimu4c86s...` | `mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s...` |

The `NEPTUNE_ENDPOINT` environment variable and `start-aws-mcp.sh` must reference the new endpoint.

## Community Detection

The Leiden community detection algorithm requires Neo4j GDS (Graph Data Science), which is not available on Neptune. Options:

1. Skip community refresh if drift is minor (communities are already in OpenSearch from Phase 50 migration)
2. Export graph from Neptune to Neo4j on PW, run Leiden, export communities, import back to Neptune

For this phase, option 1 is recommended unless the drift assessment shows significant structural changes.

## Validation Strategy

After re-ingestion, validate with:
- Node/relationship count comparison (before vs after)
- Tool parity: run `get_code_context("setuprad")`, `trace_full_execution_chain("JGLOBAL_FORECAST")`, `find_callers_callees("setuprad")` against both legacy and AWS
- Health check: `mcp_health_check` should report Neptune HEALTHY with updated counts
