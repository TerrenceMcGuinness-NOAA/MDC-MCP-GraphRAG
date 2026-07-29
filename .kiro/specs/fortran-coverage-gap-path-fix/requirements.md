# Requirements Document

## Introduction

`check_knowledge_integrity`'s **Coverage Gap** sub-check always SKIPs with:

```
[SKIP] no Fortran files found in /app/supported_repos/global-workflow
```

This is a **false negative**. The Neo4j graph holds 80,745 FortranSubroutine
nodes, 16,849 FortranFunction nodes, and 9,014 FortranModule nodes — all sourced
from Fortran files that were present at ingest time. The bug: the check hard-codes
the pre-Phase-61 path (`/app/supported_repos/global-workflow`) instead of resolving
through the tenant's `workflow_root` (which under the multi-tenant mount model is
`/app/.pw_workflow_mount/<subdir>`).

This phase fixes the path resolution, adds a **graph-based fallback** (so the
check works even when the filesystem mount is unavailable, e.g. inside the
AgentCore microVM), and extends coverage checking to all primary language buckets.

Phase 72 from the SDD
(`sdd_framework/workflows/phase72_fortran_coverage_gap_path_fix.md`), surfaced in
the 2026-07-20 gap analysis (Gap 3).

## Requirements

### Requirement 1: Resolve source root via tenant catalog

**User Story:** As an operator, I want the coverage check to find Fortran files
at the correct tenant-resolved path, not a hard-coded stale path.

#### Acceptance Criteria

1. THE Coverage Gap check SHALL resolve the source-tree root via the active
   tenant's `workflow_root` from the tenant catalog (e.g.
   `/app/.pw_workflow_mount/develop` for tenant `gw`), not a hard-coded path.
2. WHEN `workflow_root` is reachable, THE check SHALL count Fortran files under
   `<workflow_root>/sorc/` and compare against `Fortran*`-labeled graph nodes.
3. THE check SHALL support the `MCP_WORKFLOW_MOUNT` env override (Phase 61
   contract) for non-default mount bases.

### Requirement 2: Graph-based fallback when mount unavailable

**User Story:** As an operator on a host without the workflow mount (e.g. the
AgentCore microVM), I want the check to still produce a numeric result.

#### Acceptance Criteria

1. WHEN `workflow_root` is not reachable (directory doesn't exist / not mounted),
   THE check SHALL fall back to counting `Fortran*`-labeled nodes in the graph
   and report their count (rather than SKIP).
2. THE fallback SHALL clearly label its output as "graph-only (filesystem not
   mounted)" so the reader knows it didn't cross-reference with on-disk files.
3. THE fallback SHALL produce `[OK]` when the graph has > 100 Fortran nodes
   (threshold), `[WARN]` when 1–100, and `[FAIL]` when 0.

### Requirement 3: Extend to all primary language buckets

**User Story:** As an operator, I want coverage checking for Python and Shell
sources too, not just Fortran.

#### Acceptance Criteria

1. THE check SHALL also report counts for `PythonModule`/`PythonFunction`,
   `ShellScript`, and `Module` (CMake) graph labels alongside the Fortran counts.
2. WHEN filesystem is available, THE check SHALL count `.py` files under `ush/` +
   `workflow/`, `.sh`/`.ksh` under `ush/` + `scripts/` + `jobs/`, and report
   vs their graph-node counterparts.
3. THE extension SHALL NOT block the base fix — it can land in a sub-task after
   the Fortran resolution is proven.

### Requirement 4: Output is pass/fail/warn, never SKIP

**User Story:** As an operator, I want the Coverage Gap row to always show a
definitive result (not hide behind SKIP).

#### Acceptance Criteria

1. THE Coverage Gap check SHALL output `[OK]`, `[WARN]`, or `[FAIL]` — never
   `[SKIP]`.
2. `[OK]`: graph node count ≥ threshold AND (if filesystem available) on-disk
   file count matches within 10% of graph count.
3. `[WARN]`: graph-only mode (no filesystem) with adequate count, or on-disk vs
   graph divergence > 10% but < 50%.
4. `[FAIL]`: graph node count = 0, or on-disk vs graph divergence > 50%.

### Requirement 5: Boundaries

#### Acceptance Criteria

1. THE feature SHALL NOT address the ChromaDB adapter parity (Phase 70) or the
   graph node-count scope documentation (Phase 73).
2. THE feature SHALL NOT add per-tenant coverage rollups (this phase covers the
   default tenant; per-tenant is a follow-up).
3. THE feature SHALL NOT auto-commit or auto-push.
4. ON `DB_BACKEND=aws`, THE feature's fallback path SHALL function (Neptune graph
   count, no filesystem) without regression.
