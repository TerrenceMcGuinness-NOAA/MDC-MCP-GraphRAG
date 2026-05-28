"""Property-based tests for omd-tenants-2-v17-pilot.

Feature: omd-tenants-2-v17-pilot
Tests: P4 (Attribution headers — tenant + branch)
"""
from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Hypothesis settings profile
# ---------------------------------------------------------------------------
settings.register_profile(
    "v17",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("v17")

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_LIFECYCLES = ["experimental", "staging", "production", "merged", "stale"]


@st.composite
def tenant_with_branch_strategy(draw):
    """Generate a minimal Tenant-like object with a branch field."""
    tenant_id = draw(st.from_regex(r"[a-z][a-z0-9_]{1,15}", fullmatch=True))
    branch = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P")),
        min_size=1, max_size=40,
    ).filter(lambda s: "\n" not in s and "\r" not in s))
    lifecycle = draw(st.sampled_from(_LIFECYCLES))
    return _FakeTenant(tenant_id=tenant_id, branch=branch, lifecycle=lifecycle)


@st.composite
def tenant_with_empty_branch_strategy(draw):
    """Generate a Tenant-like object with an empty branch field."""
    tenant_id = draw(st.from_regex(r"[a-z][a-z0-9_]{1,15}", fullmatch=True))
    lifecycle = draw(st.sampled_from(_LIFECYCLES))
    return _FakeTenant(tenant_id=tenant_id, branch="", lifecycle=lifecycle)


@dataclass(frozen=True)
class _FakeTenant:
    tenant_id: str
    branch: str
    lifecycle: str


# ---------------------------------------------------------------------------
# Property 4: Attribution headers (tenant + branch)
# Feature: omd-tenants-2-v17-pilot, Property 4: Attribution headers (tenant + branch)
# ---------------------------------------------------------------------------


class TestP4AttributionHeaders:
    """Property 4: Attribution headers (tenant + branch).

    For any tenant T and any non-empty body b:
    - attribute(b, T) first line is *Tenant: <T.tenant_id>* (with [STALE] if stale)
    - When T.branch is non-empty, second line is *Branch: <T.branch>*
    - Then a blank line, then body b unchanged
    - When T.branch is empty, no *Branch:* line is emitted
    """

    @given(
        tenant=tenant_with_branch_strategy(),
        body=st.text(min_size=1, max_size=200),
    )
    def test_branch_line_present_when_branch_nonempty(self, tenant, body):
        """Non-empty branch → *Branch: <branch>* line between tenant and body."""
        from src.tools._attribution import attribute

        result = attribute(body, tenant)
        lines = result.split("\n")

        # First line: *Tenant: <id>* with optional [STALE]
        stale_suffix = " [STALE]" if tenant.lifecycle == "stale" else ""
        expected_tenant_line = f"*Tenant: {tenant.tenant_id}*{stale_suffix}"
        assert lines[0] == expected_tenant_line

        # Second line: *Branch: <branch>*
        expected_branch_line = f"*Branch: {tenant.branch}*"
        assert lines[1] == expected_branch_line

        # Third line: blank separator
        assert lines[2] == ""

        # Remainder: body unchanged
        remainder = "\n".join(lines[3:])
        assert remainder == body

    @given(
        tenant=tenant_with_empty_branch_strategy(),
        body=st.text(min_size=1, max_size=200),
    )
    def test_no_branch_line_when_branch_empty(self, tenant, body):
        """Empty branch → no *Branch:* line; just tenant + blank + body."""
        from src.tools._attribution import attribute

        result = attribute(body, tenant)
        lines = result.split("\n")

        stale_suffix = " [STALE]" if tenant.lifecycle == "stale" else ""
        expected_tenant_line = f"*Tenant: {tenant.tenant_id}*{stale_suffix}"
        assert lines[0] == expected_tenant_line

        # Second line: blank separator (no branch line)
        assert lines[1] == ""

        # Remainder: body unchanged
        remainder = "\n".join(lines[2:])
        assert remainder == body

        # No *Branch:* anywhere
        assert "*Branch:" not in result


# ---------------------------------------------------------------------------
# Property 5: Dedupe correctness and counts
# Feature: omd-tenants-2-v17-pilot, Property 5: Dedupe correctness and counts
# ---------------------------------------------------------------------------

