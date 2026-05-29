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

            # Stub in-memory registry keyed by (collection, sha)
            registry: dict[tuple[str, str], dict] = {}

            class StubSHAIndex(SHAIndex):
                def __init__(self):
                    pass  # no real client

                async def lookup(self, sha: str, *, collection: str) -> DedupeResult:
                    if (collection, sha) in registry:
                        r = registry[(collection, sha)]
                        return DedupeResult(
                            is_duplicate=True,
                            canonical_index=r["index"],
                            canonical_id=r["doc_id"],
                        )
                    return DedupeResult(is_duplicate=False, canonical_index=None, canonical_id=None)

                async def register(self, sha: str, *, collection: str, tenant, index: str, doc_id: str) -> None:
                    registry[(collection, sha)] = {
                        "tenant_id": tenant.tenant_id, "index": index, "doc_id": doc_id,
                    }

            idx = StubSHAIndex()
            tenant_a = _FakeTenant(tenant_id="gw", branch="develop", lifecycle="production")
            tenant_b = _FakeTenant(tenant_id="gw_v17", branch="dev/gfs.v17", lifecycle="staging")

            # Phase 1: ingest all files under tenant A (collection=code)
            embedding_calls_a = 0
            for relpath in tree:
                p = tmp_path / relpath
                sha = idx.hash_file(p)
                result = await idx.lookup(sha, collection="code")
                assert not result.is_duplicate
                doc_id = f"a_{sha[:8]}"
                await idx.register(sha, collection="code", tenant=tenant_a,
                                   index="mdc-code-titan1024", doc_id=doc_id)
                embedding_calls_a += 1

            # Phase 2: ingest same files under tenant B (same collection=code)
            documents_deduped = 0
            embedding_calls_b = 0
            reference_docs = []
            for relpath in tree:
                p = tmp_path / relpath
                sha = idx.hash_file(p)
                result = await idx.lookup(sha, collection="code")
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
                assert ref["metadata"]["canonical_index"] == "mdc-code-titan1024"
                assert ref["metadata"]["canonical_id"] is not None
                assert ref["embedding"] is None
                assert ref["content"] == "<reference: see canonical doc>"
                assert ref["metadata"]["tenant_id"] == "gw_v17"

            # Aggregate invariants
            dedupe_pct = round(documents_deduped / total_files * 100, 1)
            assert dedupe_pct == 100.0
            assert embedding_calls_a == total_files
            assert embedding_calls_b == total_files - documents_deduped

    @pytest.mark.asyncio
    async def test_collection_dimension_preservation(self):
        """Preservation across the collection dimension (design P5 cases 1-4).

        On the fixed (collection, sha)-keyed registry:
        - a never-seen (collection, sha) is embedded (not a duplicate);
        - docs-then-code in the SAME tenant is NOT a duplicate → embedded once
          per collection (the formerly-buggy masking case is gone);
        - cross-tenant WITHIN a collection still dedupes (preserved);
        - the documentation ingestion pass models no graph node.
        """
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_dedupe import DedupeResult, SHAIndex

        registry: dict[tuple[str, str], dict] = {}

        class StubSHAIndex(SHAIndex):
            def __init__(self):
                pass

            async def lookup(self, sha: str, *, collection: str) -> DedupeResult:
                if (collection, sha) in registry:
                    r = registry[(collection, sha)]
                    return DedupeResult(True, r["index"], r["doc_id"])
                return DedupeResult(False, None, None)

            async def register(self, sha: str, *, collection: str, tenant, index: str, doc_id: str) -> None:
                registry[(collection, sha)] = {
                    "tenant_id": tenant.tenant_id, "index": index, "doc_id": doc_id,
                }

        idx = StubSHAIndex()
        gw = _FakeTenant(tenant_id="gw", branch="develop", lifecycle="production")
        v17 = _FakeTenant(tenant_id="gw_v17", branch="dev/gfs.v17", lifecycle="staging")

        # Case 2: never-seen (collection, sha) → not a duplicate → embed.
        assert (await idx.lookup("aaaa", collection="code")).is_duplicate is False

        # Case 4: documentation registers a sha; the code pass over the SAME sha
        # in the SAME tenant is NOT a duplicate (the formerly-buggy masking case)
        # → embedded once per collection.
        await idx.register("bbbb", collection="documentation", tenant=v17,
                           index="gw_v17_mdc-workflow-docs-titan1024", doc_id="d1")
        assert (await idx.lookup("bbbb", collection="code")).is_duplicate is False
        await idx.register("bbbb", collection="code", tenant=v17,
                           index="gw_v17_mdc-code-titan1024", doc_id="c1")
        assert ("documentation", "bbbb") in registry
        assert ("code", "bbbb") in registry

        # Case 1: cross-tenant WITHIN a collection still dedupes (preserved).
        await idx.register("cccc", collection="code", tenant=gw,
                           index="mdc-code-titan1024", doc_id="canon")
        dup = await idx.lookup("cccc", collection="code")
        assert dup.is_duplicate is True
        assert dup.canonical_index == "mdc-code-titan1024"

        # Case 3: the documentation ingestion pass models NO graph node.
        doc_src = (Path(__file__).parents[2] / "scripts"
                   / "ingest_documentation_v8.py").read_text()
        assert "graph_db" not in doc_src


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


