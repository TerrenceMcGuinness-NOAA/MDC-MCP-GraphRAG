# Implementation Plan: Fortran Coverage-Gap Path Fix

## Overview

Fix the Coverage Gap sub-check's hard-coded path; add graph-based fallback;
extend to multi-language coverage.

## Tasks

- [ ] 1. Fix the Fortran path resolution
  - [ ] 1.1 Replace the hard-coded `/app/supported_repos/global-workflow` with `tenant_ctx.workflow_root` (from the active tenant context); honor `MCP_WORKFLOW_MOUNT` override
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ] 1.2 Add the graph-based fallback: when `workflow_root` doesn't exist, count `Fortran*`-labeled nodes in the graph; `[OK]` > 100, `[WARN]` 1-100, `[FAIL]` 0
    - _Requirements: 2.1, 2.2, 2.3_
  - [ ] 1.3 Ensure the output is always `[OK]`/`[WARN]`/`[FAIL]` — never `[SKIP]`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 2. Cross-reference mode (filesystem + graph)
  - [ ] 2.1 When filesystem is available, count `.f90`/`.F90`/`.f`/`.F` under `sorc/`; compare vs graph Fortran node sum; apply divergence thresholds (< 10% OK, 10-50% WARN, > 50% FAIL)
    - _Requirements: 1.2, 4.2, 4.3, 4.4_

- [ ] 3. Multi-language extension
  - [ ] 3.1 Add Python coverage: `.py` under `ush/` + `workflow/` vs `PythonModule` + `PythonFunction` graph labels
    - _Requirements: 3.1, 3.2_
  - [ ] 3.2 Add Shell coverage: `.sh`/`.ksh` under `ush/` + `scripts/` + `jobs/` vs `ShellScript` graph labels
    - _Requirements: 3.1, 3.2_
  - [ ] 3.3 Format output as per-language rows in the Coverage Gap section
    - _Requirements: 3.1_

- [ ] 4. Testing
  - [ ] 4.1 Unit test: tenant-resolved path with mock filesystem + graph counts → correct OK/WARN/FAIL outcomes; absent path triggers graph-only fallback
    - _Requirements: 2.1, 4.1_
  - [ ] 4.2 Functional (COTS): `check_knowledge_integrity` → Coverage Gap `[OK]` with real Fortran count
  - [ ] 4.3 Functional (AWS): Coverage Gap `[OK] (graph-only)` using Neptune counts (no EFS on EC2)
    - _Requirements: 5.4_

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