import asyncio
import hashlib
import sys
from pathlib import Path

import pytest


@st.composite
def synthetic_file_tree(draw, min_files=1, max_files=8):
    """Generate a dict of {relative_path: bytes_content} with unique content."""
    n = draw(st.integers(min_value=min_files, max_value=max_files))
    tree = {}
    for i in range(n):
        name = draw(st.from_regex(r"[a-z]{1,8}\.(sh|py|f90)", fullmatch=True))
        # Prefix with index to guarantee unique content across files
        content = draw(st.binary(min_size=1, max_size=200))
        tree[f"src/{name}_{i}"] = bytes([i]) + content
    return tree


class TestP5DedupeCorrectnessAndCounts:
    """Property 5: Dedupe correctness and counts.

    For any file F whose SHA-256 matches a doc already ingested under
    tenant A, ingesting F under tenant B:
    - creates a reference document (is_reference=True, canonical_tenant=A, embedding=None)
    - does NOT create a full-content document or embedding call
    - aggregate dedupe_efficiency_pct == round(deduped/total*100, 1)
    - embedding calls == documents_created_total - documents_deduped
    """

    @given(tree=synthetic_file_tree(min_files=2, max_files=6))
    @pytest.mark.asyncio
    async def test_dedupe_reference_shape_and_counts(self, tree):
        """Ingest under A then B; duplicates become references under B."""
        import tempfile

        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_dedupe import DedupeResult, SHAIndex, make_reference_document

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Setup: write files to tmp_path
            for relpath, content in tree.items():
                p = tmp_path / relpath
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)

            # Stub in-memory registry
            registry: dict[str, dict] = {}

            class StubSHAIndex(SHAIndex):
                def __init__(self):
                    pass  # no real client

                async def lookup(self, sha: str) -> DedupeResult:
                    if sha in registry:
                        r = registry[sha]
                        return DedupeResult(
                            is_duplicate=True,
                            canonical_index=r["index"],
                            canonical_id=r["doc_id"],
                        )
                    return DedupeResult(is_duplicate=False, canonical_index=None, canonical_id=None)

                async def register(self, sha: str, *, tenant, index: str, doc_id: str) -> None:
                    registry[sha] = {"tenant_id": tenant.tenant_id, "index": index, "doc_id": doc_id}

            idx = StubSHAIndex()
            tenant_a = _FakeTenant(tenant_id="gw", branch="develop", lifecycle="production")
            tenant_b = _FakeTenant(tenant_id="gw_v17", branch="dev/gfs.v17", lifecycle="staging")

            # Phase 1: ingest all files under tenant A
            embedding_calls_a = 0
            for relpath in tree:
                p = tmp_path / relpath
                sha = idx.hash_file(p)
                result = await idx.lookup(sha)
                assert not result.is_duplicate
                doc_id = f"a_{sha[:8]}"
                await idx.register(sha, tenant=tenant_a, index="mdc-workflow-docs-titan1024", doc_id=doc_id)
                embedding_calls_a += 1

            # Phase 2: ingest same files under tenant B
            documents_deduped = 0
            embedding_calls_b = 0
            reference_docs = []
            for relpath in tree:
                p = tmp_path / relpath
                sha = idx.hash_file(p)
                result = await idx.lookup(sha)
                if result.is_duplicate:
                    ref = make_reference_document(
                        tenant=tenant_b,
                        source_path=str(p),
                        sha=sha,
                        canonical_index=result.canonical_index,
                        canonical_id=result.canonical_id,
                        canonical_tenant="gw",
                    )
                    reference_docs.append(ref)
                    documents_deduped += 1
                else:
                    embedding_calls_b += 1

            total_files = len(tree)

            # All files were already ingested under A → all are duplicates under B
            assert documents_deduped == total_files
            assert embedding_calls_b == 0

            # Reference document shape assertions
            for ref in reference_docs:
                assert ref["metadata"]["is_reference"] is True
                assert ref["metadata"]["canonical_tenant"] == "gw"
                assert ref["metadata"]["canonical_index"] == "mdc-workflow-docs-titan1024"
                assert ref["metadata"]["canonical_id"] is not None
                assert ref["embedding"] is None
                assert ref["content"] == "<reference: see canonical doc>"
                assert ref["metadata"]["tenant_id"] == "gw_v17"

            # Aggregate invariants
            dedupe_pct = round(documents_deduped / total_files * 100, 1)
            assert dedupe_pct == 100.0
            assert embedding_calls_a == total_files
            assert embedding_calls_b == total_files - documents_deduped