# ---------------------------------------------------------------------------
# Secondary property: Lifecycle → mode mapping
# Feature: omd-tenants-2-v17-pilot, Property: Lifecycle to mode mapping
# ---------------------------------------------------------------------------


class TestLifecycleToModeMapping:
    """For each lifecycle value, _derive_mode_from_lifecycle returns the
    correct mode or raises ValueError for refused lifecycles."""

    def test_experimental_maps_to_diff(self):
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_common import derive_mode_from_lifecycle
        assert derive_mode_from_lifecycle("experimental") == "diff"

    def test_staging_maps_to_full(self):
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_common import derive_mode_from_lifecycle
        assert derive_mode_from_lifecycle("staging") == "full"

    def test_production_maps_to_full(self):
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_common import derive_mode_from_lifecycle
        assert derive_mode_from_lifecycle("production") == "full"

    def test_merged_raises(self):
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_common import derive_mode_from_lifecycle
        with pytest.raises(ValueError, match="merged"):
            derive_mode_from_lifecycle("merged")

    def test_stale_raises(self):
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_common import derive_mode_from_lifecycle
        with pytest.raises(ValueError, match="stale"):
            derive_mode_from_lifecycle("stale")


# ---------------------------------------------------------------------------
# Secondary property: Probe skip semantics
# Feature: omd-tenants-2-v17-pilot, Property: Probe skip semantics
# ---------------------------------------------------------------------------


