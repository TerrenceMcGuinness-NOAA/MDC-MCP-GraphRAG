# populate_workflow_efs.sh

Multi-tenant EFS worktree provisioning script for the AgentCore MCP/RAG
runtime. Reads `tenants.yaml` and creates one git worktree per tenant
under the EFS access-point root.

## Pattern: Bare Repo + Worktrees

A single bare clone of `NOAA-EMC/global-workflow.git` lives at
`<EFS>/.git` (outside the access-point root, invisible to the runtime).
Each tenant gets a worktree under
`<EFS>/supported_repos/global-workflow/<workflow_subdir>`. Worktrees
share the bare repo's object store, so adding a tenant costs only the
working-tree files (~few hundred MB), not another full clone (~1.3 GB).

## FETCH_HEAD Lesson (Phase 0)

Bare-repo worktrees do **not** populate `refs/remotes/origin/*`, so
`git pull` fails with "no tracking information." The correct update
pattern is:

```bash
git -C <worktree> fetch origin <branch>
git -C <worktree> merge --ff-only FETCH_HEAD
```

The fetch must run from the **worktree directory** (not the bare repo)
so that `FETCH_HEAD` lands in the worktree's gitdir.

## Idempotency Contract (R2.4)

- Re-running with no catalog change → no-op (fetch + ff-only).
- Adding a new tenant row → provisions only the new worktree.
- Removing a tenant row → does **NOT** delete its worktree. Worktree
  removal is an explicit operator step:
  ```bash
  git -C /mnt/efs-staging/.git worktree remove \
      /mnt/efs-staging/supported_repos/global-workflow/<subdir>
  ```

## Required Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `EFS_FS_ID` | `fs-032d52e4677000758` | EFS file system ID |
| `STAGING_MNT` | `/mnt/efs-staging` | Operator-host mount point |
| `GW_REMOTE` | `https://github.com/NOAA-EMC/global-workflow.git` | Remote URL |
| `TENANTS_YAML` | `mcp_server_python/src/config/tenants.yaml` | Catalog path |

## Prerequisites

- `amazon-efs-utils` installed (provides `mount.efs`)
- `python3.12` + `PyYAML` available
- sudo privileges
- EFS security group allows TCP 2049 from operator host

## Testable Python Helper

The git worktree logic is extracted into `_populate_worktrees.py` so
property tests can drive it directly against tmp_path bare repos
without sudo/mount. The shell script handles mount/umount/sudo/chown
and delegates git operations to this module.

## Cross-References

- Foundation Phase 0 closeout: `CHANGELOG.md [8.22.3]`
- Foundation spec: `.kiro/specs/omd-tenants-1-foundation/tasks.md §0.3`
- Phase 0 script (rollback reference): `populate_workflow_efs_phase0.sh`
