# Phase 72 — Fortran Coverage-Gap Path Fix

**Version**: 0.1.0
**Created**: 2026-07-20
**Status**: draft (requirement captured; not scheduled)
**Estimated effort**: TBD (scoping needed — small)
**Depends on**: Phase 61 (`configurable_workflow_mount_base`) for the
`workflow_root` catalog contract
**Kiro spec**: _(to be authored — `.kiro/specs/fortran-coverage-gap-path-fix/`)_
**Owner**: TBD

---

## 1. Executive Summary

`check_knowledge_integrity`'s **Coverage Gap** sub-check skips with:

```
[SKIP] no Fortran files found in /app/supported_repos/global-workflow
```

This is a **false negative**. The Neo4j graph for tenant `gw` currently holds
**80,745 FortranSubroutine nodes**, **16,849 FortranFunction nodes**, and
**9,014 FortranModule nodes** — all sourced from Fortran files that clearly
were present at ingest time.

The bug: the check hard-codes the pre-Phase-61 path
`/app/supported_repos/global-workflow`. Under the multi-tenant workflow-mount
model, source lives under `/app/.pw_workflow_mount/<subdir>` (e.g.
`/app/.pw_workflow_mount/develop` for tenant `gw`).

Observed on 2026-07-20 during the post-cutover full-sweep gap analysis (see
`supported_repos/global-workflow.wiki/agentcore-mcp-rag-Gap-Analysis-2026-07-20.md`,
Gap 3).

## 2. Scope

### 2.1 In Scope

- Resolve the Fortran-source root via `tenants.yaml` → `workflow_root` (or the
  equivalent field established in Phase 61) instead of hard-coding.
- Fall back to counting `Fortran*`-labeled nodes in the graph if the workflow
  mount is unavailable — this makes the check tenant-agnostic and works even
  when `.pw_workflow_mount` is not mounted (e.g. under AgentCore microVM).
- Extend the check to also cover the other primary language buckets in the
  graph: `PythonModule` / `PythonFunction`, `ShellScript`, `Module` (CMake).
- Update the tool's output row so `Coverage Gap` shows `pass`/`fail`/`warn`
  instead of `[SKIP]` on COTS.

### 2.2 Out of Scope

- ChromaDB adapter parity for the metadata sampler — that is Phase 70. This
  phase is the graph-side coverage-gap fix only.
- Nightly benchmark harness — that is Phase 71.
- Reporting per-tenant coverage rollups — this phase covers the default
  tenant. Per-tenant rollup is a follow-up.

## 3. Success Criteria

1. `check_knowledge_integrity` reports a non-`[SKIP]` outcome for the
   Coverage Gap check on tenant `gw`.
2. When run under a shell with `MCP_WORKFLOW_MOUNT` unset (simulating
   AgentCore), the fallback graph-based coverage still produces a numeric
   result.
3. Injecting a fake `.f90` file into `/app/.pw_workflow_mount/develop/sorc/`
   that lacks a corresponding `FortranModule` graph node produces a WARN row
   with the file path.
4. Removing all `Fortran*` nodes from Neo4j (simulated in a scratch DB)
   produces a FAIL row, not a SKIP.

## 4. Open Questions

- Should the fallback compare graph counts against a *declared* expected
  count from the manifest, or just report the counts and let the operator
  interpret? First cut: report counts + a threshold (e.g. WARN if < 100
  Fortran nodes total).
- Does the check need to distinguish between "no source on disk" (mount
  missing) vs "source on disk but not ingested"? Yes — different remediation
  paths.

## 5. Risks

- Un-skipping this check may cause the integrity report to change from
  "All checks passed" to "some checks failed" if there is real coverage
  drift. That is the desired outcome, but it will be a first-time surface
  and may need triage.

## 6. References

- Gap Analysis wiki: `supported_repos/global-workflow.wiki/agentcore-mcp-rag-Gap-Analysis-2026-07-20.md`
- Phase 61 spec: `sdd_framework/workflows/phase61_configurable_workflow_mount_base.md`
- Tool: `mcp_health_check` (surfaces the SKIP) and `check_knowledge_integrity`
  (owns the check)
- Tenant catalog: `mcp_server_python/src/config/tenants.yaml`
