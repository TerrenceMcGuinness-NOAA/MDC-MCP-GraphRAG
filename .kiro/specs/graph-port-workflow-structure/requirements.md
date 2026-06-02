# Requirements Document — `graph-port-workflow-structure`

> **STATUS: PLACEHOLDER / STUB.** Title and scope sketch only. Full
> requirements to be authored when this spec is picked up (Spec 2 of the
> graph-relationship-parity series, after `graph-port-shell-ops`).

## Introduction (sketch)

Spec 2 of the graph-relationship-parity series. Ports the legacy workflow-
structure ingesters to the Python tenant-aware pipeline so Neptune captures
the Rocoto workflow DAG and config→env-var lineage that Neo4j has but Neptune
currently lacks.

Scripts to port (from `mcp_server_node/scripts/`):
- `ingest_rocoto_xml.py` — Rocoto XML workflow definitions
- `ingest_expdir_configs.py` — experiment-directory config resolution
- `ingest_config_files.py` — `parm/config/*` env-var setting

Relationship types this spec adds to Neptune (tenant-prefixed):
- `MEMBER_OF` — task belongs to a metatask (workflow hierarchy)
- `DEPENDS_ON` — task-level dependency (Rocoto `<dependency>`)
- `DEPENDS_ON_DATA` — task depends on a data file existing
- `RUNS_SCRIPT` — Rocoto task runs a specific ex-script (links to the
  ShellScript nodes from Spec 1)
- `RUNS_ON` — task runs on a specific HPC queue/partition
- `USES_ENV` — task uses an environment variable
- `SETS_ENV` — config file sets an env-var value (with value + is_default)
- `RESOLVES_FROM` / `PART_OF` — expdir config resolution chain

Enables: workflow task-ordering queries ("what runs before
JGFS_ATMOS_ANALYSIS?"), config lineage ("where does $COMROOT get its value?"),
Rocoto metatask hierarchy traversal.

Dependency: builds on Spec 1 — `RUNS_SCRIPT` edges link Rocoto tasks to the
`ShellScript` nodes that `graph-port-shell-ops` creates. Best sequenced after
Spec 1 lands.

## Requirements

_TODO: author full EARS requirements when picked up._
