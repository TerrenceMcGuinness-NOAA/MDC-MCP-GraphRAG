"""Regression guard for the documentation source-set scoping.

disk-priority-ingest, Requirement 1.6 + Task 5.

The bug being guarded: the old ``files_for_full_branch`` walker fed the whole
worktree (~17,000 files, including all of sorc/, every .F90/.yaml/.sh) into the
shared documentation collection. The resolver must instead return a small,
extension-scoped documentation set with NO source-code files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _ingest_sources import (
    DEFAULT_DOC_EXTENSIONS,
    DocSource,
    load_doc_sources,
    resolve_doc_file_set,
)
from _ingest_walkers import files_for_full_branch

# Extensions that must never appear in the resolved documentation set.
_SOURCE_EXTENSIONS = {
    ".f90", ".f", ".f77", ".c", ".h", ".cpp", ".cc", ".hpp",
    ".sh", ".ksh", ".py", ".pl", ".yaml", ".yml", ".json", ".cfg",
    ".cmake", ".mk", ".make", ".xml", ".nml",
}


class TestSyntheticRegressionGuard:
    def _make_mixed_tree(self, tmp_path):
        wt = tmp_path / "wt"
        d = wt / "docs"
        d.mkdir(parents=True)
        # A handful of real doc files.
        for i in range(5):
            (d / f"page{i}.rst").write_text(f"doc {i}")
        (d / "readme.md").write_text("# readme")
        (d / "notes.txt").write_text("notes")
        # A large pile of source files that MUST be excluded.
        src = wt / "docs" / "src"
        src.mkdir()
        for i in range(200):
            (src / f"mod{i}.F90").write_text("program p\nend program\n")
            (src / f"scr{i}.sh").write_text("echo hi\n")
            (src / f"cfg{i}.yaml").write_text("k: v\n")
        return wt

    def test_resolved_set_far_below_whole_tree(self, tmp_path):
        wt = self._make_mixed_tree(tmp_path)
        whole_tree = list(files_for_full_branch(wt))
        sources = [DocSource(name="d", url=None, local_path="docs",
                             min_files=1, extensions=DEFAULT_DOC_EXTENSIONS)]
        files, _ = resolve_doc_file_set(sources, wt)

        # 7 doc files vs 607 total files.
        assert len(files) == 7
        assert len(whole_tree) > 600
        # Resolved set is a tiny fraction of the whole tree.
        assert len(files) < len(whole_tree) / 10

    def test_no_source_extensions_in_resolved_set(self, tmp_path):
        wt = self._make_mixed_tree(tmp_path)
        sources = [DocSource(name="d", url=None, local_path="docs",
                             min_files=1, extensions=DEFAULT_DOC_EXTENSIONS)]
        files, _ = resolve_doc_file_set(sources, wt)
        suffixes = {p.suffix.lower() for p, _, _ in files}
        assert suffixes <= set(DEFAULT_DOC_EXTENSIONS)
        assert suffixes.isdisjoint(_SOURCE_EXTENSIONS)


# ---------------------------------------------------------------------------
# Real-worktree guard (skipped when the develop checkout is not present)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _REPO_ROOT / "mcp_server_python" / "src" / "config" / "unified_manifest.json"
_DEVELOP_WT = _REPO_ROOT / "supported_repos" / "global-workflow_develop"


@pytest.mark.skipif(
    not _DEVELOP_WT.exists() or not _MANIFEST.exists(),
    reason="global-workflow_develop worktree or manifest not present",
)
class TestRealWorktreeGuard:
    def test_develop_doc_set_is_low_thousands_no_code(self):
        sources = load_doc_sources(_MANIFEST)
        files, _ = resolve_doc_file_set(sources, _DEVELOP_WT, repo_root=_REPO_ROOT)

        # Req 1.6: low thousands at most, nowhere near the ~17,000-file walk.
        assert len(files) < 5000, f"resolved {len(files)} docs — scoping regressed"
        assert len(files) > 0

        suffixes = {p.suffix.lower() for p, _, _ in files}
        assert suffixes.isdisjoint(_SOURCE_EXTENSIONS), (
            f"source-code extensions leaked into the doc set: "
            f"{sorted(suffixes & _SOURCE_EXTENSIONS)}"
        )

    def test_develop_whole_tree_is_large(self):
        """Sanity: the whole-tree walk really is huge (the bug's blast radius)."""
        whole = sum(1 for _ in files_for_full_branch(_DEVELOP_WT))
        sources = load_doc_sources(_MANIFEST)
        files, _ = resolve_doc_file_set(sources, _DEVELOP_WT, repo_root=_REPO_ROOT)
        assert len(files) < whole / 5
