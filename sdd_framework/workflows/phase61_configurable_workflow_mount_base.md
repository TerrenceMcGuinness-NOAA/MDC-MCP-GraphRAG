# Phase 61 — Configurable Workflow Mount Base (Parallel Works Filesystem Tools)

**Version**: 1.0.0
**Created**: 2026-06-25
**Status**: ready
**Estimated effort**: 1–2 hours

---

## Problem Statement

On the Parallel Works (Rocky 9) deployment the MCP server runs natively via
`mcp_server_python/scripts/run_mcp_stdio.sh` (stdio transport, no container,
no Docker MCP Gateway). The `mcp_health_check` "Workflow Filesystem" section
reports:

```
## Workflow Filesystem
- mount: /mnt/workflow (NOT mounted)
```

and every tenant row shows `workflow_root reachable: no (/mnt/workflow/...)`.

### Root cause

`Tenant.workflow_root` in `mcp_server_python/src/config/tenants.py` hardcodes
the AWS Bedrock AgentCore EFS mount point:

```python
@property
def workflow_root(self) -> Path:
    """Per-tenant absolute path on the AgentCore EFS mount (R2.7)."""
    return Path("/mnt/workflow") / self.workflow_subdir
```

`/mnt/workflow` is the EFS access-point mount that only exists on the
AgentCore runtime. On Parallel Works there is no EFS, so the path never
resolves and the filesystem-backed tools (WorkflowInfoTools:
`get_workflow_structure`, `list_job_scripts`, `get_job_details`,
`find_env_dependencies`, plus the `workflow_info` smoke probe) degrade.

The actual global-workflow worktrees **do** exist locally under
`supported_repos/`, but under different directory names than the catalog
`workflow_subdir` values:

| tenant | `workflow_subdir` | local checkout (`supported_repos/`) |
|--------|-------------------|--------------------------------------|
| gw | `develop` | `global-workflow` |
| gw_sfs | `dev-sfs` | `global-workflow_dev-sfs` |
| gw_jedi_gfs | `dev-jedi-gfs` | `global-workflow_dev-jedi-gfs` |
| gw_v17 | `dev-v17` | `global-workflow_dev-v17` |
| gw_gefs_v12 | `gefs-v12` | `global-workflow_gefs-v12` |

This is **not** a Docker Gateway problem — the gateway is not in the
native PW launch path. The fix is to make the mount base configurable so
PW can point it at a local directory while AgentCore keeps `/mnt/workflow`.

### Why Option B (configurable base) over a manual symlink farm

A symlink farm at `/mnt/workflow` (Option A) needs root to write under `/`,
is an out-of-band manual step that violates SPOT/IaC, and is fragile across
PW nodes. Making the base an env-overridable config field (Option B) keeps
the AgentCore default byte-identical, requires no root, and is reproducible.

---

## Design

### SPOT for the mount base

Introduce a single environment knob, **`MCP_WORKFLOW_MOUNT`**, defaulting to
`/mnt/workflow` (preserving AgentCore behaviour exactly). `Tenant.workflow_root`
reads it:

```python
import os

_DEFAULT_WORKFLOW_MOUNT = "/mnt/workflow"

@property
def workflow_root(self) -> Path:
    """Per-tenant absolute path under the configured workflow mount base.

    Base is ``MCP_WORKFLOW_MOUNT`` (default ``/mnt/workflow`` — the AWS
    Bedrock AgentCore EFS access-point mount). Native deployments
    (e.g. Parallel Works) override it to a local directory.
    """
    base = os.environ.get("MCP_WORKFLOW_MOUNT", _DEFAULT_WORKFLOW_MOUNT)
    return Path(base) / self.workflow_subdir
```

### Mapping local checkouts to catalog subdirs

Because `supported_repos/` checkout names differ from `workflow_subdir`,
`MCP_WORKFLOW_MOUNT` must point at a directory whose children match the
subdir names (`develop`, `dev-sfs`, `dev-jedi-gfs`, `dev-v17`, `gefs-v12`).

Provide a small, idempotent, **user-writable** symlink-farm bootstrap under
the repo (no root, no `/mnt`): default base
`${REPO_ROOT}/.pw_workflow_mount/` with symlinks:

```
.pw_workflow_mount/develop      -> supported_repos/global-workflow
.pw_workflow_mount/dev-sfs      -> supported_repos/global-workflow_dev-sfs
.pw_workflow_mount/dev-jedi-gfs -> supported_repos/global-workflow_dev-jedi-gfs
.pw_workflow_mount/dev-v17      -> supported_repos/global-workflow_dev-v17
.pw_workflow_mount/gefs-v12     -> supported_repos/global-workflow_gefs-v12
```

The catalog subdir → local-checkout mapping is itself a SPOT and lives in the
bootstrap script (single table), not scattered across docs.

### Wiring (SPOT defaults in the launcher)

`run_mcp_stdio.sh` (the SPOT for PW env defaults) exports:

