"""Bug-condition + correctness property tests for ingest-dedupe-and-graph-fix.

Feature: ingest-dedupe-and-graph-fix.

This module groups the three correctness properties from the bugfix
design:

* **Task 1 / Property 1 (Bug Condition)** — collection-blind dedupe
  masks code/jjobs content. ``TestC1BugConditionExploration`` MUST FAIL
  on the unfixed code (sha-only registry key) and PASS on the fixed code
  ((collection, sha) key). It is re-run unchanged in task 11.
* **Task 7 / Property 1 (Fix Checking)** — for buggy inputs the fixed
  pipeline embeds real content and (for code/jjobs) creates a graph node.
* **Task 9 / Property 3 (Unconditional graph write)** — every code/jjobs
  file yields exactly one graph node regardless of the dedupe decision.

Design note — why a fake OpenSearch client + a replica per-file flow:
the tests drive the *real* :class:`SHAIndex` against an in-memory fake
OpenSearch client so the production re-key fix (``_ingest_dedupe.py``)
actually changes the observed behavior. The entry-script per-file flow
(reference-vs-embed + graph MERGE) is not an importable unit, so it is
replicated faithfully in :func:`_run_code_pass_file` exactly as the
v8 entry scripts structure it (graph MERGE in the dedupe ``else``
branch). A signature-tolerant shim (:func:`_lookup` / :func:`_register`)
lets the identical test body run against both the unfixed
(``lookup(sha)``) and fixed (``lookup(sha, collection=...)``) APIs, so
the unfixed failure surfaces behaviorally (``is_reference == True``,
no graph node) rather than as a ``TypeError``.
"""
from __future__ import annotations

import hashlib
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _ingest_dedupe import SHAIndex, make_reference_document  # noqa: E402

COLLECTION_DOCUMENTATION = "documentation"
COLLECTION_CODE = "code"
COLLECTION_JJOBS = "jjobs"


@dataclass(frozen=True)
class _FakeTenant:
    tenant_id: str
    branch: str = "dev/gfs.v17"
    lifecycle: str = "staging"


# ---------------------------------------------------------------------------
# In-memory doubles
# ---------------------------------------------------------------------------


def _term_match(doc: dict, term: dict) -> bool:
    """Evaluate an OpenSearch ``{"term": {field: value}}`` clause."""
    (field, value), = term.items()
    return doc.get(field) == value


def _doc_matches(doc: dict, query: dict) -> bool:
    """Evaluate the two query shapes SHAIndex.lookup builds.

    * unfixed: ``{"term": {"sha": sha}}``
    * fixed:   ``{"bool": {"filter": [{"term": {"collection": c}},
                                       {"term": {"sha": s}}]}}``
    """
    if "term" in query:
        return _term_match(doc, query["term"])
    if "bool" in query:
        return all(_term_match(doc, f["term"]) for f in query["bool"]["filter"])
    raise AssertionError(f"unexpected query shape: {query!r}")


class FakeOSClient:
    """Minimal in-memory stand-in for the opensearch-py client.

    Implements just the synchronous ``index`` / ``search`` surface that
    :class:`SHAIndex` reaches via ``asyncio.to_thread``.
    """

    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def index(self, index: str, id: str, body: dict) -> None:  # noqa: A002
        self.store[id] = dict(body)

    def search(self, index: str, body: dict) -> dict:
        q = body["query"]
        for src in self.store.values():
            if _doc_matches(src, q):
                return {"hits": {"hits": [{"_source": src}]}}
        return {"hits": {"hits": []}}


class StubGraph:
    """Records MERGE calls so tests can assert graph-node creation."""

    def __init__(self) -> None:
        self.nodes: list[tuple[str, dict]] = []

    async def query(self, cypher: str, params: dict | None = None) -> list:
        self.nodes.append((cypher, dict(params or {})))
        return []

    def created_for(self, path: str) -> bool:
        return any(p.get("path") == path for _, p in self.nodes)


# ---------------------------------------------------------------------------
# Signature-tolerant shims — let one test body run on both code versions
# ---------------------------------------------------------------------------


def _supports_collection(func) -> bool:
    return "collection" in inspect.signature(func).parameters


async def _lookup(idx: SHAIndex, sha: str, *, collection: str):
    if _supports_collection(idx.lookup):
        return await idx.lookup(sha, collection=collection)
    return await idx.lookup(sha)


async def _register(idx: SHAIndex, sha: str, *, collection: str, tenant, index: str, doc_id: str) -> None:
    if _supports_collection(idx.register):
        await idx.register(sha, collection=collection, tenant=tenant, index=index, doc_id=doc_id)
    else:
        await idx.register(sha, tenant=tenant, index=index, doc_id=doc_id)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Replica of the v8 code/jjobs per-file flow.
#
# ``graph_in_else=True`` mirrors the CURRENT (unfixed) entry-script
# structure where the graph MERGE lives in the dedupe ``else`` branch.
# ``graph_in_else=False`` mirrors the FIXED structure where the MERGE
# runs unconditionally (used by the Property 3 test, task 9).
# ---------------------------------------------------------------------------


