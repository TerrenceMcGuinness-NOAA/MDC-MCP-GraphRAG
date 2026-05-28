"""Worktree management logic for multi-tenant EFS population.

Extracted from populate_workflow_efs.sh so property tests can drive
the git operations directly against tmp_path bare repos without
sudo/mount.

The shell script calls this module for the git worktree operations;
it handles mount/umount/sudo/chown itself.

Implements: Requirements 2.1, 2.2, 2.3, 2.4 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run git with safe.directory='*' to bypass ownership checks."""
    cmd = ["git", "-c", "safe.directory=*"] + args
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _worktree_exists(bare_repo: Path, target: Path) -> bool:
    """Check if a worktree is already registered at target."""
    result = _git(["worktree", "list", "--porcelain"], cwd=bare_repo)
    return f"worktree {target}\n" in result.stdout


def add_or_update_worktree(
    bare_repo: Path, target: Path, branch: str, *, init_submodules: bool = True
) -> None:
    """Add a new worktree or fast-forward an existing one.

    For existing worktrees: fetch origin <branch> from the worktree
    directory (so FETCH_HEAD lands in the worktree's gitdir), then
    merge --ff-only FETCH_HEAD. This is the Phase 0 lesson: bare-repo
    worktrees lack refs/remotes/origin/*, so `git pull` fails.

    For new worktrees: `git worktree add <target> <branch>`.

    When ``init_submodules`` is True (default), runs
    ``git submodule update --init --recursive`` after create/update
    so the full source tree (sorc/ufs_model, sorc/gsi, etc.) is
    available for code ingestion and graph traversal tools
    (find_dependencies, find_callers_callees, trace_execution_path).
    """
    if _worktree_exists(bare_repo, target):
        # Update: fetch + merge from the worktree directory
        _git(["fetch", "origin", branch], cwd=target)
        _git(["merge", "--ff-only", "FETCH_HEAD"], cwd=target)
    else:
        # Create
        _git(["worktree", "add", str(target), branch], cwd=bare_repo)

    # Initialize submodules so the full dependency tree is on disk.
    # Each branch pins its own submodule SHAs (different UFS, FV3, GSI
    # versions per tenant), so this must run per-worktree.
    # --depth 1: only the pinned SHA's tree, no history (saves ~50% disk).
    if init_submodules:
        _git(["submodule", "update", "--init", "--recursive", "--depth", "1"], cwd=target)


def populate_all(
    bare_repo: Path,
    ap_root: Path,
    tenants: list[dict],
) -> None:
    """Create or update one worktree per tenant under ap_root.

    Does NOT remove worktrees for tenants absent from the catalog
    (per design §1 idempotency contract — removal is an explicit
    operator step).

    Parameters
    ----------
    bare_repo : Path
        Path to the bare git repository (e.g. <EFS>/.git).
    ap_root : Path
        Access-point root (e.g. <EFS>/supported_repos/global-workflow).
    tenants : list[dict]
        Each dict has keys: tenant_id, workflow_subdir, branch.
    """
    for t in tenants:
        target = ap_root / t["workflow_subdir"]
        add_or_update_worktree(bare_repo, target, t["branch"])