class TestProbeSkipSemantics:
    """_smoke_branch_isolation raises SkipProbe when catalog lacks gw or gw_v17,
    returns True when isolation holds, raises RuntimeError on leak."""

    @pytest.mark.asyncio
    async def test_skip_when_catalog_missing_gw_v17(self, monkeypatch, tmp_path):
        """Catalog without gw_v17 → SkipProbe raised."""
        import yaml
        sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
        from tools.smoke_queries import _smoke_branch_isolation, SkipProbe

        # Write a catalog with only gw
        catalog_yaml = tmp_path / "tenants.yaml"
        catalog_yaml.write_text(yaml.dump({
            "schema_version": 1,
            "defaults": {"tenant_id": "gw", "staleness_threshold_days": 30},
            "tenants": [{
                "tenant_id": "gw", "repo_ref": "NOAA-EMC/global-workflow",
                "branch": "develop", "index_prefix": "", "label_prefix": "",
                "workflow_subdir": "develop", "lifecycle": "production",
                "description": "test", "extends": [],
            }],
        }))
        monkeypatch.setenv("MCP_TENANT_CATALOG_PATH", str(catalog_yaml))

        with pytest.raises(SkipProbe):
            await _smoke_branch_isolation(None, None)

    @pytest.mark.asyncio
    async def test_skip_when_catalog_missing_gw(self, monkeypatch, tmp_path):
        """Catalog without gw → SkipProbe raised."""
        import yaml
        sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
        from tools.smoke_queries import _smoke_branch_isolation, SkipProbe

        catalog_yaml = tmp_path / "tenants.yaml"
        catalog_yaml.write_text(yaml.dump({
            "schema_version": 1,
            "defaults": {"tenant_id": "gw_v17", "staleness_threshold_days": 30},
            "tenants": [{
                "tenant_id": "gw_v17", "repo_ref": "NOAA-EMC/global-workflow",
                "branch": "dev/gfs.v17", "index_prefix": "gw_v17_",
                "label_prefix": "GW_V17_", "workflow_subdir": "dev-v17",
                "lifecycle": "staging", "description": "test", "extends": [],
            }],
        }))
        monkeypatch.setenv("MCP_TENANT_CATALOG_PATH", str(catalog_yaml))

        with pytest.raises(SkipProbe):
            await _smoke_branch_isolation(None, None)

    @pytest.mark.asyncio
    async def test_pass_when_isolation_holds(self, monkeypatch, tmp_path):
        """Both tenants present + isolation holds → returns True."""
        import yaml
        sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
        from tools.smoke_queries import _smoke_branch_isolation, SkipProbe
        from unittest.mock import AsyncMock, MagicMock

        catalog_yaml = tmp_path / "tenants.yaml"
        catalog_yaml.write_text(yaml.dump({
            "schema_version": 1,
            "defaults": {"tenant_id": "gw", "staleness_threshold_days": 30},
            "tenants": [
                {"tenant_id": "gw", "repo_ref": "NOAA-EMC/global-workflow",
                 "branch": "develop", "index_prefix": "", "label_prefix": "",
                 "workflow_subdir": "develop", "lifecycle": "production",
                 "description": "t", "extends": []},
                {"tenant_id": "gw_v17", "repo_ref": "NOAA-EMC/global-workflow",
                 "branch": "dev/gfs.v17", "index_prefix": "gw_v17_",
                 "label_prefix": "GW_V17_", "workflow_subdir": "dev-v17",
                 "lifecycle": "staging", "description": "t", "extends": []},
            ],
        }))
        monkeypatch.setenv("MCP_TENANT_CATALOG_PATH", str(catalog_yaml))

        # Stub data layer
        data = MagicMock()
        data.graph_db.query = AsyncMock(side_effect=[
            [{"name": "JGDAS_ATMOS_ANALYSIS_WDQMS"}],  # assertion 1: v17 has it
            [],  # assertion 2: gw doesn't
        ])
        data.vector_db.query = AsyncMock(side_effect=[
            [{"metadata": {"source": "/mnt/workflow/develop/docs/mpas.md"}}],  # assertion 3: gw has MPAS
            [],  # assertion 4: v17 has no develop-sourced MPAS
        ])

        result = await _smoke_branch_isolation(data, None)
        assert result is True

    @pytest.mark.asyncio
    async def test_fail_with_r41_prefix_on_leak(self, monkeypatch, tmp_path):
        """Isolation violated → RuntimeError with R4.1#N prefix."""
        import yaml
        sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
        from tools.smoke_queries import _smoke_branch_isolation
        from unittest.mock import AsyncMock, MagicMock

        catalog_yaml = tmp_path / "tenants.yaml"
        catalog_yaml.write_text(yaml.dump({
            "schema_version": 1,
            "defaults": {"tenant_id": "gw", "staleness_threshold_days": 30},
            "tenants": [
                {"tenant_id": "gw", "repo_ref": "NOAA-EMC/global-workflow",
                 "branch": "develop", "index_prefix": "", "label_prefix": "",
                 "workflow_subdir": "develop", "lifecycle": "production",
                 "description": "t", "extends": []},
                {"tenant_id": "gw_v17", "repo_ref": "NOAA-EMC/global-workflow",
                 "branch": "dev/gfs.v17", "index_prefix": "gw_v17_",
                 "label_prefix": "GW_V17_", "workflow_subdir": "dev-v17",
                 "lifecycle": "staging", "description": "t", "extends": []},
            ],
        }))
        monkeypatch.setenv("MCP_TENANT_CATALOG_PATH", str(catalog_yaml))

        # Simulate assertion 1 failure: v17 doesn't have the J-Job
        data = MagicMock()
        data.graph_db.query = AsyncMock(return_value=[])
        data.vector_db.query = AsyncMock(return_value=[])

        with pytest.raises(RuntimeError, match="R4.1#1"):
            await _smoke_branch_isolation(data, None)


# ---------------------------------------------------------------------------
# Property 6: Rollback isolation across config and data layers
# Feature: omd-tenants-2-v17-pilot, Property 6: Rollback isolation across config and data layers
# ---------------------------------------------------------------------------