async def _run_code_pass_file(
    *,
    sha_index: SHAIndex,
    graph: StubGraph,
    nodes_by_label: dict[str, int],
    sha: str,
    path: str,
    collection: str,
    label: str,
    index_name: str,
    tenant: _FakeTenant,
    graph_in_else: bool,
) -> tuple[bool, bool]:
    """Process one code/jjobs file; return (is_reference, graph_node_created)."""

    async def _merge() -> None:
        cypher = (
            f"MERGE (n:`{label}` {{name: $name, path: $path}}) "
            f"SET n.tenant_id = $tenant_id, n.sha256 = $sha"
        )
        await graph.query(cypher, params={
            "name": Path(path).stem, "path": path,
            "tenant_id": tenant.tenant_id, "sha": sha,
        })
        nodes_by_label[label] = nodes_by_label.get(label, 0) + 1

    result = await _lookup(sha_index, sha, collection=collection)
    if result.is_duplicate:
        is_reference = True
    else:
        is_reference = False
        if graph_in_else:
            await _merge()
        await _register(
            sha_index, sha, collection=collection, tenant=tenant,
            index=index_name, doc_id=f"{collection}_{sha[:12]}",
        )

    # Fixed structure: graph MERGE runs unconditionally after the if/else.
    if not graph_in_else:
        await _merge()

    return is_reference, graph.created_for(path)


# ===========================================================================
# Task 1 — Bug Condition exploration (MUST FAIL on unfixed code)
# ===========================================================================


class TestC1BugConditionExploration:
    """Property 1 (Bug Condition): a SHA registered only by a *different*
    collection of the *same* tenant is wrongly treated as a duplicate,
    suppressing both real-content embedding and the graph node.

    EXPECTED on UNFIXED code: FAILS (``is_reference`` comes back True, no
    graph node) — this is the success criterion for task 1. The same body
    PASSES on the fixed code (task 11).
    """

    async def _docs_then_x_masking(self, collection: str, label: str, index_name: str):
        client = FakeOSClient()
        idx = SHAIndex(client=client)
        graph = StubGraph()
        nodes: dict[str, int] = {}
        tenant = _FakeTenant(tenant_id="gw_v17")

        sha = _sha("forecast.py contents")
        path = "/mnt/efs-staging/.../forecast.py"

        # Documentation pass registers the SHA first.
        await _register(
            idx, sha, collection=COLLECTION_DOCUMENTATION, tenant=tenant,
            index="gw_v17_mdc-workflow-docs-titan1024", doc_id="doc_x",
        )

        # The code/jjobs pass walks the SAME file.
        is_reference, graph_node_created = await _run_code_pass_file(
            sha_index=idx, graph=graph, nodes_by_label=nodes,
            sha=sha, path=path, collection=collection, label=label,
            index_name=index_name, tenant=tenant, graph_in_else=True,
        )
        return is_reference, graph_node_created

    @pytest.mark.asyncio
    async def test_docs_then_code_masking(self):
        """C(X) #1: docs-registered SHA must NOT mask the code pass."""
        is_reference, graph_node_created = await self._docs_then_x_masking(
            COLLECTION_CODE, "GW_V17_File", "gw_v17_mdc-code-titan1024",
        )
        assert is_reference is False
        assert graph_node_created is True

    @pytest.mark.asyncio
    async def test_docs_then_jjobs_masking(self):
        """C(X) #2: docs-registered SHA must NOT mask the jjobs pass."""
        is_reference, graph_node_created = await self._docs_then_x_masking(
            COLLECTION_JJOBS, "GW_V17_JJob", "gw_v17_mdc-jjobs-titan1024",
        )
        assert is_reference is False
        assert graph_node_created is True

    @pytest.mark.asyncio
    async def test_full_dedupe_collapse_leaves_graph_empty(self):
        """C(X) #3: a small tree registered by docs then re-walked by code
        must still produce graph nodes (unfixed yields ``{}``)."""
        client = FakeOSClient()
        idx = SHAIndex(client=client)
        graph = StubGraph()
        nodes: dict[str, int] = {}
        tenant = _FakeTenant(tenant_id="gw_v17")

        tree = {f"/src/file_{i}.py": _sha(f"unique content {i}") for i in range(4)}

        for path, sha in tree.items():
            await _register(
                idx, sha, collection=COLLECTION_DOCUMENTATION, tenant=tenant,
                index="gw_v17_mdc-workflow-docs-titan1024", doc_id=f"doc_{sha[:8]}",
            )

        for path, sha in tree.items():
            await _run_code_pass_file(
                sha_index=idx, graph=graph, nodes_by_label=nodes,
                sha=sha, path=path, collection=COLLECTION_CODE,
                label="GW_V17_File", index_name="gw_v17_mdc-code-titan1024",
                tenant=tenant, graph_in_else=True,
            )

        assert nodes != {}
        assert nodes.get("GW_V17_File") == len(tree)


# ===========================================================================
# Task 7 — Fix Checking (PASSES on fixed code)
# ===========================================================================


