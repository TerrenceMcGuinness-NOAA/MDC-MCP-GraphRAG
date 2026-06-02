# Requirements Document — `graph-port-python-community`

> **STATUS: PLACEHOLDER / STUB.** Title and scope sketch only. Full
> requirements to be authored when this spec is picked up (Spec 3 of the
> graph-relationship-parity series, after `graph-port-workflow-structure`).

## Introduction (sketch)

Spec 3 of the graph-relationship-parity series. Two distinct workstreams:

### 3a. Python AST graph

Port `ingest_python_graph.py` (from `mcp_server_node/scripts/`) to the Python
tenant-aware pipeline. Adds Python-specific graph semantics that the Fortran-
oriented `ingest_code_v8.py` does not capture:
- `INHERITS` — Python class inherits from another class
- richer `IMPORTS` — Python module-to-module imports (distinct from Fortran USE)
- Python-specific `CALLS` / `DEFINES` from the Python AST

Growing in importance with the `pygfs` / `wxflow` codebases.

### 3b. Community detection (graph analytics)

Replicate `run_community_detection.js` — which uses Neo4j's GDS (Graph Data
Science) Louvain algorithm — on Neptune, which has NO GDS library. Produces:
- `MEMBER_OF` (community) — file/function assigned to a detected subsystem
- `INTERACTS_WITH` — cross-community coupling edge

DESIGN CHALLENGE: Neptune openCypher has no Louvain/PageRank. Options:
1. Neptune Analytics (the ML/graph-analytics add-on) — managed but extra cost
2. External batch: export the CALLS/USES subgraph, run Louvain via Python
   NetworkX or igraph, write the community memberships back as edges
Option 2 is likely preferred (no new managed service). This is more design
work than the other ports — it's an analytics pass, not an ingestion port.

Enables: Python class-hierarchy queries, subsystem/community discovery,
`search_architecture` community summaries with real community structure.

Lower priority than Specs 1 and 2 (operational users get more value from the
shell + workflow graph than from Python class hierarchies and community
analytics).

## Requirements

_TODO: author full EARS requirements when picked up. Consider splitting 3a
(straightforward ingestion port) from 3b (analytics batch) into separate
specs if the community-detection design proves heavy._