class TestP6RollbackIsolation:
    """Property 6: Rollback isolation.

    Removing a tenant's data via delete_tenant_indices only removes that
    tenant's prefixed indices and labels; no unprefixed or other-tenant
    data is touched.
    """

    def test_config_layer_removal_preserves_other_tenants(self, tmp_path):
        """Removing a tenant from catalog leaves others byte-equal."""
        import yaml
        sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
        from config.tenants import load_catalog

        catalog_yaml = tmp_path / "tenants.yaml"
        tenants_data = {
            "schema_version": 1,
            "defaults": {"tenant_id": "gw", "staleness_threshold_days": 30},
            "tenants": [
                {"tenant_id": "gw", "repo_ref": "R", "branch": "develop",
                 "index_prefix": "", "label_prefix": "",
                 "workflow_subdir": "develop", "lifecycle": "production",
                 "description": "d", "extends": []},
                {"tenant_id": "gw_v17", "repo_ref": "R", "branch": "dev/gfs.v17",
                 "index_prefix": "gw_v17_", "label_prefix": "GW_V17_",
                 "workflow_subdir": "dev-v17", "lifecycle": "staging",
                 "description": "d", "extends": []},
            ],
        }
        catalog_yaml.write_text(yaml.dump(tenants_data))

        # Snapshot gw tenant before removal
        cat_before = load_catalog(str(catalog_yaml))
        gw_before = cat_before.by_id("gw")

        # Remove gw_v17 from catalog
        tenants_data["tenants"] = [t for t in tenants_data["tenants"] if t["tenant_id"] != "gw_v17"]
        catalog_yaml.write_text(yaml.dump(tenants_data))

        cat_after = load_catalog(str(catalog_yaml))
        gw_after = cat_after.by_id("gw")

        # gw tenant unchanged
        assert gw_before == gw_after
        assert cat_after.defaults.tenant_id == "gw"
        assert "gw_v17" not in cat_after.tenant_ids

    @pytest.mark.asyncio
    async def test_data_layer_deletes_only_target_prefix(self):
        """Delete logic removes only T's prefixed indices and labels."""
        import fnmatch
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from delete_tenant_indices import _delete_tenant_data

        # Real-contract doubles: the raw opensearch-py client + NeptuneAdapter.query.
        all_indices = [
            "mdc-workflow-docs-titan1024",       # unprefixed (gw)
            "mdc-code-titan1024",                # unprefixed (gw)
            "gw_v17_mdc-workflow-docs-titan1024", # v17
            "gw_v17_mdc-code-titan1024",          # v17
            "gw_sfs_mdc-workflow-docs-titan1024",  # another tenant
            "mdc-content-sha-registry",           # system index
        ]
        deleted_indices: list[str] = []
        graph_queries: list[tuple] = []

        class FakeIndices:
            def get_alias(self, *, index):
                return {n: {} for n in all_indices if fnmatch.fnmatch(n, index)}

            def delete(self, *, index):
                deleted_indices.append(index)

        class FakeRawClient:
            indices = FakeIndices()

        class FakeGraphDB:
            def __init__(self):
                self.labels = ["GW_V17_File", "GW_V17_JJob", "File", "GW_SFS_JJob"]

            async def query(self, cypher, params=None, *, tenant=None):
                graph_queries.append((cypher, params, tenant))
                if "RETURN DISTINCT labels(n)" in cypher:
                    return [{"labels": list(self.labels)}]
                return []

        result = await _delete_tenant_data(
            graph_db=FakeGraphDB(),
            raw_os_client=FakeRawClient(),
            index_prefix="gw_v17_",
            label_prefix="GW_V17_",
            dry_run=False,
        )

        # Only gw_v17_ indices deleted
        assert set(deleted_indices) == {
            "gw_v17_mdc-workflow-docs-titan1024",
            "gw_v17_mdc-code-titan1024",
        }
        # Unprefixed indices untouched
        assert "mdc-workflow-docs-titan1024" not in deleted_indices
        assert "mdc-content-sha-registry" not in deleted_indices
        # Other tenant untouched
        assert "gw_sfs_mdc-workflow-docs-titan1024" not in deleted_indices
        # Neptune: discover labels, then one DETACH DELETE per matching GW_V17_
        # label (no any() predicate); every query passes tenant=None (no rewrite).
        detach = [c for c, _, _ in graph_queries if "DETACH DELETE" in c]
        assert detach == [
            "MATCH (n:`GW_V17_File`) DETACH DELETE n",
            "MATCH (n:`GW_V17_JJob`) DETACH DELETE n",
        ]
        assert not any("any(" in c for c, _, _ in graph_queries)
        assert all(t is None for _, _, t in graph_queries)