```bash
export MCP_WORKFLOW_MOUNT="${MCP_WORKFLOW_MOUNT:-${REPO_ROOT}/.pw_workflow_mount}"
```

AgentCore Dockerfiles / `.bedrock_agentcore.yaml` set nothing (inherit the
`/mnt/workflow` default), so production is unchanged.

---

## Fixes Catalogue

| # | File | Change | Effort |
|---|------|--------|--------|
| F1 | `mcp_server_python/src/config/tenants.py` | `Tenant.workflow_root` reads `MCP_WORKFLOW_MOUNT` (default `/mnt/workflow`); add module-level `_DEFAULT_WORKFLOW_MOUNT` + `import os` | 15 min |
| F2 | `mcp_server_python/scripts/setup_pw_workflow_mount.sh` (new) | Idempotent bootstrap: create `${REPO_ROOT}/.pw_workflow_mount/` and the 5 subdir→`supported_repos/` symlinks; verify each target exists; ASCII `[OK]/[WARN]` output | 30 min |
| F3 | `mcp_server_python/scripts/run_mcp_stdio.sh` | Export `MCP_WORKFLOW_MOUNT` default (PW SPOT); document alongside existing `legacy` backend block | 10 min |
| F4 | `.gitignore` | Ignore `.pw_workflow_mount/` (machine-local symlink farm) | 2 min |
| F5 | `mcp_server_python/tests/unit/test_tenants.py` | Tests: default base is `/mnt/workflow`; `MCP_WORKFLOW_MOUNT` override changes `workflow_root`; subdir join correct; env unset restores default | 20 min |
| F6 | `CHANGELOG.md` | Add dated entry for the new env knob + PW mount bootstrap | 5 min |

---

## Steps

### Step 1 — Make `workflow_root` env-aware (F1)

Add `import os` and `_DEFAULT_WORKFLOW_MOUNT = "/mnt/workflow"` to
`tenants.py`; update the `workflow_root` property to read
`MCP_WORKFLOW_MOUNT`. No behaviour change when the env var is unset.

**Test**: `python -c` snippet — with env unset, `Tenant(...).workflow_root`
== `/mnt/workflow/develop`; with `MCP_WORKFLOW_MOUNT=/tmp/x`, ==
`/tmp/x/develop`.

---

### Step 2 — Add the PW symlink-farm bootstrap (F2)

Create `setup_pw_workflow_mount.sh`. It holds the single subdir→checkout
mapping table, creates `${REPO_ROOT}/.pw_workflow_mount/`, makes each
symlink (idempotent — `ln -sfn`), and warns (non-fatal) for any missing
`supported_repos/` target. No root required; never writes under `/mnt`.

**Test**: run the script; `ls -l .pw_workflow_mount/` shows 5 valid
symlinks; re-running is a no-op (no errors, no duplicates).

---

### Step 3 — Wire the launcher default (F3 + F4)

Export `MCP_WORKFLOW_MOUNT` default in `run_mcp_stdio.sh` pointing at the
bootstrap dir. Add `.pw_workflow_mount/` to `.gitignore`.

**Test**: `source run_mcp_stdio.sh`-equivalent env check shows
`MCP_WORKFLOW_MOUNT` set; AgentCore path (env preset to `/mnt/workflow`
or unset in container) is unaffected.

---

### Step 4 — Unit tests (F5)

Add `test_tenants.py` cases covering default base, override, subdir join,
and env-unset restoration (use `monkeypatch.setenv` / `delenv`).

**Test**: `python -m pytest tests/unit/test_tenants.py -q` green.

---

### Step 5 — Validate end-to-end (F2 + F1 + F3)

Run the bootstrap, restart the MCP server, and call `mcp_health_check`.

**Acceptance**:
- "Workflow Filesystem" mount line resolves (not "NOT mounted").
- Tenant table `workflow_root reachable` shows `yes` for tenants whose
  `supported_repos/` checkout is present.
- `get_workflow_structure` / `list_job_scripts` return real data for the
  default `gw` tenant.
- AgentCore production behaviour unchanged (default `/mnt/workflow`).

---

### Step 6 — Changelog (F6)

Add a dated `CHANGELOG.md` entry: new `MCP_WORKFLOW_MOUNT` env knob,
`setup_pw_workflow_mount.sh`, PW filesystem-tool enablement; note the
AgentCore default is preserved.

---

## Out of Scope

- Renaming `supported_repos/` checkouts to match `workflow_subdir`
  (the symlink farm is intentionally non-destructive).
- Any change to the AWS/AgentCore EFS mount or Dockerfiles.
- Write-path tools — this phase only restores the read-path filesystem
  tools.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Override accidentally set in AgentCore image | Default stays `/mnt/workflow`; Dockerfiles set nothing — verified in F3 test |
| Stale symlinks after a checkout is removed | Bootstrap is idempotent and re-run cheaply; missing targets warn, don't fail |
| Subdir/checkout mapping drift | Mapping is a single SPOT table inside the bootstrap script |
