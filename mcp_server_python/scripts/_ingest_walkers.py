"""File enumeration helpers for tenant-aware ingestion.

Provides two strategies:
- files_for_full_branch: all files under a worktree (excluding .git/)
- files_for_diff: only files changed vs a baseline branch

Implements: Requirements 3.2, 3.3 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator


def files_for_full_branch(worktree_root: Path) -> Iterator[Path]:
    """All files under the worktree, excluding .git/ and operator artefacts."""
    for p in worktree_root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            yield p


def files_for_diff(
    worktree_root: Path, baseline_branch: str = "develop"
) -> Iterator[Path]:
    """Files changed between baseline and HEAD, mapped onto worktree paths.

    Uses ``git diff --name-only <baseline>..HEAD`` with a 30s timeout
    to guard against corrupt indices on remote-hosted repos.
    """
    out = subprocess.check_output(
        ["git", "-C", str(worktree_root), "diff", "--name-only",
         f"{baseline_branch}..HEAD"],
        text=True,
        timeout=30,
    )
    for rel in filter(None, (line.strip() for line in out.splitlines())):
        p = worktree_root / rel
        if p.is_file():
            yield p