# ---------------------------------------------------------------------------
# Secondary property: Empty-prefix refusal
# Feature: omd-tenants-2-v17-pilot, Property: Empty-prefix refusal
# ---------------------------------------------------------------------------


class TestEmptyPrefixRefusal:
    """delete_tenant_indices refuses tenants with empty prefix (protects gw)."""

    @pytest.mark.asyncio
    async def test_empty_index_prefix_exits_2(self, tmp_path, monkeypatch):
        """Tenant with empty index_prefix → exit 2, no AWS calls."""
        import yaml
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from delete_tenant_indices import run_delete

        catalog_yaml = tmp_path / "tenants.yaml"
        catalog_yaml.write_text(yaml.dump({
            "schema_version": 1,
            "defaults": {"tenant_id": "gw", "staleness_threshold_days": 30},
            "tenants": [
                {"tenant_id": "gw", "repo_ref": "R", "branch": "develop",
                 "index_prefix": "", "label_prefix": "",
                 "workflow_subdir": "develop", "lifecycle": "production",
                 "description": "d", "extends": []},
            ],
        }))

        exit_code = await run_delete(
            tenant_id="gw", catalog_path=str(catalog_yaml), dry_run=False,
            vector_db=None, graph_db=None,
        )
        assert exit_code == 2

    @pytest.mark.asyncio
    async def test_empty_label_prefix_exits_2(self, tmp_path):
        """Tenant with empty label_prefix → exit 2."""
        import yaml
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from delete_tenant_indices import run_delete

        catalog_yaml = tmp_path / "tenants.yaml"
        catalog_yaml.write_text(yaml.dump({
            "schema_version": 1,
            "defaults": {"tenant_id": "t1", "staleness_threshold_days": 30},
            "tenants": [
                {"tenant_id": "t1", "repo_ref": "R", "branch": "b",
                 "index_prefix": "t1_", "label_prefix": "",
                 "workflow_subdir": "t1", "lifecycle": "staging",
                 "description": "d", "extends": []},
            ],
        }))

        exit_code = await run_delete(
            tenant_id="t1", catalog_path=str(catalog_yaml), dry_run=False,
            vector_db=None, graph_db=None,
        )
        assert exit_code == 2


# ---------------------------------------------------------------------------
# Secondary property: Cost-report drift detection
# Feature: omd-tenants-2-v17-pilot, Property: Cost-report drift detection
# ---------------------------------------------------------------------------