# ---------------------------------------------------------------------------
# Property 3: Worktree containment and populate idempotence
# Feature: omd-tenants-2-v17-pilot, Property 3: Worktree containment and populate idempotence
# ---------------------------------------------------------------------------

import shutil
import subprocess
import tempfile

_GIT_AVAILABLE = shutil.which("git") is not None


def _init_bare_with_branches(bare_path: Path, branches: list[str]):
    """Create a bare repo with an initial commit and named branches.

    Sets origin to point to itself so fetch operations are no-ops
    (the test doesn't need real remote advancement).
    """
    # Use a temporary working clone to create commits
    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir) / "work"
        subprocess.run(["git", "init", str(work)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t.com"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "config", "user.name", "T"],
                       check=True, capture_output=True)
        (work / "README.md").write_text("init")
        subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "commit", "-m", "init"],
                       check=True, capture_output=True)
        # Create each branch
        for br in branches:
            subprocess.run(["git", "-C", str(work), "branch", br],
                           check=True, capture_output=True)
        # Clone as bare
        subprocess.run(["git", "clone", "--bare", str(work), str(bare_path)],
                       check=True, capture_output=True)
    # Point origin to self so fetch is a no-op in tests
    subprocess.run(["git", "-C", str(bare_path), "remote", "set-url", "origin", str(bare_path)],
                   check=True, capture_output=True)


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not on PATH")
class TestP3WorktreeContainmentAndIdempotence:
    """Property 3: Worktree containment and populate idempotence.

    Uses max_examples=20 (not 100) because each iteration creates real
    git repos — keeps CI fast while still exercising varied catalogs.
    """

    @given(
        num_tenants=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=20, deadline=None)
    def test_populate_creates_one_worktree_per_tenant_idempotent(self, num_tenants):
        """Populate creates exactly one worktree per tenant; re-running is idempotent."""
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _populate_worktrees import populate_all

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            bare_path = tmp_path / ".git"
            ap_root = tmp_path / "supported_repos" / "global-workflow"
            ap_root.mkdir(parents=True)

            # Generate tenant configs with distinct subdirs and branches
            tenants = []
            branches = []
            for i in range(num_tenants):
                subdir = f"tenant-{i}"
                branch = f"branch-{i}"
                tenants.append({"tenant_id": f"t{i}", "workflow_subdir": subdir, "branch": branch})
                branches.append(branch)

            _init_bare_with_branches(bare_path, branches)

            # Run populate once
            populate_all(bare_repo=bare_path, ap_root=ap_root, tenants=tenants)

            # Assert: one worktree per tenant at correct path
            for t in tenants:
                wt = ap_root / t["workflow_subdir"]
                assert wt.is_dir(), f"worktree {wt} not created"
                # Check HEAD is on the correct branch
                head_ref = subprocess.check_output(
                    ["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"],
                    text=True,
                ).strip()
                assert head_ref == t["branch"], f"expected {t['branch']}, got {head_ref}"

            # Snapshot directory listing
            snapshot_1 = sorted(p.name for p in ap_root.iterdir() if p.is_dir())

            # Run populate again (idempotence)
            populate_all(bare_repo=bare_path, ap_root=ap_root, tenants=tenants)

            snapshot_2 = sorted(p.name for p in ap_root.iterdir() if p.is_dir())
            assert snapshot_1 == snapshot_2, "idempotence violated"

    @given(num_tenants=st.integers(min_value=2, max_value=3))
    @settings(max_examples=10, deadline=None)
    def test_removing_tenant_from_catalog_does_not_remove_worktree(self, num_tenants):
        """Removing a tenant from the catalog does NOT delete its worktree."""
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _populate_worktrees import populate_all

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            bare_path = tmp_path / ".git"
            ap_root = tmp_path / "supported_repos" / "global-workflow"
            ap_root.mkdir(parents=True)

            tenants = []
            branches = []
            for i in range(num_tenants):
                tenants.append({"tenant_id": f"t{i}", "workflow_subdir": f"t-{i}", "branch": f"b-{i}"})
                branches.append(f"b-{i}")

            _init_bare_with_branches(bare_path, branches)
            populate_all(bare_repo=bare_path, ap_root=ap_root, tenants=tenants)

            # Remove last tenant from catalog and re-run
            removed = tenants[-1]
            populate_all(bare_repo=bare_path, ap_root=ap_root, tenants=tenants[:-1])

            # The removed tenant's worktree still exists
            assert (ap_root / removed["workflow_subdir"]).is_dir()


