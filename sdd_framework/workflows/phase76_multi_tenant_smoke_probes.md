# Phase 76: Multi-Tenant Smoke Probes

**Status**: DESIGN
**Created**: 2026-08-10
**Session**: phase76_multi_tenant_smoke_probes

## Motivation

The `workflow_info` functional smoke probe only validates the default tenant's
filesystem (via `MCP_WORKFLOW_ROOT`). If a non-default tenant's EFS worktree
is missing or corrupted, nothing catches it until a user hits a query failure.

Additionally, there is no mechanism to detect when a tenant's worktree has
drifted from its branch's remote HEAD — stale worktrees mean stale ingestion
data and stale query results.

These are two separate concerns (SoC):

1. **Per-tenant filesystem validation** — real-time smoke probe (fast, side-effect-free)
2. **Worktree staleness detection** — periodic scheduled check (may need network access to git remote)

Both read from the same SPOT: `tenants.yaml`.

## SPOT: `tenants.yaml` (Single Point of Truth)

Path: `mcp_server_python/src/config/tenants.yaml`

The tenant catalog already defines everything both probes need:

| Field | Used by | Purpose |
|-------|---------|---------|
| `tenant_id` | Both | Identity |
| `workflow_subdir` | Both | Filesystem path under `MCP_WORKFLOW_MOUNT` |
| `repo_ref` | Staleness | Which git remote to compare against |
| `branch` | Staleness | Which branch HEAD to compare |
| `lifecycle` | Both | Skip `experimental` tenants in staleness alerts |
| `staleness_threshold_days` | Staleness | (catalog defaults) max age before flagging |

### Extensibility — non-global-workflow tenants

Adding a tenant like MPAS requires only a new catalog entry:

```yaml
  - tenant_id: mpas
    repo_ref: NCAR/MPAS-Model
    branch: develop
    index_prefix: "mpas_"
    label_prefix: "MPAS_"
    workflow_subdir: mpas-model
    lifecycle: experimental
    description: "MPAS-Atmosphere unstructured mesh dynamical core."
    extends: []
```

No code changes. The probes iterate the catalog dynamically.

The filesystem validation needs a way to know what "sound" means per tenant.
Global-workflow tenants have `dev/jobs/` or `jobs/`. A non-global-workflow
tenant (MPAS, JEDI, etc.) might not have `jobs/` at all. Solution: an optional
`health_check_path` field in the tenant entry:

```yaml
    health_check_path: "src"  # just check this subdir exists
```

Default (when absent): `dev/jobs` for `repo_ref: NOAA-EMC/global-workflow`,
else just check the root dir exists.

---

## Concern 1: Per-Tenant Filesystem Validation (Smoke Probe)

### Requirements

1. The probe SHALL iterate all tenants from the catalog (not hardcoded).
2. For each tenant, it SHALL resolve `workflow_root` via the tenant model
   (`MCP_WORKFLOW_MOUNT / workflow_subdir`).
3. For global-workflow tenants (`repo_ref` starts with `NOAA-EMC/global-workflow`),
   it SHALL check that `dev/jobs/` or `jobs/` exists.
4. For non-global-workflow tenants, it SHALL check that `health_check_path`
   exists (if specified), else that the root dir itself exists.
5. The probe SHALL report per-tenant status (pass/skip/fail) in the
   Functional Validation output.
6. A single tenant failing SHALL NOT block other tenants from being checked.
7. Tenants whose `workflow_root` does not exist SHALL report SKIP (not FAIL)
   — consistent with the "not provisioned" convention.
8. Total probe latency SHALL remain under 100ms (filesystem stat calls only).

### Design

Replace the current `_smoke_workflow_info` (which checks one path) with
`_smoke_workflow_info_all_tenants`:

