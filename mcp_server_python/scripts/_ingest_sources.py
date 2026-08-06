"""Documentation source-set resolution + disk-priority consistency gate.

disk-priority-ingest, Requirements 1 and 2.

Pure functions only — no writes to the vector store — so this module is unit
testable and reusable by ``validate_manifest_paths.py``. It answers two
questions for the documentation ingester:

1. *Which files* constitute the documentation set (an explicit, manifest-driven
   set scoped by an extension allowlist), replacing the whole-worktree walk that
   ``files_for_full_branch`` performs (blocking defect 1).
2. *Should a source be read from disk or refreshed by the crawler* — the
   disk-priority resolution with a consistency gate (:func:`probe_local`).

Only ``git`` subprocesses touch the filesystem's VCS state; each is wrapped with
the same 30 s timeout used by ``files_for_diff``.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Default documentation extension allowlist (Req 1.3): .rst / .md / .txt plus
# the doc formats present under a tenant's docs/ tree. Source-code extensions
# are deliberately excluded so the shared docs collection never ingests code.
DEFAULT_DOC_EXTENSIONS: tuple[str, ...] = (".rst", ".md", ".txt")

# Source types in the unified manifest that represent documentation the doc
# ingester is responsible for.
_DOC_SOURCE_TYPES = frozenset({"url_crawl", "on_disk_submodule"})

# git subprocess timeout, matching the guard in files_for_diff.
_GIT_TIMEOUT = 30

# Probe reasons, in specificity order (most specific first). See probe_local.
REASON_OK = "ok"
REASON_PATH_ABSENT = "path_absent"
REASON_MANIFEST_DEFECT = "manifest_defect"
REASON_PATH_EMPTY = "path_empty"
REASON_BELOW_MIN_FILES = "below_min_files"
REASON_SUBMODULE_OFF_PIN = "submodule_off_pin"
REASON_WORKTREE_DIRTY = "worktree_dirty"

DISPOSITION_DISK = "disk"
DISPOSITION_NEEDS_CRAWL = "needs_crawl"


@dataclass(frozen=True)
class DocSource:
    """One documentation source declared in the unified manifest."""

    name: str
    url: str | None
    local_path: str | None
    min_files: int
    extensions: tuple[str, ...]


@dataclass(frozen=True)
class LocalProbe:
    """Result of probing a source's on-disk copy for disk-priority use."""

    usable: bool
    reason: str
    resolved_path: Path | None
    commit_sha: str | None
    dirty: bool


@dataclass(frozen=True)
class SourceDecision:
    """Per-source disposition emitted by resolve_doc_file_set (one per source)."""

    name: str
    disposition: str  # DISPOSITION_DISK | DISPOSITION_NEEDS_CRAWL
    reason: str
    file_count: int = 0
    commit_sha: str | None = None
    dirty: bool = False
    resolved_path: str | None = None


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def _extensions_from_patterns(patterns: Iterable[str]) -> tuple[str, ...]:
    """Derive a suffix allowlist from manifest ``file_patterns`` globs.

    A pattern like ``**/*.rst`` yields ``.rst``. Patterns without a usable
    suffix are ignored. Falls back to the default doc allowlist if nothing
    usable is found.
    """
    exts: list[str] = []
    for pat in patterns:
        suffix = Path(pat).suffix.lower()
        if suffix and "*" not in suffix:
            exts.append(suffix)
    return tuple(dict.fromkeys(exts)) or DEFAULT_DOC_EXTENSIONS