@st.composite
def _bug_condition_input(draw):
    """Generate an X where isBugCondition(X) holds: a code/jjobs pass over
    a SHA registered by a *different* collection of the *same* tenant."""
    tenant_id = draw(st.from_regex(r"[a-z][a-z0-9_]{1,12}", fullmatch=True))
    target = draw(st.sampled_from([COLLECTION_CODE, COLLECTION_JJOBS]))
    prior = draw(st.sampled_from(
        [c for c in (COLLECTION_DOCUMENTATION, COLLECTION_CODE, COLLECTION_JJOBS)
         if c != target]
    ))
    content = draw(st.text(min_size=1, max_size=60))
    return tenant_id, prior, target, content


class TestFixCheckingProperty:
    """Property 1 (Fix Checking): for all X where isBugCondition(X), the
    fixed pipeline embeds real content (is_reference=False) and creates a
    graph node for code/jjobs collections.

    Validates Requirements 2.1, 2.2, 2.3, 2.5, 2.6.
    """

    @given(inp=_bug_condition_input())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_buggy_inputs_embed_and_create_graph_node(self, inp):
        tenant_id, prior, target, content = inp
        idx = SHAIndex(client=FakeOSClient())
        graph = StubGraph()
        nodes: dict[str, int] = {}
        tenant = _FakeTenant(tenant_id=tenant_id)
        sha = _sha(content)
        label = "GW_V17_File" if target == COLLECTION_CODE else "GW_V17_JJob"
        index_name = f"{tenant_id}_mdc-{target}-titan1024"

        # A different collection of the SAME tenant registers the SHA first.
        await _register(
            idx, sha, collection=prior, tenant=tenant,
            index=f"{tenant_id}_mdc-{prior}-titan1024", doc_id="prior",
        )

        is_reference, graph_node_created = await _run_code_pass_file(
            sha_index=idx, graph=graph, nodes_by_label=nodes,
            sha=sha, path=f"/src/{tenant_id}_{target}.f90",
            collection=target, label=label, index_name=index_name,
            tenant=tenant, graph_in_else=False,
        )

        # 1. Not deduped — a SHA seen only in another collection is real content here.
        assert is_reference is False
        # 2. Graph node created regardless of any dedupe decision (code/jjobs).
        assert graph_node_created is True
        assert nodes.get(label) == 1


# ===========================================================================
# Task 9 — Unconditional graph modeling (Property 3, PASSES on fixed code)
# ===========================================================================


@st.composite
def _mixed_dup_tree(draw):
    """Generate a mix of duplicate and non-duplicate code/jjobs files.

    Returns (collection, [(path, content, is_pre_registered)]). Files
    flagged pre-registered are registered under the SAME (collection, sha)
    by a prior tenant first, so they hit the dedupe reference path; the
    rest are never-seen and embed. Either way, each must yield one node.
    """
    collection = draw(st.sampled_from([COLLECTION_CODE, COLLECTION_JJOBS]))
    n = draw(st.integers(min_value=1, max_value=6))
    files = []
    for i in range(n):
        content = f"file-{i}-{draw(st.text(min_size=0, max_size=20))}"
        pre = draw(st.booleans())
        files.append((f"/src/f_{i}.x", content, pre))
    return collection, files


class TestUnconditionalGraphWriteProperty:
    """Property 3: every code/jjobs file yields exactly one graph node,
    whether it was embedded or written as a reference; nodes_created_by_label
    is non-empty whenever >=1 file is processed.

    Validates Requirements 2.3, 2.4, 2.7, 2.8.
    """

    @given(spec=_mixed_dup_tree())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_every_file_yields_one_graph_node(self, spec):
        collection, files = spec
        idx = SHAIndex(client=FakeOSClient())
        graph = StubGraph()
        nodes: dict[str, int] = {}
        label = "GW_V17_File" if collection == COLLECTION_CODE else "GW_V17_JJob"
        index_name = f"gw_v17_mdc-{collection}-titan1024"
        prior_tenant = _FakeTenant(tenant_id="gw")
        tenant = _FakeTenant(tenant_id="gw_v17")

        # Pre-register flagged files under the SAME (collection, sha) by a
        # prior tenant so they become legitimate cross-tenant duplicates.
        for path, content, pre in files:
            if pre:
                await _register(
                    idx, _sha(content), collection=collection, tenant=prior_tenant,
                    index=f"gw_mdc-{collection}-titan1024", doc_id="canon",
                )

        n_dup = 0
        for path, content, pre in files:
            is_reference, graph_node_created = await _run_code_pass_file(
                sha_index=idx, graph=graph, nodes_by_label=nodes,
                sha=_sha(content), path=path, collection=collection,
                label=label, index_name=index_name, tenant=tenant,
                graph_in_else=False,
            )
            n_dup += int(is_reference)
            # Every file — duplicate or not — gets its graph node.
            assert graph_node_created is True

        # One node per distinct path; report non-empty when >=1 file processed.
        distinct_paths = {p for p, _, _ in files}
        assert nodes.get(label) == len(distinct_paths)
        assert nodes != {}
