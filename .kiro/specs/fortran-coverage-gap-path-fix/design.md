# Design Document

## Overview

Fix the `check_knowledge_integrity` Coverage Gap sub-check so it resolves the
source-tree path from the tenant catalog instead of a hard-coded stale path, adds
a graph-based fallback for hosts without the workflow mount, and extends coverage
to all primary language buckets.

## Current behavior (broken)

```python
# semantic_search.py :: _check_coverage_gap()
fortran_root = Path("/app/supported_repos/global-workflow/sorc")
#                   ^^^^^^^^^^^ hard-coded, stale since Phase 61/67
if not fortran_root.exists():
    return "[SKIP] no Fortran files found in /app/supported_repos/global-workflow"
```

## Proposed behavior

```python
def _check_coverage_gap(tenant_ctx, graph_db):
    root = tenant_ctx.workflow_root / "sorc" if tenant_ctx else None

    # Path 1: filesystem + graph cross-reference
    if root and root.exists():
        on_disk = count_fortran_files(root)
        in_graph = graph_db.count_by_label("FortranSubroutine") + \
                   graph_db.count_by_label("FortranFunction") + \
                   graph_db.count_by_label("FortranModule")
        divergence = abs(on_disk - in_graph) / max(on_disk, 1)
        if divergence < 0.10:
            return f"[OK] {in_graph} Fortran nodes, {on_disk} files (divergence {divergence:.0%})"
        elif divergence < 0.50:
            return f"[WARN] divergence {divergence:.0%} ({in_graph} graph vs {on_disk} disk)"
        else:
            return f"[FAIL] divergence {divergence:.0%} ({in_graph} graph vs {on_disk} disk)"

    # Path 2: graph-only fallback (no filesystem)
    in_graph = graph_db.count_by_label("FortranSubroutine") + \
               graph_db.count_by_label("FortranFunction") + \
               graph_db.count_by_label("FortranModule")
    if in_graph > 100:
        return f"[OK] {in_graph} Fortran nodes (graph-only; filesystem not mounted)"
    elif in_graph > 0:
        return f"[WARN] only {in_graph} Fortran nodes (graph-only; filesystem not mounted)"
    else:
        return f"[FAIL] 0 Fortran nodes in graph"
```

## Extension: multi-language coverage

After the base Fortran fix lands, extend with the same pattern for:

| Language | On-disk path | Graph labels |
|---|---|---|
| Fortran | `sorc/**/*.{f90,F90,f,F}` | `FortranSubroutine`, `FortranFunction`, `FortranModule`, `FortranProgram` |
| Python | `ush/**/*.py`, `workflow/**/*.py` | `PythonModule`, `PythonFunction` |
| Shell | `ush/**/*.sh`, `scripts/**/*.sh`, `jobs/**` | `ShellScript` |

Output: a per-language row in the Coverage Gap section (not one monolithic line).

## Files changed

- `mcp_server_python/src/tools/semantic_search.py` — `_check_coverage_gap()`
  rewrite (tenant-resolved path + graph fallback)
- Potentially `mcp_server_python/src/tools/smoke_queries.py` if the `workflow_info`
  functional probe references the same hard-coded path

## Testing

- Unit: mock `tenant_ctx.workflow_root` as a `tmp_path` with 5 `.f90` files;
  mock `graph_db.count_by_label` returning 5 → `[OK]`; returning 50 (10× disk) →
  `[FAIL]`; `workflow_root` absent + graph returns 500 → `[OK] (graph-only)`;
  graph returns 0 → `[FAIL]`.
- Functional (COTS): `check_knowledge_integrity` → Coverage Gap shows `[OK]`
  with a real count (not `[SKIP]`).
- Functional (AWS/AgentCore): Coverage Gap shows `[OK] (graph-only)` with
  Neptune node counts (no filesystem on EC2).
