"""Unit tests for _ingest_dedupe.py and _ingest_walkers.py.

Feature: omd-tenants-2-v17-pilot, Requirements 3.2, 3.3, 3.4
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# Add scripts/ to path for direct import
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _ingest_dedupe import DedupeResult, SHAIndex, make_reference_document
from _ingest_walkers import files_for_diff, files_for_full_branch


@dataclass(frozen=True)
class _FakeTenant:
    tenant_id: str
    branch: str
    lifecycle: str


# ---------------------------------------------------------------------------
# SHAIndex.hash_file
# ---------------------------------------------------------------------------


class TestHashFile:
    def test_small_text_file(self, tmp_path):
        """hash_file on a small text file matches hashlib directly."""
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        idx = SHAIndex()
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert idx.hash_file(f) == expected

    def test_binary_file(self, tmp_path):
        """hash_file on binary content matches hashlib directly."""
        f = tmp_path / "data.bin"
        content = bytes(range(256)) * 300  # > 64 KiB to test chunking
        f.write_bytes(content)
        idx = SHAIndex()
        expected = hashlib.sha256(content).hexdigest()
        assert idx.hash_file(f) == expected

    def test_empty_file(self, tmp_path):
        """hash_file on empty file returns SHA-256 of empty bytes."""
        f = tmp_path / "empty"
        f.write_bytes(b"")
        idx = SHAIndex()
        expected = hashlib.sha256(b"").hexdigest()
        assert idx.hash_file(f) == expected


# ---------------------------------------------------------------------------
# SHAIndex.lookup / register (async, no client → no-op)
# ---------------------------------------------------------------------------


class TestSHAIndexNoClient:
    @pytest.mark.asyncio
    async def test_lookup_returns_not_duplicate_without_client(self):
        """lookup with no client returns DedupeResult(False, None, None)."""
        idx = SHAIndex(client=None)
        result = await idx.lookup("abc123")
        assert result == DedupeResult(is_duplicate=False, canonical_index=None, canonical_id=None)

    @pytest.mark.asyncio
    async def test_register_is_noop_without_client(self):
        """register with no client does not raise."""
        idx = SHAIndex(client=None)
        t = _FakeTenant(tenant_id="gw", branch="develop", lifecycle="production")
        await idx.register("abc", tenant=t, index="idx", doc_id="d1")
        # No exception = success


# ---------------------------------------------------------------------------
# make_reference_document
# ---------------------------------------------------------------------------


class TestMakeReferenceDocument:
    def test_shape_matches_design(self):
        """Reference document shape matches design §2.4 exactly."""
        t = _FakeTenant(tenant_id="gw_v17", branch="dev/gfs.v17", lifecycle="staging")
        ref = make_reference_document(
            tenant=t,
            source_path="/mnt/workflow/dev-v17/parm/config.yaml",
            sha="9f8eabc123",
            canonical_index="mdc-workflow-docs-titan1024",
            canonical_id="abc123",
            canonical_tenant="gw",
        )
        assert ref["metadata"]["tenant_id"] == "gw_v17"
        assert ref["metadata"]["source"] == "/mnt/workflow/dev-v17/parm/config.yaml"
        assert ref["metadata"]["content_sha256"] == "9f8eabc123"
        assert ref["metadata"]["is_reference"] is True
        assert ref["metadata"]["canonical_tenant"] == "gw"
        assert ref["metadata"]["canonical_index"] == "mdc-workflow-docs-titan1024"
        assert ref["metadata"]["canonical_id"] == "abc123"
        assert ref["content"] == "<reference: see canonical doc>"
        assert ref["embedding"] is None  # null, not empty list


# ---------------------------------------------------------------------------
# files_for_full_branch
# ---------------------------------------------------------------------------


class TestFilesForFullBranch:
    def test_excludes_git_directory(self, tmp_path):
        """files_for_full_branch excludes .git/ contents."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hi')")
        (tmp_path / "README.md").write_text("# hello")

        results = list(files_for_full_branch(tmp_path))
        names = {p.name for p in results}
        assert "main.py" in names
        assert "README.md" in names
        assert "HEAD" not in names

    def test_never_yields_directories(self, tmp_path):
        """files_for_full_branch only yields files, not directories."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file.txt").write_text("x")
        results = list(files_for_full_branch(tmp_path))
        for p in results:
            assert p.is_file()

    def test_empty_directory(self, tmp_path):
        """files_for_full_branch on empty dir yields nothing."""
        assert list(files_for_full_branch(tmp_path)) == []


# ---------------------------------------------------------------------------
# files_for_diff
# ---------------------------------------------------------------------------

_GIT_AVAILABLE = shutil.which("git") is not None


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not on PATH")
class TestFilesForDiff:
    def _make_repo_with_branch(self, tmp_path):
        """Create a git repo with a develop branch and a feature branch."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.com"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"],
                       check=True, capture_output=True)

        # Initial commit on develop
        (repo / "base.txt").write_text("base")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "branch", "-M", "develop"],
                       check=True, capture_output=True)

        # Feature branch with one new file
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feature"],
                       check=True, capture_output=True)
        (repo / "new_file.py").write_text("# new")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add new_file"],
                       check=True, capture_output=True)
        return repo

    def test_returns_changed_files(self, tmp_path):
        """files_for_diff returns files changed vs baseline."""
        repo = self._make_repo_with_branch(tmp_path)
        results = list(files_for_diff(repo, baseline_branch="develop"))
        names = [p.name for p in results]
        assert "new_file.py" in names
        assert "base.txt" not in names

    def test_returns_empty_when_head_equals_baseline(self, tmp_path):
        """files_for_diff returns empty when HEAD == baseline."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.com"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"],
                       check=True, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "branch", "-M", "develop"],
                       check=True, capture_output=True)

        results = list(files_for_diff(repo, baseline_branch="develop"))
        assert results == []
