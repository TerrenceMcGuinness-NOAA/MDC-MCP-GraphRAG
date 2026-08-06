"""Unit tests for _ingest_sources.py.

Feature: disk-priority-ingest, Requirements 1 and 2.

Covers every probe reason (path_absent, manifest_defect, path_empty,
below_min_files, submodule_off_pin, worktree_dirty, ok), the manifest loader,
and the source-set resolver's disk / needs_crawl dispositions.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _ingest_sources import (
    DEFAULT_DOC_EXTENSIONS,
    DISPOSITION_DISK,
    DISPOSITION_NEEDS_CRAWL,
    REASON_BELOW_MIN_FILES,
    REASON_MANIFEST_DEFECT,
    REASON_OK,
    REASON_PATH_ABSENT,
    REASON_PATH_EMPTY,
    REASON_SUBMODULE_OFF_PIN,
    REASON_WORKTREE_DIRTY,
    DocSource,
    load_doc_sources,
    probe_local,
    resolve_doc_file_set,
)

_GIT_AVAILABLE = shutil.which("git") is not None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")


def _commit_all(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _src(name="s", local_path="sub", min_files=0, extensions=DEFAULT_DOC_EXTENSIONS, url=None):
    return DocSource(name=name, url=url, local_path=local_path,
                     min_files=min_files, extensions=extensions)


# ---------------------------------------------------------------------------
# Non-git reasons (no submodule setup needed)
# ---------------------------------------------------------------------------


class TestSimpleReasons:
    def test_absent_path_is_manifest_defect(self, tmp_path):
        """Any declared local_path that does not resolve is a manifest_defect (5e.c)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        probe = probe_local(_src(local_path="nested/does_not_exist"), wt)
        assert probe.usable is False
        assert probe.reason == REASON_MANIFEST_DEFECT
        assert probe.resolved_path is None

    def test_manifest_defect_direct_sorc_child(self, tmp_path):
        """A direct sorc/ child that is absent is a manifest defect."""
        wt = tmp_path / "wt"
        (wt / "sorc").mkdir(parents=True)
        (wt / ".gitmodules").write_text(
            '[submodule "sorc/gsi_enkf.fd"]\n\tpath = sorc/gsi_enkf.fd\n'
            "\turl = https://example/GSI.git\n"
        )
        probe = probe_local(_src(local_path="sorc/gsi.fd"), wt)
        assert probe.usable is False
        assert probe.reason == REASON_MANIFEST_DEFECT

    def test_registered_but_absent_submodule_is_manifest_defect(self, tmp_path):
        """Even a .gitmodules-registered path is a defect when absent (5e.c)."""
        wt = tmp_path / "wt"
        (wt / "sorc").mkdir(parents=True)
        (wt / ".gitmodules").write_text(
            '[submodule "sorc/gsi_enkf.fd"]\n\tpath = sorc/gsi_enkf.fd\n'
        )
        probe = probe_local(_src(local_path="sorc/gsi_enkf.fd"), wt)
        assert probe.reason == REASON_MANIFEST_DEFECT

    def test_path_empty(self, tmp_path):
        wt = tmp_path / "wt"
        (wt / "empty").mkdir(parents=True)
        probe = probe_local(_src(local_path="empty"), wt)
        assert probe.usable is False
        assert probe.reason == REASON_PATH_EMPTY
        assert probe.resolved_path == wt / "empty"

    def test_below_min_files(self, tmp_path):
        wt = tmp_path / "wt"
        d = wt / "docs"
        d.mkdir(parents=True)
        (d / "a.rst").write_text("x")
        (d / "b.rst").write_text("y")
        probe = probe_local(_src(local_path="docs", min_files=5), wt)
        assert probe.usable is False
        assert probe.reason == REASON_BELOW_MIN_FILES

    def test_repo_root_fallback(self, tmp_path):
        """A supported_repos/... style path resolves under repo_root."""
        repo_root = tmp_path / "repo"
        d = repo_root / "supported_repos" / "x" / "docs"
        d.mkdir(parents=True)
        (d / "a.rst").write_text("hi")
        wt = tmp_path / "wt"
        wt.mkdir()
        probe = probe_local(
            _src(local_path="supported_repos/x/docs"), wt, repo_root=repo_root
        )
        # Not a git repo, plain dir -> ok (commit_sha None is fine)
        assert probe.reason == REASON_OK
        assert probe.resolved_path == d