def load_doc_sources(manifest_path: str | Path) -> list[DocSource]:
    """Load documentation sources from the unified manifest.

    Selects enabled sources whose ``source_type`` is a documentation type
    (``url_crawl`` or ``on_disk_submodule``). Each source's extension allowlist
    comes from its ``file_patterns`` when present, else the default doc
    allowlist. ``min_files`` defaults to 0 when absent so a source without a
    declared floor can never trip ``below_min_files``.
    """
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    sources: list[DocSource] = []
    for s in data.get("sources", []):
        if s.get("source_type") not in _DOC_SOURCE_TYPES:
            continue
        if s.get("enabled") is False:
            continue
        patterns = s.get("file_patterns")
        extensions = (
            _extensions_from_patterns(patterns) if patterns else DEFAULT_DOC_EXTENSIONS
        )
        sources.append(
            DocSource(
                name=s["name"],
                url=s.get("url"),
                local_path=s.get("local_path"),
                min_files=int(s.get("min_files", 0)),
                extensions=extensions,
            )
        )
    return sources


# ---------------------------------------------------------------------------
# git helpers (timeout-guarded, never raise)
# ---------------------------------------------------------------------------


def _git(args: list[str]) -> str | None:
    """Run a git command, returning stripped stdout or None on any failure."""
    try:
        out = subprocess.run(
            ["git", *args],
            text=True,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _ls_tree_entry(worktree_root: Path, local_path: str) -> tuple[str, str] | None:
    """Return ``(type, sha)`` for ``local_path`` in the superproject HEAD tree.

    ``type`` is ``commit`` for a submodule gitlink, ``tree`` for a directory.
    Returns None if the path is not present in HEAD.
    """
    out = _git(["-C", str(worktree_root), "ls-tree", "HEAD", local_path])
    if not out:
        return None
    # Format: "<mode> <type> <sha>\t<path>"
    meta = out.split("\t", 1)[0].split()
    if len(meta) < 3:
        return None
    return meta[1], meta[2]


def _count_files(root: Path) -> int:
    """Count regular files under ``root`` excluding any ``.git`` directory."""
    n = 0
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def _resolve_candidate(
    local_path: str, worktree_root: Path, repo_root: Path | None
) -> Path:
    """Resolve a local_path to a concrete dir.

    Primary base is the worktree root (submodule / docs paths). Falls back to
    the repo root for the transitional ``supported_repos/...`` form before the
    manifest is made worktree-relative (Req 4.2).
    """
    cand = worktree_root / local_path
    if not cand.exists() and repo_root is not None:
        alt = repo_root / local_path
        if alt.exists():
            return alt
    return cand


def probe_local(
    source: DocSource, worktree_root: Path, repo_root: Path | None = None
) -> LocalProbe:
    """Probe a source's on-disk copy, returning the most specific reason.

    Specificity order: manifest_defect (the declared path does not resolve at
    all — Task 5e.c) -> path_empty -> below_min_files -> submodule_off_pin ->
    worktree_dirty -> ok.
    """
    if source.local_path is None:
        return LocalProbe(False, REASON_PATH_ABSENT, None, None, False)

    local_path = source.local_path
    candidate = _resolve_candidate(local_path, worktree_root, repo_root)

    # 1. Absent — a declared local_path that does not resolve is a manifest
    #    defect, regardless of whether .gitmodules knows the path (Task 5e.c).
    #    The ingester still degrades this source to needs_crawl; the validator
    #    treats it as a hard failure. This closes the hole that let the four
    #    stale coupled-model paths pass as path_absent.
    if not candidate.exists():
        return LocalProbe(False, REASON_MANIFEST_DEFECT, None, None, False)

    # 2. Determine submodule vs plain directory via the superproject tree entry.
    entry = _ls_tree_entry(worktree_root, local_path)
    is_submodule = entry is not None and entry[0] == "commit"

    # 3. Empty.
    total_files = _count_files(candidate)
    if total_files == 0:
        return LocalProbe(False, REASON_PATH_EMPTY, candidate, None, False)

    # 4. Below the per-source population floor.
    if total_files < source.min_files:
        return LocalProbe(False, REASON_BELOW_MIN_FILES, candidate, None, False)

    # 5. Pin + dirty checks. Only meaningful for a submodule gitlink; a plain
    #    directory in the superproject cannot be "off pin".
    if is_submodule:
        gitlink_sha = entry[1]
        checked_out = _git(["-C", str(candidate), "rev-parse", "HEAD"])
        commit_sha = checked_out or gitlink_sha
        if checked_out is not None and gitlink_sha is not None and checked_out != gitlink_sha:
            return LocalProbe(False, REASON_SUBMODULE_OFF_PIN, candidate, commit_sha, False)
        status = _git(["-C", str(candidate), "status", "--porcelain"])
    else:
        commit_sha = _git(["-C", str(worktree_root), "rev-parse", "HEAD"])
        status = _git(["-C", str(worktree_root), "status", "--porcelain", "--", local_path])

    dirty = bool(status)
    if dirty:
        return LocalProbe(False, REASON_WORKTREE_DIRTY, candidate, commit_sha, True)

    return LocalProbe(True, REASON_OK, candidate, commit_sha, False)


# ---------------------------------------------------------------------------
# Source-set resolution
# ---------------------------------------------------------------------------


def _collect_doc_files(root: Path, extensions: tuple[str, ...]) -> list[Path]:
    """All files under ``root`` whose suffix is in the allowlist, excluding .git."""
    allow = {e.lower() for e in extensions}
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts and p.suffix.lower() in allow:
            out.append(p)
    return out


def resolve_doc_file_set(
    sources: list[DocSource],
    worktree_root: Path,
    repo_root: Path | None = None,
) -> tuple[list[tuple[Path, DocSource, LocalProbe]], list[SourceDecision]]:
    """Resolve the documentation file set and per-source decisions.

    A source is read from disk (``disk``) when its probe passes; the returned
    file list contains only its doc-extension-matching files. Otherwise the
    source is marked ``needs_crawl`` with the probe reason (URL-only sources,
    which declare no ``local_path``, are ``needs_crawl / path_absent``).
    """
    files: list[tuple[Path, DocSource, LocalProbe]] = []
    decisions: list[SourceDecision] = []

    for source in sources:
        if source.local_path is None:
            decisions.append(
                SourceDecision(
                    name=source.name,
                    disposition=DISPOSITION_NEEDS_CRAWL,
                    reason=REASON_PATH_ABSENT,
                )
            )
            continue

        probe = probe_local(source, worktree_root, repo_root)
        if probe.usable and probe.resolved_path is not None:
            matched = _collect_doc_files(probe.resolved_path, source.extensions)
            for p in matched:
                files.append((p, source, probe))
            decisions.append(
                SourceDecision(
                    name=source.name,
                    disposition=DISPOSITION_DISK,
                    reason=probe.reason,
                    file_count=len(matched),
                    commit_sha=probe.commit_sha,
                    dirty=probe.dirty,
                    resolved_path=str(probe.resolved_path),
                )
            )
        else:
            decisions.append(
                SourceDecision(
                    name=source.name,
                    disposition=DISPOSITION_NEEDS_CRAWL,
                    reason=probe.reason,
                    commit_sha=probe.commit_sha,
                    dirty=probe.dirty,
                    resolved_path=(
                        str(probe.resolved_path) if probe.resolved_path else None
                    ),
                )
            )

    return files, decisions


__all__ = [
    "DEFAULT_DOC_EXTENSIONS",
    "DocSource",
    "LocalProbe",
    "SourceDecision",
    "DISPOSITION_DISK",
    "DISPOSITION_NEEDS_CRAWL",
    "REASON_OK",
    "REASON_PATH_ABSENT",
    "REASON_MANIFEST_DEFECT",
    "REASON_PATH_EMPTY",
    "REASON_BELOW_MIN_FILES",
    "REASON_SUBMODULE_OFF_PIN",
    "REASON_WORKTREE_DIRTY",
    "load_doc_sources",
    "probe_local",
    "resolve_doc_file_set",
]