```python
async def _smoke_workflow_info(_data: Any, _mcp: Any) -> bool:
    """Validate all tenant worktrees are sound."""
    from src.config.tenants import load_tenant_catalog

    catalog = load_tenant_catalog()
    results = []

    for tenant in catalog.tenants:
        root = tenant.workflow_root
        if not root.exists():
            results.append((tenant.tenant_id, "skip", "not mounted"))
            continue
        check_path = _resolve_health_check_path(tenant)
        if check_path.exists():
            results.append((tenant.tenant_id, "pass", None))
        else:
            results.append((tenant.tenant_id, "fail", f"{check_path} missing"))

    failed = [r for r in results if r[1] == "fail"]
    if failed:
        raise RuntimeError(
            f"Tenant worktree failures: {', '.join(f[0] for f in failed)}"
        )
    if all(r[1] == "skip" for r in results):
        raise SkipProbe("No tenant worktrees mounted")
    return True
```

### Integration point

Same slot as today's `workflow_info` module in `SmokeQueryRegistry.QUERIES`.
The description changes from "MCP_WORKFLOW_ROOT/jobs or /dev/jobs is a directory"
to "All tenant worktrees have expected structure".

---

## Concern 2: Worktree Staleness Detection (Scheduled Monitor)

### Requirements

1. The monitor SHALL compare each tenant's worktree HEAD against its
   branch's remote HEAD (via `git ls-remote`).
2. If the worktree is behind by more than `staleness_threshold_days`
   (from catalog defaults), the tenant SHALL be flagged as stale.
3. The monitor SHALL also check submodule state: `git submodule status`
   in the worktree, flagging any submodule with a `-` prefix (not initialized)
   or where the committed SHA differs from the checked-out SHA.
4. Output SHALL be a JSON report suitable for consumption by a health
   dashboard or alerting system.
5. The monitor SHALL NOT modify the worktree (read-only).
6. Tenants with `lifecycle: experimental` SHALL be reported but not
   treated as critical alerts.
7. The monitor SHALL be runnable as a standalone CLI script:
   `python3 scripts/check_tenant_staleness.py [--tenant <id>] [--json]`

### Design

Standalone script: `mcp_server_python/scripts/check_tenant_staleness.py`

```python
def check_staleness(tenant) -> TenantStalenessReport:
    worktree = tenant.workflow_root
    if not worktree.exists():
        return TenantStalenessReport(tenant_id=..., status="absent")

    # Compare local HEAD vs remote HEAD
    local_head = run(["git", "-C", str(worktree), "rev-parse", "HEAD"])
    remote_head = run(["git", "ls-remote", remote_url, tenant.branch])

    # Check submodule state
    sub_status = run(["git", "-C", str(worktree), "submodule", "status"])
    # Parse for uninitialized (-) or SHA mismatch (+)

    return TenantStalenessReport(
        tenant_id=tenant.tenant_id,
        local_head=local_head,
        remote_head=remote_head,
        behind_commits=...,
        stale=(days_behind > threshold),
        submodules_ok=...,
    )
```

### Integration point

- NOT a real-time smoke probe (too slow, needs network).
- Tier C scheduled consumer — cron or systemd timer on the dev host.
- Could also be wired into the health check as an optional `--staleness`
  deep mode if the latency budget allows (5-15s per tenant with network).

---

## Implementation Steps

| # | Step | Tag | Concern |
|---|------|-----|---------|
| 1 | Research: confirm smoke probe shape, catalog loader, existing tests | research | both |
| 2 | Design: finalize `health_check_path` schema addition to tenants.yaml | design | 1 |
| 3 | Implement: `_smoke_workflow_info_all_tenants` in smoke_queries.py | implement | 1 |
| 4 | Validate: run mcp_health_check(functional=True), confirm per-tenant output | validate | 1 |
| 5 | Design: staleness monitor CLI shape, output format | design | 2 |
| 6 | Implement: `scripts/check_tenant_staleness.py` | implement | 2 |
| 7 | Validate: run staleness check against live worktrees | validate | 2 |
| 8 | Document: update steering + CHANGELOG | document | both |

## Dependencies

- `tenants.yaml` schema (may need `health_check_path` optional field — schema_version bump)
- `load_tenant_catalog()` function in `src/config/tenants.py`
- EFS mount with all tenant worktrees present (already provisioned)
- Network access to git remotes (staleness monitor only)

## Rollback

Concern 1 is a drop-in replacement for the existing `workflow_info` probe.
Rollback: revert to the single-path check.

Concern 2 is a new standalone script. Rollback: delete the script.
