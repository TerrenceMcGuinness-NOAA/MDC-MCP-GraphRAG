# Implementation Plan: Fortran Coverage-Gap Path Fix

## Overview

Fix the Coverage Gap sub-check's hard-coded path; add graph-based fallback;
extend to multi-language coverage.

## Tasks

- [x] 1. Fix the Fortran path resolution
  - [x] 1.1 Resolve source root via the active tenant's `repo_base` (Phase-61 `workflow_root`, honoring `MCP_WORKFLOW_MOUNT` via `_resolve_repo_base_with_tenant`); count under `<repo_base>/sorc/`. Also fixed the missing `tenant=` kwarg on the graph count query (was global before Phase 72)
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.2 Graph-based fallback: when the source dir isn't present, count `Fortran*` nodes; `[OK]` > 100, `[WARN]` 1-100, `[FAIL]` 0
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 1.3 Output is always `[OK]`/`[WARN]`/`[FAIL]` — never `[SKIP]` (the `disk_count==0 → [SKIP]` branch is removed)
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 2. Cross-reference mode (filesystem + graph)
  - [x] 2.1 When the source dir is present, count sources and compare to the tenant-scoped graph node sum. **Deviation**: the draft's file-vs-symbol percentage "divergence" is a scale mismatch (one .f90 defines many subroutines → always huge), so it is replaced with the sound signal `graph_nodes >= source_files` → `[OK]`; `0 < nodes < files` → `[WARN]` (partial coverage); files present but `0` nodes → `[FAIL]`
    - _Requirements: 1.2, 4.2, 4.3, 4.4_

- [x] 3. Multi-language extension
  - [x] 3.1 Python coverage: `.py` under `ush/` + `workflow/` vs `PythonModule` + `PythonFunction`
    - _Requirements: 3.1, 3.2_
  - [x] 3.2 Shell coverage: `.sh`/`.ksh` under `ush/` + `scripts/` + `jobs/` vs `ShellScript`
    - _Requirements: 3.1, 3.2_
  - [x] 3.3 Output is one `_Check` row per language ("Coverage Gap (Fortran|Python|Shell)"); `_check_coverage_gap` returns `list[_Check]`, integrity tool `extend`s them
    - _Requirements: 3.1_

- [x] 4. Testing
  - [x] 4.1 Unit tests (`tests/unit/test_coverage_gap_multilang.py`, 10 tests): tenant-resolved path + mock fs + graph counts → OK/WARN/FAIL; absent path → graph-only fallback; tenant-scoping asserted; never-SKIP; 3 per-language rows. Updated the obsolete SKIP test in `test_semantic_search_tools.py` to assert the graph-only fallback.
    - _Requirements: 2.1, 4.1_
  - [x] 4.2 Functional (COTS, live Neo4j + `.pw_workflow_mount/develop`): `Coverage Gap (Fortran)` → `[OK] 107794 Fortran nodes for 7242 files under sorc/`; Python `[OK] 8607 nodes/41 files`; Shell `[OK] 589 nodes/114 files`; **no `[SKIP]`**
  - [x] 4.3 Functional (graph-only fallback, live Neo4j, nonexistent repo): `Coverage Gap (Fortran)` → `[OK] 107794 Fortran nodes (graph-only; filesystem not mounted)` — the AWS/AgentCore no-filesystem path
    - _Requirements: 5.4_

## Verification status

- **Unit**: full suite 1322 passed / 26 failed (all 26 pre-existing: opensearch-py
  absent + stale assertions; 0 regressions; was 1311/26 after Phase 70). 10 new
  coverage tests pass.
- **Live functional**: verified read-only against Neo4j (bolt://localhost:7687)
  and the develop worktree — see 4.2 / 4.3 above.

## Deviation from the draft design (intentional, sound)

The draft's `divergence = |on_disk_files - in_graph_symbols| / on_disk_files`
compared file counts to symbol counts (different scales), which is always a huge
"divergence" and would falsely FAIL every language. Replaced with
`graph_nodes >= source_files → OK`, `0 < nodes < files → WARN`,
`files present & 0 nodes → FAIL`, plus the graph-only fallback for no-filesystem
hosts. This honors the requirement intent (OK/WARN/FAIL gradation, never SKIP)
with a metric that is meaningful across Fortran/Python/Shell.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] }
  ]
}
```