# ---------------------------------------------------------------------------
# git / submodule reasons
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not on PATH")
class TestSubmoduleReasons:
    def _make_super_with_submodule(self, tmp_path):
        # upstream submodule repo
        up = tmp_path / "upstream"
        _init_repo(up)
        (up / "readme.rst").write_text("doc one")
        (up / "guide.rst").write_text("doc two")
        (up / "code.F90").write_text("program p\nend program\n")
        _commit_all(up, "init upstream")

        # superproject
        sup = tmp_path / "super"
        _init_repo(sup)
        (sup / "base.txt").write_text("base")
        _commit_all(sup, "init super")
        _git(sup, "submodule", "add", str(up), "sub")
        _commit_all(sup, "add submodule")
        return sup, up

    def test_ok_submodule_at_pin_clean(self, tmp_path):
        sup, _ = self._make_super_with_submodule(tmp_path)
        probe = probe_local(_src(local_path="sub", min_files=1), sup)
        assert probe.usable is True
        assert probe.reason == REASON_OK
        assert probe.resolved_path == sup / "sub"
        assert probe.commit_sha is not None
        assert probe.dirty is False

    def test_submodule_off_pin(self, tmp_path):
        sup, up = self._make_super_with_submodule(tmp_path)
        sub = sup / "sub"
        # advance the submodule's own HEAD without updating the superproject link
        (sub / "extra.rst").write_text("more")
        _commit_all(sub, "advance submodule")
        probe = probe_local(_src(local_path="sub", min_files=1), sup)
        assert probe.usable is False
        assert probe.reason == REASON_SUBMODULE_OFF_PIN

    def test_worktree_dirty_submodule(self, tmp_path):
        sup, _ = self._make_super_with_submodule(tmp_path)
        sub = sup / "sub"
        # modify a tracked file (uncommitted) -> dirty, still at pin
        (sub / "readme.rst").write_text("doc one modified")
        probe = probe_local(_src(local_path="sub", min_files=1), sup)
        assert probe.usable is False
        assert probe.reason == REASON_WORKTREE_DIRTY
        assert probe.dirty is True

    def test_ok_plain_directory_in_superproject(self, tmp_path):
        """A committed plain dir (tree, not gitlink) is not off-pin -> ok."""
        sup = tmp_path / "super"
        _init_repo(sup)
        d = sup / "docs"
        d.mkdir()
        (d / "index.rst").write_text("welcome")
        head = _commit_all(sup, "add docs")
        probe = probe_local(_src(local_path="docs", min_files=1), sup)
        assert probe.usable is True
        assert probe.reason == REASON_OK
        assert probe.commit_sha == head

    def test_resolve_doc_file_set_disk_and_extension_scope(self, tmp_path):
        """Disk source returns only doc-extension files, not code."""
        sup, _ = self._make_super_with_submodule(tmp_path)
        sources = [_src(name="sub", local_path="sub", min_files=1)]
        files, decisions = resolve_doc_file_set(sources, sup)
        names = sorted(p.name for p, _, _ in files)
        assert names == ["guide.rst", "readme.rst"]  # code.F90 excluded
        assert len(decisions) == 1
        assert decisions[0].disposition == DISPOSITION_DISK
        assert decisions[0].file_count == 2


# ---------------------------------------------------------------------------
# resolve_doc_file_set dispositions
# ---------------------------------------------------------------------------


class TestResolveDispositions:
    def test_url_only_source_needs_crawl(self, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        sources = [_src(name="rtd", local_path=None, url="https://x/docs")]
        files, decisions = resolve_doc_file_set(sources, wt)
        assert files == []
        assert decisions[0].disposition == DISPOSITION_NEEDS_CRAWL

    def test_empty_source_needs_crawl_with_reason(self, tmp_path):
        wt = tmp_path / "wt"
        (wt / "empty").mkdir(parents=True)
        sources = [_src(name="e", local_path="empty")]
        _, decisions = resolve_doc_file_set(sources, wt)
        assert decisions[0].disposition == DISPOSITION_NEEDS_CRAWL
        assert decisions[0].reason == REASON_PATH_EMPTY


# ---------------------------------------------------------------------------
# load_doc_sources
# ---------------------------------------------------------------------------


class TestLoadDocSources:
    def _manifest(self, tmp_path, sources):
        p = tmp_path / "m.json"
        p.write_text(json.dumps({"sources": sources}))
        return p

    def test_selects_doc_types_and_skips_disabled(self, tmp_path):
        m = self._manifest(tmp_path, [
            {"name": "a", "source_type": "url_crawl", "enabled": True,
             "url": "https://a", "local_path": "sorc/a.fd"},
            {"name": "b", "source_type": "url_crawl", "enabled": False,
             "url": "https://b"},
            {"name": "c", "source_type": "code_parse", "enabled": True},
            {"name": "d", "source_type": "on_disk_submodule", "enabled": True,
             "local_path": "docs", "file_patterns": ["**/*.rst"]},
        ])
        srcs = load_doc_sources(m)
        names = sorted(s.name for s in srcs)
        assert names == ["a", "d"]  # b disabled, c not a doc type

    def test_extensions_from_file_patterns(self, tmp_path):
        m = self._manifest(tmp_path, [
            {"name": "d", "source_type": "on_disk_submodule", "enabled": True,
             "local_path": "docs", "file_patterns": ["**/*.rst"]},
        ])
        srcs = load_doc_sources(m)
        assert srcs[0].extensions == (".rst",)

    def test_default_extensions_and_min_files(self, tmp_path):
        m = self._manifest(tmp_path, [
            {"name": "a", "source_type": "url_crawl", "enabled": True,
             "url": "https://a", "local_path": "sorc/a.fd", "min_files": 200},
        ])
        srcs = load_doc_sources(m)
        assert srcs[0].extensions == DEFAULT_DOC_EXTENSIONS
        assert srcs[0].min_files == 200

    def test_min_files_defaults_zero_when_absent(self, tmp_path):
        m = self._manifest(tmp_path, [
            {"name": "a", "source_type": "url_crawl", "enabled": True,
             "url": "https://a", "local_path": "sorc/a.fd"},
        ])
        srcs = load_doc_sources(m)
        assert srcs[0].min_files == 0