# ---------------------------------------------------------------------------
# Secondary property: Worktree fetch+merge against bare repo
# Feature: omd-tenants-2-v17-pilot, Property: Worktree fetch+merge against bare repo
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not on PATH")
class TestWorktreeFetchMergeAgainstBareRepo:
    """Bare-repo worktrees lack refs/remotes/origin/*, so git pull fails.
    The correct pattern is fetch origin <branch> + merge --ff-only FETCH_HEAD.
    """

    def test_pull_fails_on_bare_repo_worktree(self):
        """git pull fails on a bare-repo worktree without a remote."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            # Create a bare repo directly (no origin remote)
            bare_path = tmp_path / "bare.git"
            subprocess.run(["git", "init", "--bare", str(bare_path)], check=True, capture_output=True)

            # Create a commit via a temp working tree
            work = tmp_path / "work"
            subprocess.run(["git", "clone", str(bare_path), str(work)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t.com"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(work), "config", "user.name", "T"],
                           check=True, capture_output=True)
            (work / "f.txt").write_text("x")
            subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(work), "commit", "-m", "init"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(work), "push"], check=True, capture_output=True)

            # Remove the origin remote from the bare repo
            subprocess.run(["git", "-C", str(bare_path), "remote", "remove", "origin"],
                           capture_output=True)

            # Add worktree from the bare repo
            wt = tmp_path / "wt"
            subprocess.run(
                ["git", "-C", str(bare_path), "worktree", "add", str(wt), "master"],
                check=True, capture_output=True,
            )

            # git pull should fail — no remote configured
            result = subprocess.run(
                ["git", "-C", str(wt), "pull"],
                capture_output=True, text=True,
            )
            assert result.returncode != 0

    def test_fetch_merge_succeeds_on_bare_repo_worktree(self):
        """fetch origin <branch> + merge --ff-only FETCH_HEAD works."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a non-bare "remote" repo with a commit
            remote = tmp_path / "remote"
            subprocess.run(["git", "init", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(remote), "config", "user.email", "t@t.com"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(remote), "config", "user.name", "T"],
                           check=True, capture_output=True)
            (remote / "f.txt").write_text("v1")
            subprocess.run(["git", "-C", str(remote), "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(remote), "commit", "-m", "v1"],
                           check=True, capture_output=True)

            # Clone as bare
            bare_path = tmp_path / "bare.git"
            subprocess.run(["git", "clone", "--bare", str(remote), str(bare_path)],
                           check=True, capture_output=True)

            # Add worktree
            wt = tmp_path / "wt"
            subprocess.run(
                ["git", "-C", str(bare_path), "worktree", "add", str(wt), "master"],
                check=True, capture_output=True,
            )

            # Advance the remote
            (remote / "f.txt").write_text("v2")
            subprocess.run(["git", "-C", str(remote), "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(remote), "commit", "-m", "v2"],
                           check=True, capture_output=True)

            # Fetch into the worktree (this sets FETCH_HEAD in the worktree)
            subprocess.run(
                ["git", "-C", str(wt), "fetch", "origin", "master"],
                check=True, capture_output=True,
            )

            # merge --ff-only FETCH_HEAD from the worktree
            result = subprocess.run(
                ["git", "-C", str(wt), "merge", "--ff-only", "FETCH_HEAD"],
                capture_output=True, text=True,
            )
            assert result.returncode == 0
            assert (wt / "f.txt").read_text() == "v2"