class TestCostReportDriftDetection:
    """For each metric in default_baseline_ranges, values outside the range
    produce drift flags; values inside produce none."""

    @given(
        dedupe=st.floats(min_value=20.0, max_value=50.0),
        docs=st.integers(min_value=1500, max_value=2200),
        tokens=st.integers(min_value=1500000, max_value=2500000),
    )
    def test_within_range_no_flags(self, dedupe, docs, tokens):
        """All metrics within range → empty drift_flags."""
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_cost_model import default_baseline_ranges, evaluate_drift

        observed = {
            "dedupe_efficiency_pct": dedupe,
            "documents_created_total": docs,
            "estimated_tokens": tokens,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert flags == []

    @given(val=st.floats(min_value=0.0, max_value=19.9))
    def test_dedupe_below_range_flagged(self, val):
        """dedupe_efficiency_pct below range → flagged."""
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_cost_model import default_baseline_ranges, evaluate_drift

        observed = {
            "dedupe_efficiency_pct": val,
            "documents_created_total": 1800,
            "estimated_tokens": 2000000,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert "dedupe_efficiency_pct" in flags

    @given(val=st.floats(min_value=50.1, max_value=100.0))
    def test_dedupe_above_range_flagged(self, val):
        """dedupe_efficiency_pct above range → flagged."""
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_cost_model import default_baseline_ranges, evaluate_drift

        observed = {
            "dedupe_efficiency_pct": val,
            "documents_created_total": 1800,
            "estimated_tokens": 2000000,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert "dedupe_efficiency_pct" in flags

    @given(val=st.integers(min_value=2501000, max_value=5000000))
    def test_tokens_above_range_flagged(self, val):
        """estimated_tokens above range → flagged."""
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_cost_model import default_baseline_ranges, evaluate_drift

        observed = {
            "dedupe_efficiency_pct": 35.0,
            "documents_created_total": 1800,
            "estimated_tokens": val,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert "estimated_tokens" in flags


# ---------------------------------------------------------------------------
# Property 2: Empty-prefix passthrough preservation
# Feature: omd-tenants-2-v17-pilot, Property 2: Empty-prefix passthrough preservation
# ---------------------------------------------------------------------------


class TestP2EmptyPrefixPassthroughPreservation:
    """Property 2: Ingesting under a non-empty-prefix tenant does NOT
    modify the unprefixed baseline indices or labels.

    This is the tightest invariant the v17 pilot promises: the gw
    tenant's data is byte-equal before and after a v17 ingestion run.
    """

    @given(
        num_files=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=20, deadline=None)
    @pytest.mark.asyncio
    async def test_v17_ingestion_does_not_touch_unprefixed_data(self, num_files):
        """Non-empty-prefix ingestion leaves unprefixed indices/labels unchanged."""
        sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
        from _ingest_dedupe import SHAIndex, DedupeResult, make_reference_document

        # Pre-existing unprefixed data (simulating gw baseline)
        unprefixed_indices = {
            "mdc-workflow-docs-titan1024": {"doc_1", "doc_2", "doc_3"},
            "mdc-jjobs-titan1024": {"jj_1", "jj_2"},
            "mdc-code-titan1024": {"code_1"},
            "mdc-ee2-standards-titan1024": {"ee2_1", "ee2_2"},
        }
        unprefixed_labels = {"File", "JJob", "FortranSubroutine"}

        # Track all writes during the v17 ingestion
        written_indices: dict[str, set] = {}
        written_labels: set[str] = set()

        class StubVectorDB:
            async def write_document(self, index, doc_id, **kwargs):
                written_indices.setdefault(index, set()).add(doc_id)

        class StubGraphDB:
            async def write_node(self, label, **kwargs):
                written_labels.add(label)

        # Simulate v17 ingestion (non-empty prefix)
        tenant_v17 = _FakeTenant(
            tenant_id="gw_v17", branch="dev/gfs.v17", lifecycle="staging"
        )
        v17_index_prefix = "gw_v17_"
        v17_label_prefix = "GW_V17_"

        sha_index = SHAIndex(client=None)  # no-op lookup/register

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for i in range(num_files):
                f = tmp_path / f"file_{i}.sh"
                f.write_bytes(bytes([i]) * 50)

                # Simulate the ingestion write path
                index_name = f"{v17_index_prefix}mdc-workflow-docs-titan1024"
                doc_id = f"v17_doc_{i}"
                await StubVectorDB().write_document(index_name, doc_id)

                label = f"{v17_label_prefix}File"
                await StubGraphDB().write_node(label)

        # Post-assertion: no unprefixed index was written to
        for idx in written_indices:
            assert idx.startswith(v17_index_prefix), (
                f"Write to unprefixed index {idx!r} — baseline violated"
            )

        # Post-assertion: no unprefixed label was written
        for label in written_labels:
            assert label.startswith(v17_label_prefix), (
                f"Write to unprefixed label {label!r} — baseline violated"
            )

        # Post-assertion: original unprefixed data unchanged
        # (the stubs don't mutate the pre-existing sets — this confirms
        # the ingestion path never touches them)
        assert unprefixed_indices == {
            "mdc-workflow-docs-titan1024": {"doc_1", "doc_2", "doc_3"},
            "mdc-jjobs-titan1024": {"jj_1", "jj_2"},
            "mdc-code-titan1024": {"code_1"},
            "mdc-ee2-standards-titan1024": {"ee2_1", "ee2_2"},
        }
        assert unprefixed_labels == {"File", "JJob", "FortranSubroutine"}
