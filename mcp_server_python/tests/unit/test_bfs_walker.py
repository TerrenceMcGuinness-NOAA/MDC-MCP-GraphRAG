"""Unit tests for :mod:`src.tools._bfs_walker`.

The module hosts the two query-shape optimizations of the
``neptune-traversal-query-optimization`` spec:

* ``resolve_anchor_ids`` -- UNION_ALL_Decomposition of the Anchor_Predicate
  (R1.1, R1.3, R1.4), covered by the *Task 2.5* section below.
* ``bfs_walk`` / ``_expand_one_hop`` -- the BFS_Walker itself (R2.1-R2.7),
  covered by the *Task 4.4* section below.
* ``bfs_walk``'s activation / completion log lines and the
  ``bfs_optimized_header`` / ``insert_bfs_header`` response indicator
  (R8.1-R8.4), covered by the *Task 8.3* section below. The indicator's
  tool-level half -- that it reaches a rendered response -- lives with
  each tool's own suite, where the server fixtures are.
* Label_Scope_Predicate on expanded nodes (R4.1, R4.3, R4.4), covered by
  the *Task 7.3* section below.

The graph fixture is :class:`MockGraphDB` from ``tests/conftest.py``; see
its ``add_response`` fragment-matching docstring for how cypher queries
are routed to canned row lists. No live AWS calls.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import pytest

from src.config.tenants import CatalogDefaults, Tenant, TenantCatalog
from src.tenancy.resolver import tenant_scope
from src.tools._bfs_walker import (
    _EDGE_TYPE_RE,
    BFSResult,
    _expand_one_hop,
    _is_timeout_error,
    _positive_int,
    _retarget_scope_pred,
    _valid_edge_types,
    bfs_optimized_header,
    bfs_walk,
    insert_bfs_header,
    resolve_anchor_ids,
)
from src.tools._traversal_bounds import (
    BFS_ACTIVATION_THRESHOLD,
    BFS_FAN_OUT_LIMIT,
    RESULT_LIMIT,
)
from tests.conftest import MockGraphDB

pytestmark = pytest.mark.unit


# ── helpers ────────────────────────────────────────────────────────────


#: Fragment unique to the ``resolve_anchor_ids`` cypher, used to route
#: canned rows through the mock's longest-substring matcher.
_ANCHOR_FRAGMENT = "RETURN id(n) AS nid"


def _make_graph(rows: list[dict[str, Any]] | None = None) -> MockGraphDB:
    """Fresh mock with the default canned rows wiped and the anchor
    resolution query seeded with ``rows``."""
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response(_ANCHOR_FRAGMENT, list(rows or []))
    return graph


def _cyphers(graph: MockGraphDB) -> list[str]:
    return [c[1][0] for c in graph.call_log if c[0] == "query"]


def _query_calls(graph: MockGraphDB) -> list[Any]:
    return [c for c in graph.call_log if c[0] == "query"]


def _make_catalog() -> TenantCatalog:
    """Two-tenant catalog: default ``gw`` (no prefix) + ``gw_v17``."""
    gw = Tenant(
        tenant_id="gw",
        repo_ref="NOAA-EMC/global-workflow",
        branch="develop",
        index_prefix="",
        label_prefix="",
        workflow_subdir="global-workflow",
        lifecycle="production",
    )
    gw_v17 = Tenant(
        tenant_id="gw_v17",
        repo_ref="NOAA-EMC/global-workflow",
        branch="dev/gfs.v17",
        index_prefix="gw_v17_",
        label_prefix="GW_V17_",
        workflow_subdir="global-workflow-v17",
        lifecycle="staging",
    )
    return TenantCatalog(
        schema_version=1,
        defaults=CatalogDefaults(tenant_id="gw"),
        tenants=(gw, gw_v17),
    )


# ══ Task 2.5 — resolve_anchor_ids / UNION_ALL_Decomposition ════════════
# Validates R1.1 (UNION ALL replaces the OR anchor predicate), R1.3
# (set-equivalent, deduplicated result), R1.4 (scope predicate and
# statement-timeout carried on both branches).


async def test_resolve_anchor_ids_emits_union_all_not_or() -> None:
    """The anchor predicate is two ``UNION ALL`` branches, never an ``OR``
    disjunction over ``name``/``path`` (R1.1)."""
    graph = _make_graph([{"nid": "1"}])
    await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0
    )
    cypher = _cyphers(graph)[0]
    assert "UNION ALL" in cypher
    assert cypher.count("UNION ALL") == 1
    # Each branch is a single-property equality -> index-seekable.
    assert "n.name = $name" in cypher
    assert "n.path = $name" in cypher
    # The index-defeating disjunction is gone.
    assert " OR " not in cypher
    assert "n.name = $name OR" not in cypher


async def test_resolve_anchor_ids_dedupes_overlapping_branch_rows() -> None:
    """``UNION ALL`` does not dedupe, so a node matched on both ``name``
    and ``path`` arrives twice; the returned ids are folded to a set so
    the result stays set-equivalent to the ``OR`` form (R1.3)."""
    graph = _make_graph(
        [
            # name branch
            {"nid": "n-1"},
            {"nid": "n-2"},
            # path branch — n-1 matched on both properties
            {"nid": "n-1"},
            {"nid": "n-3"},
        ]
    )
    ids = await resolve_anchor_ids(
        graph, "exglobal_forecast.sh", scope_pred="", tenant=None,
        timeout_s=30.0,
    )
    assert sorted(ids) == ["n-1", "n-2", "n-3"]
    assert len(ids) == len(set(ids)), "duplicate anchor ids leaked"


async def test_resolve_anchor_ids_scope_pred_on_both_branches() -> None:
    """The Label_Scope_Predicate is carried on *both* branches, so tenant
    isolation is identical to the pre-decomposition query (R1.4)."""
    scope = (
        " AND size([__lbl IN labels(n) "
        "WHERE __lbl STARTS WITH 'GW_V17_']) > 0"
    )
    graph = _make_graph([{"nid": "1"}])
    await resolve_anchor_ids(
        graph, "setuprad", scope_pred=scope, tenant=None, timeout_s=30.0
    )
    cypher = _cyphers(graph)[0]
    assert cypher.count(scope) == 2
    head, _, tail = cypher.partition("UNION ALL")
    assert scope in head
    assert scope in tail


async def test_resolve_anchor_ids_omits_scope_pred_when_empty() -> None:
    """A default-tenant caller passes an empty fragment; nothing extra is
    appended to either branch."""
    graph = _make_graph([{"nid": "1"}])
    await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0
    )
    cypher = _cyphers(graph)[0]
    assert "labels(n)" not in cypher
    assert cypher.count("WHERE") == 2  # one per branch, nothing more


async def test_resolve_anchor_ids_passes_tenant_and_timeout_through() -> None:
    """The tenant object and Statement_Timeout reach the adapter
    unchanged, and ``$name`` is bound as a parameter (R1.4)."""
    graph = _make_graph([{"nid": "1"}])
    sentinel = object()
    await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=sentinel, timeout_s=12.5
    )
    calls = _query_calls(graph)
    assert len(calls) == 1
    assert calls[0][2] == {"name": "setuprad"}
    assert calls[0][3]["tenant"] is sentinel
    assert calls[0][3]["timeout"] == 12.5


async def test_resolve_anchor_ids_scopes_both_branches_for_non_default_tenant(
) -> None:
    """End-to-end with the real ``tenant_label_predicate``: a non-default
    tenant's label prefix appears on both branches (R1.4, R4.4)."""
    from src.tools.code_analysis import _scope_and

    catalog = _make_catalog()
    graph = _make_graph([{"nid": "1"}])
    async with tenant_scope("gw_v17", catalog) as ctx:
        await resolve_anchor_ids(
            graph,
            "setuprad",
            scope_pred=_scope_and("n"),
            tenant=ctx.tenant,
            timeout_s=30.0,
        )
    cypher = _cyphers(graph)[0]
    assert cypher.count("GW_V17_") == 2
    head, _, tail = cypher.partition("UNION ALL")
    assert "GW_V17_" in head
    assert "GW_V17_" in tail


async def test_resolve_anchor_ids_blank_name_issues_no_query() -> None:
    """Without an anchor name there is nothing to seek; short-circuit."""
    graph = _make_graph([{"nid": "1"}])
    assert await resolve_anchor_ids(
        graph, "", scope_pred="", tenant=None, timeout_s=30.0
    ) == []
    assert _query_calls(graph) == []


async def test_resolve_anchor_ids_timeout_returns_empty_not_raise() -> None:
    """A statement-timeout on anchor resolution degrades to 'no anchor',
    never an unhandled exception (R1.4, Property 7)."""
    from src.data.neptune_adapter import NeptuneAdapterError

    graph = _make_graph([{"nid": "1"}])
    graph.add_raise(
        _ANCHOR_FRAGMENT,
        NeptuneAdapterError("query exceeded 30.0s statement timeout"),
    )
    assert await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0
    ) == []


async def test_resolve_anchor_ids_non_timeout_error_returns_empty() -> None:
    """Any other query failure is equally graceful."""
    graph = _make_graph([{"nid": "1"}])
    graph.add_raise(_ANCHOR_FRAGMENT, RuntimeError("boom"))
    assert await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0
    ) == []


async def test_resolve_anchor_ids_skips_malformed_rows() -> None:
    """Non-dict rows and blank/absent ids are dropped rather than
    producing bogus anchors."""
    graph = _make_graph(
        [
            {"nid": "good-1"},
            {"nid": None},
            {"nid": ""},
            {"other": "x"},
            {"nid": 42},  # non-str ids are normalised
        ]
    )
    ids = await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0
    )
    assert sorted(ids) == ["42", "good-1"]


async def test_resolve_anchor_ids_empty_result_set_returns_empty() -> None:
    graph = _make_graph([])
    assert await resolve_anchor_ids(
        graph, "nosuchsymbol", scope_pred="", tenant=None, timeout_s=30.0
    ) == []


# ══ Task 2.6 — node variable + failure sink ═════════════════════════════
# The two parameters ``anchor_degree`` needs to reuse this resolution:
# ``var`` so its ``_scope_and("a")`` fragment drops in without
# retargeting, ``error_sink`` so a lost query stays distinguishable from
# a resolution that matched nothing (R1.5 fail-safe).


async def test_resolve_anchor_ids_honours_node_variable() -> None:
    """``var`` renames the bound node in both branches and in the
    projection, so a caller anchored on ``a`` needs no rewrite."""
    graph = _make_graph([{"nid": "1"}])
    await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0,
        var="a",
    )
    cypher = _cyphers(graph)[0]
    assert "MATCH (a) WHERE a.name = $name" in cypher
    assert "MATCH (a) WHERE a.path = $name" in cypher
    assert cypher.count("RETURN id(a) AS nid") == 2
    # No leftover ``n`` binding -- the whole query moved to ``a``.
    assert "(n)" not in cypher
    assert "id(n)" not in cypher
    # Still the decomposed shape, not an OR.
    assert cypher.count("UNION ALL") == 1
    assert " OR " not in cypher


async def test_resolve_anchor_ids_rejects_non_identifier_node_variable(
) -> None:
    """``var`` is interpolated into the pattern, so anything that is not a
    bare identifier falls back to ``n`` rather than being emitted."""
    graph = _make_graph([{"nid": "1"}])
    ids = await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0,
        var="a) RETURN 1 AS nid //",
    )
    cypher = _cyphers(graph)[0]
    assert "RETURN 1 AS nid" not in cypher
    assert "MATCH (n) WHERE n.name = $name" in cypher
    assert ids == ["1"]


@pytest.mark.parametrize(
    "exc, expected",
    [
        (RuntimeError("boom"), "error"),
        (asyncio.TimeoutError(), "timeout"),
    ],
)
async def test_resolve_anchor_ids_error_sink_records_failure(
    exc: BaseException, expected: str
) -> None:
    """A lost resolution deposits its reason in ``error_sink`` while still
    returning ``[]``, so a caller that must not read the empty list as
    'no match' can tell the two apart."""
    graph = _make_graph([{"nid": "1"}])
    graph.add_raise(_ANCHOR_FRAGMENT, exc)
    sink: list[str] = []
    ids = await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0,
        error_sink=sink,
    )
    assert ids == []
    assert sink == [expected]


@pytest.mark.parametrize("rows", [[], [{"nid": "1"}]])
async def test_resolve_anchor_ids_error_sink_untouched_without_failure(
    rows: list[dict[str, object]]
) -> None:
    """A successful resolution leaves the sink empty, whether or not it
    matched anything -- only a lost query is a failure."""
    graph = _make_graph(rows)
    sink: list[str] = []
    await resolve_anchor_ids(
        graph, "setuprad", scope_pred="", tenant=None, timeout_s=30.0,
        error_sink=sink,
    )
    assert sink == []


def test_bfs_result_is_frozen_with_expected_fields() -> None:
    """``BFSResult`` carries the observability fields R8.2 renders and is
    immutable so a caller cannot mutate a walk's outcome (Task 4.1)."""
    result = BFSResult(
        nodes=[{"name": "a", "hop": 1, "relType": "CALLS",
                "direction": "forward"}],
        hops_expanded=1,
        queries_issued=2,
        wall_clock_ms=7,
        truncated=False,
    )
    assert result.nodes[0]["name"] == "a"
    assert result.hops_expanded == 1
    assert result.queries_issued == 2
    assert result.wall_clock_ms == 7
    assert result.truncated is False
    with pytest.raises(AttributeError):
        result.truncated = True  # type: ignore[misc]


# ══ Task 4.4 — bfs_walk / _expand_one_hop (BFS_Walker) ═════════════════
# Validates R2.1 (per-type single-hop decomposition + application-side
# merge), R2.3 (Fan_Out_Limit bounds each expansion), R2.4 (visited-set
# prevents cycles and re-expansion), R2.5 (early termination on a hop
# that yields nothing new), R2.7 (result is a bounded subset; a walk
# degrades to partial results rather than raising).


# ── BFS graph double ───────────────────────────────────────────────────


#: Matches the expansion pattern ``_expand_one_hop`` emits. Group 1 is
#: the pattern head (``a`` for forward, ``b`` for reverse) and group 2 the
#: interpolated relationship type.
_EXPAND_RE = re.compile(
    r"MATCH \((a|b)\)-\[:([A-Za-z_][A-Za-z0-9_]*)\]->\((?:a|b)\)"
)
_LIMIT_RE = re.compile(r"LIMIT (\d+)")

#: Fragment unique to an expansion query, for ``add_raise`` routing.
_EXPAND_FRAGMENT = "RETURN DISTINCT id(b) AS nid"


class _WalkGraph(MockGraphDB):
    """:class:`MockGraphDB` that answers expansions from an adjacency list.

    A hop's cypher is identical at every depth (only ``$ids`` changes), so
    fragment matching alone cannot express a multi-hop graph. This double
    keeps the parent's ``call_log`` / ``add_raise`` behaviour (both flow
    through ``super().query``) and, for an expansion query, resolves the
    rows from ``edges`` instead of the canned list -- honouring the
    direction encoded in the pattern, the ``DISTINCT`` on the target, and
    the ``LIMIT`` the walker carried.
    """

    def __init__(
        self,
        edges: list[tuple[str, str, str]] | None = None,
        *,
        anchor_ids: tuple[str, ...] = ("A",),
        node_meta: dict[str, dict[str, Any]] | None = None,
        slow_after: int | None = None,
        slow_seconds: float = 5.0,
    ) -> None:
        super().__init__()
        self.canned_rows = []
        #: Directed edges as ``(source_id, rel_type, target_id)``.
        self.edges = list(edges or [])
        self.node_meta = dict(node_meta or {})
        #: Once more than this many queries have been issued, every
        #: query sleeps ``slow_seconds`` -- trips the wall-clock bound.
        self.slow_after = slow_after
        self.slow_seconds = slow_seconds
        self.add_response(
            _ANCHOR_FRAGMENT, [{"nid": nid} for nid in anchor_ids]
        )

    def _row(self, nid: str) -> dict[str, Any]:
        meta = self.node_meta.get(nid, {})
        return {
            "nid": nid,
            "name": meta.get("name", nid),
            "path": meta.get("path"),
            "labels": meta.get("labels", ["File"]),
        }

    async def query(  # type: ignore[override]
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        tenant: Any = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        rows = await super().query(cypher, params, tenant, timeout=timeout)
        if self.slow_after is not None:
            issued = sum(1 for c in self.call_log if c[0] == "query")
            if issued > self.slow_after:
                await asyncio.sleep(self.slow_seconds)
        match = _EXPAND_RE.search(cypher)
        if match is None:
            return rows
        head, edge_type = match.group(1), match.group(2)
        ids = [str(i) for i in ((params or {}).get("ids") or [])]
        if head == "a":  # forward: (a)-[:T]->(b), seek on a
            hits = [d for s, r, d in self.edges if r == edge_type and s in ids]
        else:  # reverse: (b)-[:T]->(a), seek on a
            hits = [s for s, r, d in self.edges if r == edge_type and d in ids]
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for nid in hits:  # RETURN DISTINCT id(b)
            if nid in seen:
                continue
            seen.add(nid)
            out.append(self._row(nid))
        limit = _LIMIT_RE.search(cypher)
        if limit:
            out = out[: int(limit.group(1))]
        return out


def _expansion_cyphers(graph: MockGraphDB) -> list[str]:
    return [c for c in _cyphers(graph) if _EXPAND_FRAGMENT in c]


async def _walk(
    graph: MockGraphDB,
    *,
    start_name: str = "A",
    direction: str = "forward",
    edge_types: Any = ("CALLS",),
    max_depth: int = 2,
    fan_out_limit: int = 100,
    result_limit: int = 200,
    timeout_s: float = 30.0,
    scope_pred: str = "",
    tenant: Any = None,
    label_scope_expanded: bool = False,
    tool: str | None = None,
    degree: int | None = None,
) -> BFSResult:
    """``bfs_walk`` with the bounds a caller would pass, so each test only
    states the one it is exercising.

    ``tool`` / ``degree`` are the observability inputs (R8.1) and default
    to omitted, which is what every pre-8.3 test passed.
    """
    return await bfs_walk(
        graph,
        start_name=start_name,
        direction=direction,
        edge_types=list(edge_types),
        max_depth=max_depth,
        fan_out_limit=fan_out_limit,
        result_limit=result_limit,
        timeout_s=timeout_s,
        scope_pred=scope_pred,
        tenant=tenant,
        label_scope_expanded=label_scope_expanded,
        tool=tool,
        degree=degree,
    )


def _timeout_exc() -> BaseException:
    from src.data.neptune_adapter import NeptuneAdapterError

    return NeptuneAdapterError("query exceeded 30.0s statement timeout")


# ── basic multi-hop traversal (R2.1, R2.2) ─────────────────────────────


async def test_bfs_walk_two_hop_discovers_transitive_nodes() -> None:
    """A 2-hop walk over one type discovers the anchor's neighbor and its
    neighbor, each tagged with the hop it was first seen at (R2.1)."""
    graph = _WalkGraph([("A", "CALLS", "B"), ("B", "CALLS", "C")])
    result = await _walk(graph, max_depth=2)

    assert [n["name"] for n in result.nodes] == ["B", "C"]
    assert [n["hop"] for n in result.nodes] == [1, 2]
    assert result.hops_expanded == 2
    assert result.truncated is False
    assert result.wall_clock_ms >= 0


async def test_bfs_walk_excludes_the_anchor_from_nodes() -> None:
    """The Anchor_Node is the caller's own input and is never listed as a
    discovered node, even when it is reachable from itself."""
    graph = _WalkGraph([("A", "CALLS", "B"), ("B", "CALLS", "A")])
    result = await _walk(graph, max_depth=3)
    assert "A" not in [n["nid"] for n in result.nodes]


async def test_bfs_walk_tags_each_node_with_reltype_and_direction() -> None:
    """Each merged node records which edge type led to it and in which
    direction, so a caller can render the provenance of the hop."""
    graph = _WalkGraph([("A", "CALLS", "B"), ("A", "USES", "C")])
    result = await _walk(graph, edge_types=("CALLS", "USES"), max_depth=1)

    by_name = {n["name"]: n for n in result.nodes}
    assert by_name["B"]["relType"] == "CALLS"
    assert by_name["C"]["relType"] == "USES"
    assert {n["direction"] for n in result.nodes} == {"forward"}


async def test_bfs_walk_carries_node_metadata_from_the_expansion() -> None:
    """``name`` / ``path`` / ``labels`` come straight from the expansion
    row, with ``labels`` always a list."""
    graph = _WalkGraph(
        [("A", "CALLS", "b1")],
        node_meta={
            "b1": {
                "name": "exglobal_forecast.sh",
                "path": "scripts/exglobal_forecast.sh",
                "labels": ["File", "ShellScript"],
            }
        },
    )
    result = await _walk(graph, max_depth=1)
    assert result.nodes[0]["name"] == "exglobal_forecast.sh"
    assert result.nodes[0]["path"] == "scripts/exglobal_forecast.sh"
    assert result.nodes[0]["labels"] == ["File", "ShellScript"]


async def test_bfs_walk_query_count_is_linear_in_depth_and_types() -> None:
    """One query per type per hop, plus the anchor resolution -- the whole
    point of decomposing the Multi_Type_Expansion (R2.2)."""
    graph = _WalkGraph(
        [
            ("A", "CALLS", "B"),
            ("A", "USES", "C"),
            ("B", "CALLS", "D"),
        ]
    )
    result = await _walk(graph, edge_types=("CALLS", "USES"), max_depth=2)

    assert result.hops_expanded == 2
    assert result.queries_issued == 1 + 2 * 2
    assert len(_expansion_cyphers(graph)) == 4


async def test_bfs_walk_folds_duplicate_edge_types() -> None:
    """A repeated type is expanded once per hop; the redundant copy would
    only be discarded by the visited-set, so it is never issued."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    result = await _walk(
        graph, edge_types=("CALLS", "CALLS", "CALLS"), max_depth=1
    )
    assert result.queries_issued == 1 + 1
    assert [n["name"] for n in result.nodes] == ["B"]


async def test_bfs_walk_drops_unsupported_edge_types() -> None:
    """A type that is not a plain identifier never reaches the graph and
    is not counted in ``queries_issued``."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    result = await _walk(
        graph, edge_types=("CALLS", "CALLS|USES", "", "1BAD"), max_depth=1
    )
    assert result.queries_issued == 1 + 1
    assert len(_expansion_cyphers(graph)) == 1


async def test_bfs_walk_with_no_usable_edge_types_issues_no_expansion(
) -> None:
    graph = _WalkGraph([("A", "CALLS", "B")])
    result = await _walk(graph, edge_types=(), max_depth=3)
    assert result.nodes == []
    assert result.hops_expanded == 0
    assert result.queries_issued == 1
    assert _expansion_cyphers(graph) == []


async def test_bfs_walk_unresolvable_anchor_returns_empty_untruncated(
) -> None:
    """No anchor means no walk; the caller renders its own 'not found'
    notice, so this is not a truncated result."""
    graph = _WalkGraph([("A", "CALLS", "B")], anchor_ids=())
    result = await _walk(graph, max_depth=3)
    assert result.nodes == []
    assert result.hops_expanded == 0
    assert result.queries_issued == 1
    assert result.truncated is False
    assert _expansion_cyphers(graph) == []


async def test_bfs_walk_expands_every_anchor_id_in_one_query() -> None:
    """A name matching several nodes seeds the frontier with all of them,
    still one query per type per hop."""
    graph = _WalkGraph(
        [("A1", "CALLS", "B"), ("A2", "CALLS", "C")],
        anchor_ids=("A1", "A2"),
    )
    result = await _walk(graph, max_depth=1)
    assert sorted(n["name"] for n in result.nodes) == ["B", "C"]
    assert result.queries_issued == 2


# ── cycle prevention (R2.4) ────────────────────────────────────────────


async def test_bfs_walk_two_node_cycle_terminates_without_duplicates(
) -> None:
    """``A -> B -> A`` with depth budget to spare: the visited-set stops
    the walk at the point the cycle closes (R2.4)."""
    graph = _WalkGraph([("A", "CALLS", "B"), ("B", "CALLS", "A")])
    result = await _walk(graph, max_depth=5)

    assert [n["name"] for n in result.nodes] == ["B"]
    nids = [n["nid"] for n in result.nodes]
    assert len(nids) == len(set(nids)), "visited-set let a node in twice"
    # Hop 2 re-reaches the anchor, finds it visited, and empties the
    # frontier -- so the remaining 3 hops of budget are never spent.
    assert result.hops_expanded == 2
    assert result.queries_issued == 1 + 1 * 2


async def test_bfs_walk_three_node_cycle_reports_each_node_once() -> None:
    """``A -> B -> C -> A``: every reachable node appears exactly once, at
    the depth it was first discovered."""
    graph = _WalkGraph(
        [("A", "CALLS", "B"), ("B", "CALLS", "C"), ("C", "CALLS", "A")]
    )
    result = await _walk(graph, max_depth=10)

    assert [(n["name"], n["hop"]) for n in result.nodes] == [
        ("B", 1),
        ("C", 2),
    ]
    assert result.hops_expanded == 3


async def test_bfs_walk_self_loop_does_not_re_expand() -> None:
    graph = _WalkGraph([("A", "CALLS", "A")])
    result = await _walk(graph, max_depth=5)
    assert result.nodes == []
    assert result.hops_expanded == 1


async def test_bfs_walk_diamond_reports_join_node_once() -> None:
    """A node reachable by two paths is merged once, keeping its earliest
    hop -- redundant re-expansion is what the visited-set prevents."""
    graph = _WalkGraph(
        [
            ("A", "CALLS", "B"),
            ("A", "CALLS", "C"),
            ("B", "CALLS", "D"),
            ("C", "CALLS", "D"),
        ]
    )
    result = await _walk(graph, max_depth=3)

    names = [n["name"] for n in result.nodes]
    assert sorted(names) == ["B", "C", "D"]
    assert names.count("D") == 1
    assert next(n for n in result.nodes if n["name"] == "D")["hop"] == 2


# ── early termination (R2.5) ───────────────────────────────────────────


async def test_bfs_walk_stops_when_a_hop_yields_no_new_nodes() -> None:
    """A dead-end branch empties the frontier, which ends the walk with
    depth budget unspent (R2.5)."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    result = await _walk(graph, max_depth=5)

    assert [n["name"] for n in result.nodes] == ["B"]
    assert result.hops_expanded == 2  # hop 2 ran, found nothing, stopped
    # Not 1 + 1 * 5 -- three hops of budget were never issued.
    assert result.queries_issued == 1 + 1 * 2


async def test_bfs_walk_isolated_anchor_stops_after_one_hop() -> None:
    graph = _WalkGraph([("X", "CALLS", "Y")])  # nothing touches A
    result = await _walk(graph, max_depth=4)
    assert result.nodes == []
    assert result.hops_expanded == 1
    assert result.queries_issued == 1 + 1


async def test_bfs_walk_honours_depth_budget_on_a_longer_chain() -> None:
    """The walk stops at ``max_depth`` even when the chain continues."""
    graph = _WalkGraph(
        [
            ("A", "CALLS", "B"),
            ("B", "CALLS", "C"),
            ("C", "CALLS", "D"),
            ("D", "CALLS", "E"),
        ]
    )
    result = await _walk(graph, max_depth=2)
    assert [n["name"] for n in result.nodes] == ["B", "C"]
    assert result.hops_expanded == 2


async def test_bfs_walk_non_positive_depth_falls_back_to_one_hop() -> None:
    graph = _WalkGraph([("A", "CALLS", "B"), ("B", "CALLS", "C")])
    result = await _walk(graph, max_depth=0)
    assert [n["name"] for n in result.nodes] == ["B"]
    assert result.hops_expanded == 1
    assert result.queries_issued == 2


# ── fan-out limit (R2.3) ───────────────────────────────────────────────


async def test_bfs_walk_fan_out_limit_caps_a_hop_and_flags_truncated(
) -> None:
    """The Fan_Out_Limit bounds one type's expansion at one hop, and the
    result is reported as a partial view (R2.3)."""
    graph = _WalkGraph(
        [("A", "CALLS", f"B{i}") for i in range(8)]
    )
    result = await _walk(graph, max_depth=1, fan_out_limit=3)

    assert len(result.nodes) == 3
    assert result.truncated is True
    assert "LIMIT 3" in _expansion_cyphers(graph)[0]


async def test_bfs_walk_fan_out_limit_is_per_type_per_hop() -> None:
    """Two types at one hop can each return up to the limit -- the bound
    is per expansion query, not per hop."""
    graph = _WalkGraph(
        [("A", "CALLS", f"B{i}") for i in range(4)]
        + [("A", "USES", f"C{i}") for i in range(4)]
    )
    result = await _walk(
        graph, edge_types=("CALLS", "USES"), max_depth=1, fan_out_limit=2
    )
    assert len(result.nodes) == 4
    assert result.truncated is True


async def test_bfs_walk_under_fan_out_limit_is_not_truncated() -> None:
    graph = _WalkGraph([("A", "CALLS", "B"), ("A", "CALLS", "C")])
    result = await _walk(graph, max_depth=1, fan_out_limit=10)
    assert len(result.nodes) == 2
    assert result.truncated is False


async def test_bfs_walk_invalid_fan_out_limit_falls_back_to_default(
) -> None:
    graph = _WalkGraph([("A", "CALLS", "B")])
    await _walk(graph, max_depth=1, fan_out_limit=0)
    assert f"LIMIT {BFS_FAN_OUT_LIMIT}" in _expansion_cyphers(graph)[0]


# ── result limit (global cap) ──────────────────────────────────────────


async def test_bfs_walk_result_limit_caps_total_output() -> None:
    """The global cap trims the merged node list and marks the walk
    truncated, independently of the per-hop Fan_Out_Limit."""
    graph = _WalkGraph([("A", "CALLS", f"B{i}") for i in range(6)])
    result = await _walk(
        graph, max_depth=3, fan_out_limit=100, result_limit=2
    )

    assert len(result.nodes) == 2
    assert result.truncated is True
    # The cap also ends the walk: no hop 2 queries were issued.
    assert result.hops_expanded == 1
    assert len(_expansion_cyphers(graph)) == 1


async def test_bfs_walk_result_limit_across_hops() -> None:
    graph = _WalkGraph(
        [("A", "CALLS", "B"), ("B", "CALLS", "C"), ("C", "CALLS", "D")]
    )
    result = await _walk(graph, max_depth=3, result_limit=2)
    assert [n["name"] for n in result.nodes] == ["B", "C"]
    assert result.truncated is True


async def test_bfs_walk_invalid_result_limit_falls_back_to_default(
) -> None:
    """A non-positive cap falls back to ``RESULT_LIMIT`` rather than
    silently returning nothing."""
    graph = _WalkGraph([("A", "CALLS", f"B{i}") for i in range(3)])
    result = await _walk(graph, max_depth=1, result_limit=0)
    assert len(result.nodes) == 3
    assert result.truncated is False
    assert RESULT_LIMIT > 3  # sanity: the fallback is the reason above


# ── timeout handling (R2.7, Property 7) ────────────────────────────────


async def test_bfs_walk_overall_timeout_returns_truncated_not_raise(
) -> None:
    """The whole walk is bounded by one wall clock; expiry yields a
    truncated result instead of an exception (R2.7)."""
    graph = _WalkGraph(
        [("A", "CALLS", "B")], slow_after=0, slow_seconds=5.0
    )
    result = await _walk(graph, max_depth=2, timeout_s=0.05)

    assert result.truncated is True
    assert result.nodes == []


async def test_bfs_walk_overall_timeout_keeps_partial_nodes() -> None:
    """Hops completed before the wall clock expired are still returned --
    a partial view, flagged as such."""
    graph = _WalkGraph(
        [("A", "CALLS", "B"), ("B", "CALLS", "C")],
        slow_after=2,  # anchor + hop 1 are fast; hop 2 stalls
        slow_seconds=5.0,
    )
    result = await _walk(graph, max_depth=2, timeout_s=0.2)

    assert [n["name"] for n in result.nodes] == ["B"]
    assert result.truncated is True
    assert result.hops_expanded == 1


async def test_bfs_walk_hop_timeout_marks_truncated() -> None:
    """A hop absorbed as an empty expansion is not presented as an
    exhausted branch -- the timeout sink flags it."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    graph.add_raise(_EXPAND_FRAGMENT, _timeout_exc())
    result = await _walk(graph, max_depth=2)

    assert result.nodes == []
    assert result.truncated is True


async def test_bfs_walk_hop_error_is_absorbed_without_truncation() -> None:
    """A non-timeout failure is equally graceful, but is not a truncation
    signal -- nothing was cut short by a bound."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    graph.add_raise(_EXPAND_FRAGMENT, RuntimeError("boom"))
    result = await _walk(graph, max_depth=2)

    assert result.nodes == []
    assert result.truncated is False


async def test_bfs_walk_anchor_timeout_yields_empty_result() -> None:
    graph = _WalkGraph([("A", "CALLS", "B")])
    graph.add_raise(_ANCHOR_FRAGMENT, _timeout_exc())
    result = await _walk(graph, max_depth=2)
    assert result.nodes == []
    assert result.queries_issued == 1
    assert _expansion_cyphers(graph) == []


async def test_bfs_walk_one_type_timing_out_keeps_the_other_type() -> None:
    """The hop is the error boundary, so one failing type does not cost
    the walk the types that succeeded."""
    graph = _WalkGraph([("A", "CALLS", "B"), ("A", "USES", "C")])
    graph.add_raise("[:CALLS]", _timeout_exc())
    result = await _walk(
        graph, edge_types=("CALLS", "USES"), max_depth=1
    )

    assert [n["name"] for n in result.nodes] == ["C"]
    assert result.truncated is True


# ── direction handling ─────────────────────────────────────────────────


async def test_bfs_walk_forward_emits_outgoing_pattern() -> None:
    graph = _WalkGraph([("A", "CALLS", "B")])
    await _walk(graph, direction="forward", max_depth=1)
    cypher = _expansion_cyphers(graph)[0]
    assert "MATCH (a)-[:CALLS]->(b)" in cypher
    assert "WHERE id(a) IN $ids" in cypher


async def test_bfs_walk_reverse_emits_incoming_pattern() -> None:
    graph = _WalkGraph([("B", "CALLS", "A")])
    await _walk(graph, direction="reverse", max_depth=1)
    cypher = _expansion_cyphers(graph)[0]
    assert "MATCH (b)-[:CALLS]->(a)" in cypher
    assert "WHERE id(a) IN $ids" in cypher


async def test_bfs_walk_reverse_discovers_callers_not_callees() -> None:
    """The same graph walked in the two directions yields the two
    disjoint neighbourhoods a caller renders separately."""
    edges = [("CALLER", "CALLS", "A"), ("A", "CALLS", "CALLEE")]

    forward = await _walk(_WalkGraph(edges), direction="forward",
                          max_depth=1)
    reverse = await _walk(_WalkGraph(edges), direction="reverse",
                          max_depth=1)

    assert [n["name"] for n in forward.nodes] == ["CALLEE"]
    assert [n["name"] for n in reverse.nodes] == ["CALLER"]
    assert reverse.nodes[0]["direction"] == "reverse"


async def test_bfs_walk_reverse_traverses_multiple_hops_upstream() -> None:
    graph = _WalkGraph(
        [("GRANDPARENT", "CALLS", "PARENT"), ("PARENT", "CALLS", "A")]
    )
    result = await _walk(graph, direction="reverse", max_depth=2)
    assert [n["name"] for n in result.nodes] == ["PARENT", "GRANDPARENT"]
    assert [n["hop"] for n in result.nodes] == [1, 2]


# ── tenant scoping pass-through (R4.1, R4.3) ───────────────────────────


async def test_bfs_walk_scopes_expanded_nodes_when_requested() -> None:
    """With ``label_scope_expanded`` the anchor's predicate is retargeted
    onto the expansion target ``b`` (R4.1)."""
    from src.tools.code_analysis import _scope_and

    catalog = _make_catalog()
    graph = _WalkGraph([("A", "CALLS", "B")])
    async with tenant_scope("gw_v17", catalog) as ctx:
        await _walk(
            graph,
            max_depth=1,
            scope_pred=_scope_and("n"),
            tenant=ctx.tenant,
            label_scope_expanded=True,
        )
    cypher = _expansion_cyphers(graph)[0]
    assert "labels(b)" in cypher
    assert "labels(n)" not in cypher
    assert "GW_V17_" in cypher


async def test_bfs_walk_omits_expansion_scope_for_default_tenant() -> None:
    """The default ``gw`` tenant's baseline nodes are unprefixed, so no
    predicate is emitted on the expansion (R4.3)."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    scope = " AND size([__l IN labels(n) WHERE __l STARTS WITH 'X_']) > 0"
    await _walk(
        graph, max_depth=1, scope_pred=scope, label_scope_expanded=False
    )
    cypher = _expansion_cyphers(graph)[0]
    assert "STARTS WITH" not in cypher
    # The frontier seek is the whole WHERE clause -- no scope appended.
    assert "WHERE id(a) IN $ids RETURN DISTINCT" in cypher
    # The anchor resolution is still scoped either way (R1.4).
    assert scope in _cyphers(graph)[0]


async def test_bfs_walk_passes_tenant_and_timeout_to_every_query() -> None:
    graph = _WalkGraph([("A", "CALLS", "B"), ("B", "CALLS", "C")])
    sentinel = object()
    await _walk(graph, max_depth=2, tenant=sentinel, timeout_s=7.5)

    calls = _query_calls(graph)
    assert len(calls) == 3
    assert all(c[3]["tenant"] is sentinel for c in calls)
    assert all(c[3]["timeout"] == 7.5 for c in calls)


async def test_bfs_walk_binds_frontier_ids_as_a_parameter() -> None:
    """Frontier ids travel as ``$ids``, never interpolated into cypher."""
    graph = _WalkGraph([("A", "CALLS", "B"), ("B", "CALLS", "C")])
    await _walk(graph, max_depth=2)

    expansions = [
        c for c in _query_calls(graph) if _EXPAND_FRAGMENT in c[1][0]
    ]
    assert [c[2] for c in expansions] == [{"ids": ["A"]}, {"ids": ["B"]}]


# ── _expand_one_hop in isolation ───────────────────────────────────────


async def test_expand_one_hop_returns_normalised_node_dicts() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response(
        _EXPAND_FRAGMENT,
        [
            {"nid": 7, "name": "b", "path": "p/b", "labels": ("File",)},
            {"nid": "8", "name": "c", "path": None, "labels": None},
        ],
    )
    nodes = await _expand_one_hop(
        graph, ["1"], "CALLS", "forward", 10, "", None, 30.0
    )
    assert nodes == [
        {"nid": "7", "name": "b", "path": "p/b", "labels": ["File"]},
        {"nid": "8", "name": "c", "path": None, "labels": []},
    ]


async def test_expand_one_hop_skips_malformed_rows() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response(
        _EXPAND_FRAGMENT,
        [
            {"nid": "keep"},
            {"nid": None},
            {"nid": ""},
            {"name": "no-id"},
            ["not", "a", "dict"],  # type: ignore[list-item]
        ],
    )
    nodes = await _expand_one_hop(
        graph, ["1"], "CALLS", "forward", 10, "", None, 30.0
    )
    assert [n["nid"] for n in nodes] == ["keep"]


async def test_expand_one_hop_empty_frontier_issues_no_query() -> None:
    graph = MockGraphDB()
    assert await _expand_one_hop(
        graph, [], "CALLS", "forward", 10, "", None, 30.0
    ) == []
    assert _query_calls(graph) == []


async def test_expand_one_hop_drops_blank_frontier_ids() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response(_EXPAND_FRAGMENT, [])
    await _expand_one_hop(
        graph, ["1", None, "", 2], "CALLS", "forward", 10, "", None, 30.0
    )
    assert _query_calls(graph)[0][2] == {"ids": ["1", "2"]}


@pytest.mark.parametrize(
    "edge_type", ["CALLS|USES", "", "1BAD", "has-dash", "a b", "A;DROP"]
)
async def test_expand_one_hop_refuses_unsupported_edge_type(
    edge_type: str,
) -> None:
    """The type is interpolated, not parameterized, so anything that is
    not a bare identifier is refused before a query is emitted."""
    graph = MockGraphDB()
    assert await _expand_one_hop(
        graph, ["1"], edge_type, "forward", 10, "", None, 30.0
    ) == []
    assert _query_calls(graph) == []


@pytest.mark.parametrize("bad_limit", [0, -5, None, "x"])
async def test_expand_one_hop_invalid_limit_falls_back_to_default(
    bad_limit: Any,
) -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response(_EXPAND_FRAGMENT, [])
    await _expand_one_hop(
        graph, ["1"], "CALLS", "forward", bad_limit, "", None, 30.0
    )
    assert f"LIMIT {BFS_FAN_OUT_LIMIT}" in _cyphers(graph)[0]


async def test_expand_one_hop_retargets_scope_predicate_to_target(
) -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response(_EXPAND_FRAGMENT, [])
    scope = " AND size([__l IN labels(n) WHERE __l STARTS WITH 'GW_V17_']) > 0"
    await _expand_one_hop(
        graph, ["1"], "CALLS", "forward", 10, scope, None, 30.0
    )
    cypher = _cyphers(graph)[0]
    assert "labels(b)" in cypher
    assert "labels(n)" not in cypher


async def test_expand_one_hop_appends_to_timeout_sink_on_timeout() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_raise(_EXPAND_FRAGMENT, _timeout_exc())
    sink: list[str] = []
    nodes = await _expand_one_hop(
        graph, ["1"], "CALLS", "forward", 10, "", None, 30.0,
        timeout_sink=sink,
    )
    assert nodes == []
    assert sink == ["CALLS"]


async def test_expand_one_hop_leaves_sink_empty_on_other_errors() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_raise(_EXPAND_FRAGMENT, RuntimeError("boom"))
    sink: list[str] = []
    assert await _expand_one_hop(
        graph, ["1"], "CALLS", "forward", 10, "", None, 30.0,
        timeout_sink=sink,
    ) == []
    assert sink == []


async def test_expand_one_hop_swallows_error_without_a_sink() -> None:
    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_raise(_EXPAND_FRAGMENT, _timeout_exc())
    assert await _expand_one_hop(
        graph, ["1"], "CALLS", "forward", 10, "", None, 30.0
    ) == []


# ── module helpers ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [(5, 5), (1, 1), (0, 9), (-3, 9), (None, 9), ("x", 9), ("4", 4)],
)
def test_positive_int_coerces_or_falls_back(
    value: Any, expected: int
) -> None:
    assert _positive_int(value, 9) == expected


def test_valid_edge_types_filters_and_dedupes_in_order() -> None:
    assert _valid_edge_types(
        ["CALLS", "USES", "CALLS", "A|B", "", None, "_X1"]  # type: ignore
    ) == ["CALLS", "USES", "_X1"]


def test_valid_edge_types_handles_none() -> None:
    assert _valid_edge_types(None) == []


@pytest.mark.parametrize(
    "name,ok",
    [
        ("CALLS", True),
        ("_private", True),
        ("A1_b2", True),
        ("CALLS|USES", False),
        ("1CALLS", False),
        ("has-dash", False),
        ("", False),
    ],
)
def test_edge_type_re_accepts_only_identifiers(
    name: str, ok: bool
) -> None:
    assert bool(_EDGE_TYPE_RE.match(name)) is ok


def test_is_timeout_error_recognises_statement_timeouts() -> None:
    from src.data.neptune_adapter import NeptuneAdapterError

    assert _is_timeout_error(asyncio.TimeoutError()) is True
    assert _is_timeout_error(
        NeptuneAdapterError("query exceeded 30.0s STATEMENT TIMEOUT")
    ) is True
    assert _is_timeout_error(RuntimeError("connection reset")) is False


# ══ Task 7.3 — Label_Scope_Predicate on expanded nodes ═════════════════
# Validates R4.1 (the BFS_Walker's expansion queries scope the *target*
# node, not only the anchor), R4.3 (no predicate is emitted when none is
# expressible), R4.4 (anchor and target fragments come from the same
# ``_scope_and`` helper).
#
# READ THIS BEFORE TRUSTING R4.3's WORDING
# ----------------------------------------
# R4.3 says the predicate on expanded nodes "SHALL be omitted" for the
# default ``gw`` tenant, on the reasoning that gw's nodes are unprefixed
# and a filter would exclude them. That reasoning does not describe what
# ``tenant_label_predicate`` actually does, and task 7.1 encoded the real
# behaviour instead:
#
#   * Non-default tenant (``label_prefix="GW_V17_"``) -> the INCLUSION
#     form, ``size([__lbl IN labels(n) WHERE __lbl STARTS WITH
#     'GW_V17_']) > 0``.
#   * Default ``gw`` tenant, catalog declaring other prefixes -> the
#     EXCLUSION form, ``size([__lbl IN labels(n) WHERE __lbl STARTS WITH
#     'GW_V17_' OR ...]) = 0``. This admits *every* unprefixed baseline
#     node and rejects only another tenant's prefixed nodes, so applying
#     it to the expansion target cannot exclude gw's own nodes -- and
#     omitting it would let a ``GW_V17_``-prefixed neighbor of a baseline
#     anchor into a ``gw`` walk.
#   * Only when no scoping is expressible at all -- no active tenant
#     context, or a catalog in which no tenant declares a label prefix --
#     is the fragment genuinely ``""``, and *that* is the case in which
#     no predicate is emitted.
#
# So the tests below assert an exclusion predicate IS applied on the
# expansion target for the default tenant, and test the truly-empty case
# separately. The distinction matters: an implementation that literally
# followed R4.3 would leak cross-tenant neighbours into gw walks.


def _gw_only_catalog() -> TenantCatalog:
    """Single-tenant catalog: ``gw`` alone, declaring no label prefix.

    The only shape in which ``tenant_label_predicate`` returns ``""`` for
    an *active* tenant -- there is no other prefix to exclude. Used for
    the genuinely-unscoped case R4.3 is describing.
    """
    gw = Tenant(
        tenant_id="gw",
        repo_ref="NOAA-EMC/global-workflow",
        branch="develop",
        index_prefix="",
        label_prefix="",
        workflow_subdir="global-workflow",
        lifecycle="production",
    )
    return TenantCatalog(
        schema_version=1,
        defaults=CatalogDefaults(tenant_id="gw"),
        tenants=(gw,),
    )


# ── _retarget_scope_pred (the R4.4 mechanism) ──────────────────────────


@pytest.mark.parametrize("var", ["n", "a", "source", "start", "f", "t", "src"])
async def test_retarget_scope_pred_rewrites_any_source_variable(
    var: str,
) -> None:
    """A fragment built for *any* caller variable retargets onto ``b``.

    The walker's callers do not agree on an anchor variable name -- the
    tools build ``_scope_and("n")``, ``_scope_and("a")``,
    ``_scope_and("source")``, ``_scope_and("start")`` -- so the rewrite
    matches on the ``labels(...)`` call rather than on a literal variable
    name. A name-specific rewrite would silently no-op on the others and
    emit a predicate over a variable the expansion never binds (R4.4).
    """
    from src.tools.code_analysis import _scope_and

    async with tenant_scope("gw_v17", _make_catalog()):
        fragment = _scope_and(var)
        assert f"labels({var})" in fragment
        retargeted = _retarget_scope_pred(fragment, "b")
        # Byte-identical to building the fragment for ``b`` directly --
        # the strongest form of the R4.4 consistency claim.
        assert retargeted == _scope_and("b")
    assert f"labels({var})" not in retargeted
    assert "labels(b)" in retargeted


def test_retarget_scope_pred_keeps_an_empty_fragment_empty() -> None:
    """No fragment in, no filter out -- the caller emits no predicate."""
    assert _retarget_scope_pred("", "b") == ""


def test_retarget_scope_pred_drops_fragment_without_a_labels_call() -> None:
    """A non-empty fragment carrying no ``labels(...)`` call cannot have
    come from ``tenant_label_predicate``; it is dropped rather than
    emitted against a variable the expansion pattern never binds."""
    assert _retarget_scope_pred(" AND n.tenant_id = 'gw_v17'", "b") == ""


def test_retarget_scope_pred_changes_only_the_variable() -> None:
    """Retargeting is a one-token substitution: the comprehension
    binding, the prefix literal and the comparison are untouched."""
    fragment = (
        " AND size([__lbl IN labels(alpha) "
        "WHERE __lbl STARTS WITH 'GW_V17_']) > 0"
    )
    assert _retarget_scope_pred(fragment, "b") == fragment.replace(
        "labels(alpha)", "labels(b)"
    )


@pytest.mark.parametrize(
    "call", ["labels(n)", "labels( n )", "labels(  node_1  )"]
)
def test_retarget_scope_pred_tolerates_whitespace_in_the_call(
    call: str,
) -> None:
    fragment = f" AND size([__lbl IN {call} WHERE __lbl STARTS WITH 'X_']) > 0"
    assert "labels(b)" in _retarget_scope_pred(fragment, "b")
    assert call not in _retarget_scope_pred(fragment, "b")


def test_retarget_scope_pred_rewrites_every_labels_call() -> None:
    """Defensive: a fragment with two calls has both retargeted, so no
    stale variable survives into the emitted query."""
    fragment = " AND size(labels(n)) > 0 AND size(labels(n)) < 9"
    assert "labels(n)" not in _retarget_scope_pred(fragment, "b")
    assert _retarget_scope_pred(fragment, "b").count("labels(b)") == 2


# ── expansion queries: non-default tenant (R4.1) ───────────────────────


async def test_bfs_walk_expansion_scopes_target_with_inclusion_form() -> None:
    """Non-default tenant: the expansion query filters ``labels(b)`` with
    the INCLUSION form, so a neighbour outside the tenant is rejected
    server-side before it enters the frontier (R4.1)."""
    from src.tools.code_analysis import _scope_and

    graph = _WalkGraph([("A", "CALLS", "B")])
    async with tenant_scope("gw_v17", _make_catalog()) as ctx:
        scope = _scope_and("n")
        await _walk(
            graph,
            max_depth=1,
            scope_pred=scope,
            tenant=ctx.tenant,
            label_scope_expanded=True,
        )
        expected = _scope_and("b")

    cypher = _expansion_cyphers(graph)[0]
    assert expected in cypher
    assert "STARTS WITH 'GW_V17_']) > 0" in cypher, "inclusion form"
    assert "labels(n)" not in cypher, "anchor variable leaked into the hop"


async def test_bfs_walk_scopes_target_on_every_hop_and_edge_type() -> None:
    """Scoping is per-hop and per-type: every expansion query the walk
    issues carries the target predicate, not just the first (R4.1)."""
    from src.tools.code_analysis import _scope_and

    graph = _WalkGraph(
        [("A", "CALLS", "B"), ("A", "USES", "C"), ("B", "CALLS", "D")]
    )
    async with tenant_scope("gw_v17", _make_catalog()) as ctx:
        await _walk(
            graph,
            max_depth=2,
            edge_types=("CALLS", "USES"),
            scope_pred=_scope_and("n"),
            tenant=ctx.tenant,
            label_scope_expanded=True,
        )
        expected = _scope_and("b")

    expansions = _expansion_cyphers(graph)
    assert len(expansions) == 4, "2 types x 2 hops"
    assert all(expected in c for c in expansions)


async def test_bfs_walk_scopes_the_discovered_node_when_reversed() -> None:
    """In the reverse pattern ``MATCH (b)-[:T]->(a)`` the *discovered*
    node is still ``b`` -- only the arrow moves -- so the same retargeted
    fragment scopes the right end in both directions (R4.1)."""
    from src.tools.code_analysis import _scope_and

    graph = _WalkGraph([("B", "CALLS", "A")])
    async with tenant_scope("gw_v17", _make_catalog()) as ctx:
        await _walk(
            graph,
            direction="reverse",
            max_depth=1,
            scope_pred=_scope_and("n"),
            tenant=ctx.tenant,
            label_scope_expanded=True,
        )
        expected = _scope_and("b")

    cypher = _expansion_cyphers(graph)[0]
    assert "MATCH (b)-[:CALLS]->(a)" in cypher
    assert expected in cypher
    # The frontier seek stays on the anchor end; the scope on the target.
    assert "WHERE id(a) IN $ids" in cypher


# ── expansion queries: default gw tenant (the R4.3 correction) ─────────


async def test_bfs_walk_expansion_scopes_target_with_exclusion_form() -> None:
    """Default ``gw`` tenant, multi-tenant catalog: a predicate IS applied
    to the expansion target -- the EXCLUSION form.

    This is the test whose expectation R4.3's wording gets wrong. gw's
    fragment is ``size([... STARTS WITH 'GW_V17_']) = 0``, which admits
    every unprefixed baseline node, so applying it to ``labels(b)``
    cannot exclude gw's own nodes; what it does exclude is a
    ``GW_V17_``-prefixed neighbour reachable from a baseline anchor. R4.3
    is only satisfied literally in the no-scoping-expressible case, which
    ``test_bfs_walk_emits_no_target_predicate_*`` below cover.
    """
    from src.tools.code_analysis import _scope_and

    graph = _WalkGraph([("A", "CALLS", "B")])
    async with tenant_scope("gw", _make_catalog()) as ctx:
        scope = _scope_and("n")
        assert scope, "default gw still yields a predicate in this catalog"
        await _walk(
            graph,
            max_depth=1,
            scope_pred=scope,
            tenant=ctx.tenant,
            label_scope_expanded=True,
        )
        expected = _scope_and("b")

    cypher = _expansion_cyphers(graph)[0]
    assert expected in cypher
    assert "STARTS WITH 'GW_V17_']) = 0" in cypher, "exclusion form"
    assert "]) > 0" not in cypher, "gw must not get the inclusion form"
    assert "labels(n)" not in cypher


# ── the genuinely-unscoped cases (what R4.3 actually describes) ────────


async def test_bfs_walk_emits_no_target_predicate_for_a_soleeeee_tenant(
) -> None:
    """A catalog in which no tenant declares a label prefix has nothing to
    include or exclude, so ``_scope_and`` is ``""`` and no predicate is
    emitted -- on the expansion *or* the anchor resolution (R4.3)."""
    from src.tools.code_analysis import _scope_and

    graph = _WalkGraph([("A", "CALLS", "B")])
    async with tenant_scope("gw", _gw_only_catalog()) as ctx:
        scope = _scope_and("n")
        assert scope == "", "no prefix in the catalog -> nothing to scope by"
        await _walk(
            graph,
            max_depth=1,
            scope_pred=scope,
            tenant=ctx.tenant,
            label_scope_expanded=bool(scope),
        )

    for cypher in _cyphers(graph):
        assert "STARTS WITH" not in cypher
        assert "size([" not in cypher
    # The whole WHERE clause of the hop is the frontier seek.
    assert (
        "WHERE id(a) IN $ids RETURN DISTINCT" in _expansion_cyphers(graph)[0]
    )


async def test_bfs_walk_emits_no_target_predicate_outside_a_tenant_scope(
) -> None:
    """No active tenant context -> ``_scope_and`` is ``""`` -> the walk is
    emitted unscoped end to end (R4.3)."""
    from src.tools.code_analysis import _scope_and

    assert _scope_and("n") == ""
    graph = _WalkGraph([("A", "CALLS", "B")])
    await _walk(graph, max_depth=1, scope_pred=_scope_and("n"))
    for cypher in _cyphers(graph):
        assert "STARTS WITH" not in cypher


async def test_bfs_walk_opt_out_scopes_the_anchor_but_not_the_target(
) -> None:
    """``label_scope_expanded=False`` is the *opt-out* knob, distinct from
    the empty-fragment case: the anchor resolution stays scoped (R1.4)
    while the expansion emits no target predicate (R4.3).

    Every production caller passes ``bool(scope_pred)``, so this shape is
    reachable only by an explicit opt-out -- which is why it is tested
    separately from the default-tenant behaviour above rather than being
    conflated with it.
    """
    from src.tools.code_analysis import _scope_and

    graph = _WalkGraph([("A", "CALLS", "B")])
    async with tenant_scope("gw_v17", _make_catalog()) as ctx:
        scope = _scope_and("n")
        await _walk(
            graph,
            max_depth=1,
            scope_pred=scope,
            tenant=ctx.tenant,
            label_scope_expanded=False,
        )

    assert scope in _cyphers(graph)[0], "anchor resolution stays scoped"
    cypher = _expansion_cyphers(graph)[0]
    assert "STARTS WITH" not in cypher
    assert "WHERE id(a) IN $ids RETURN DISTINCT" in cypher


# ── consistency: one helper for anchor and target (R4.4) ──────────────


@pytest.mark.parametrize("tenant_id", ["gw", "gw_v17"])
async def test_bfs_walk_anchor_and_target_share_one_scope_and_output(
    tenant_id: str,
) -> None:
    """R4.4 asserted structurally, not by string-matching a hardcoded
    predicate: the anchor query carries ``_scope_and("n")`` verbatim, and
    the expansion carries exactly that fragment retargeted onto ``b``,
    which is byte-identical to ``_scope_and("b")``.

    Parametrized over both tenants because the two take *different*
    predicate forms (inclusion vs exclusion) and the consistency
    guarantee has to hold for both.
    """
    from src.tools.code_analysis import _scope_and

    graph = _WalkGraph([("A", "CALLS", "B")])
    async with tenant_scope(tenant_id, _make_catalog()) as ctx:
        scope = _scope_and("n")
        await _walk(
            graph,
            max_depth=1,
            scope_pred=scope,
            tenant=ctx.tenant,
            label_scope_expanded=True,
        )
        target_scope = _scope_and("b")

    assert scope in _cyphers(graph)[0]
    assert target_scope in _expansion_cyphers(graph)[0]
    assert target_scope == _retarget_scope_pred(scope, "b")
    # Same mechanism, one variable apart -- not two hand-written filters.
    assert target_scope == scope.replace("labels(n)", "labels(b)")


async def test_bfs_walk_anchor_scope_is_unchanged_by_target_scoping(
) -> None:
    """Turning target scoping on must not perturb the anchor resolution's
    own fragment -- the two are the same helper output applied to two
    variables, not one fragment mutated in place (R4.4)."""
    from src.tools.code_analysis import _scope_and

    async with tenant_scope("gw_v17", _make_catalog()) as ctx:
        scope = _scope_and("n")
        scoped = _WalkGraph([("A", "CALLS", "B")])
        await _walk(
            scoped, max_depth=1, scope_pred=scope, tenant=ctx.tenant,
            label_scope_expanded=True,
        )
        unscoped = _WalkGraph([("A", "CALLS", "B")])
        await _walk(
            unscoped, max_depth=1, scope_pred=scope, tenant=ctx.tenant,
            label_scope_expanded=False,
        )

    assert _cyphers(scoped)[0] == _cyphers(unscoped)[0]


async def test_expand_one_hop_scope_is_the_only_added_where_term() -> None:
    """The retargeted fragment is appended to the frontier seek as an
    ``AND`` term -- it does not replace or reorder the seek, so the
    index-seekable ``id(a) IN $ids`` lookup is preserved (R4.1)."""
    from src.tools.code_analysis import _scope_and

    graph = MockGraphDB()
    graph.canned_rows = []
    graph.add_response(_EXPAND_FRAGMENT, [])
    async with tenant_scope("gw_v17", _make_catalog()):
        await _expand_one_hop(
            graph, ["1"], "CALLS", "forward", 10, _scope_and("n"), None, 30.0
        )
        expected = _scope_and("b")

    cypher = _cyphers(graph)[0]
    assert f"WHERE id(a) IN $ids{expected} RETURN DISTINCT" in cypher


# ══ Task 8.3 — BFS observability (log lines + response indicator) ══════
# Validates R8.1 (an activation log line naming the tool, the anchor, the
# measured degree and the threshold that selected the walk), R8.2 (a
# completion line carrying the node / query / wall-clock counters, emitted
# even for a walk that discovered nothing), R8.3 (no credentials and no
# full payloads in either line), and R8.4 (the
# ``[optimized: BFS walker, ...]`` response indicator, present when a walk
# ran and absent on the single-query path).
#
# The two log lines are asserted against ``bfs_walk`` itself rather than
# through a tool, because task 8.1 deliberately emits them inside the
# walker -- one format, one site, so a fallback-chain activation that no
# strategy selector decided is logged exactly like a selected one. The
# tool-level half of R8.4 (the indicator reaching a rendered response)
# lives with each tool's own suite, where the server fixtures are:
# ``test_code_analysis_tools.py`` for ``trace_execution_path``,
# ``find_callers_callees`` and ``trace_full_execution_chain``, and
# ``test_graph_rag_tools.py`` for ``trace_data_flow``.


#: The walker's logger. Records are filtered by name so an assertion
#: cannot be satisfied (or broken) by an unrelated module's line.
_WALKER_LOGGER = "src.tools._bfs_walker"


def _log_lines(
    caplog: pytest.LogCaptureFixture, marker: str
) -> list[str]:
    """The walker's formatted log lines containing ``marker``."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _WALKER_LOGGER and marker in r.getMessage()
    ]


def _walker_log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every walker log line from this walk, joined.

    Used by the R8.3 leak assertions in preference to ``caplog.text``:
    the requirement is about what *the walker* logs, and scoping to its
    records keeps a future unrelated line from turning a leak assertion
    into a false failure -- or, worse, from being the thing that
    accidentally satisfies one.
    """
    return "\n".join(
        r.getMessage()
        for r in caplog.records
        if r.name == _WALKER_LOGGER
    )


class _SecretTenant:
    """Tenant stand-in whose ``repr`` carries a marker no log line may
    reproduce (R8.3).

    The real tenant object carries deployment configuration, so the
    concrete risk R8.3 guards against is a log line interpolating the
    tenant itself (``%s`` on the object) rather than only the anchor and
    the counters. A double whose string form is unmistakable makes that
    testable without inventing a credential-bearing catalog entry.
    """

    SECRET = "AKIAIOSFODNN7EXAMPLE/session-token"

    label_prefix = "GW_V17_"
    index_prefix = "gw_v17_"

    def __repr__(self) -> str:
        return f"<Tenant secret={self.SECRET}>"

    __str__ = __repr__


def _result(**overrides: Any) -> BFSResult:
    """:class:`BFSResult` with the counters supplied rather than measured.

    The indicator formats the counters verbatim, so asserting its exact
    text needs a deterministic ``wall_clock_ms`` -- which a real walk
    cannot give.
    """
    fields: dict[str, Any] = {
        "nodes": [],
        "hops_expanded": 0,
        "queries_issued": 1,
        "wall_clock_ms": 0,
        "truncated": False,
    }
    fields.update(overrides)
    return BFSResult(**fields)


# ── activation log line (R8.1) ─────────────────────────────────────────


async def test_bfs_walk_logs_activation_with_the_required_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The ACTIVATED line names the tool, the anchor, the measured degree
    and the threshold that selected the walk, plus the direction and depth
    budget it is running under (R8.1)."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        await _walk(
            graph,
            max_depth=2,
            tool="find_callers_callees",
            degree=42,
        )

    lines = _log_lines(caplog, "ACTIVATED")
    assert len(lines) == 1, "one activation line per walk"
    line = lines[0]
    assert line.startswith("[bfs-walker] ACTIVATED ")
    assert "tool=find_callers_callees" in line
    assert "anchor=A" in line
    assert "degree=42" in line
    assert f"threshold={BFS_ACTIVATION_THRESHOLD}" in line
    assert "direction=forward" in line
    assert "max_depth=2" in line


async def test_bfs_walk_logs_activation_at_info_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both lines are ``info``, not ``debug`` -- R8.1/R8.2 exist so an
    operator tuning the activation threshold sees them without turning on
    debug logging for the whole server."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        await _walk(graph, max_depth=1, tool="trace_data_flow")

    levels = {
        r.levelno
        for r in caplog.records
        if r.name == _WALKER_LOGGER
        and ("ACTIVATED" in r.getMessage() or "COMPLETED" in r.getMessage())
    }
    assert levels == {logging.INFO}


async def test_bfs_walk_logs_unknown_tool_and_degree_when_omitted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unprobed degree is logged as ``unknown``, not as a number an
    operator could mistake for a measurement, and an internal caller that
    named no tool reports ``tool=unknown`` (R8.1)."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        await _walk(graph, max_depth=1)

    line = _log_lines(caplog, "ACTIVATED")[0]
    assert "tool=unknown" in line
    assert "degree=unknown" in line
    assert "degree=None" not in line


async def test_bfs_walk_logs_activation_before_resolving_the_anchor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The activation line is emitted up front, so a walk whose anchor
    never resolves is still visible as an activation that spent a query
    (R8.1) -- the tuning signal R8.2's unconditional completion line
    exists for."""
    graph = _WalkGraph([], anchor_ids=())
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        result = await _walk(graph, max_depth=2, tool="trace_data_flow")

    assert result.nodes == []
    assert len(_log_lines(caplog, "ACTIVATED")) == 1
    assert "max_depth=2" in _log_lines(caplog, "ACTIVATED")[0]


async def test_bfs_walk_logs_the_clamped_depth_not_the_requested_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``max_depth`` in the line is the budget actually in force, so the
    logged bound matches the walk's behaviour rather than the caller's
    request (R8.1)."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        await _walk(graph, max_depth=0)  # coerced to 1 by _positive_int

    assert "max_depth=1" in _log_lines(caplog, "ACTIVATED")[0]


# ── completion log line (R8.2) ─────────────────────────────────────────


async def test_bfs_walk_logs_completion_with_the_walks_own_counters(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The COMPLETED line carries the node count, the query count and the
    wall clock, and every number is the one the returned
    :class:`BFSResult` reports -- the log and the R8.4 indicator describe
    the same walk (R8.2)."""
    graph = _WalkGraph([("A", "CALLS", "B"), ("B", "CALLS", "C")])
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        result = await _walk(
            graph, max_depth=2, tool="trace_data_flow", degree=42
        )

    lines = _log_lines(caplog, "COMPLETED")
    assert len(lines) == 1, "one completion line per walk"
    line = lines[0]
    assert line.startswith("[bfs-walker] COMPLETED ")
    assert "tool=trace_data_flow" in line
    assert "anchor=A" in line
    assert f"nodes={len(result.nodes)}" in line
    assert f"queries={result.queries_issued}" in line
    assert f"hops={result.hops_expanded}" in line
    assert f"wall_ms={result.wall_clock_ms}" in line
    # Anti-vacuity: the counters are real, not all zero.
    assert result.hops_expanded == 2
    assert len(result.nodes) == 2


@pytest.mark.parametrize(
    "anchor_ids, expected_queries, expected_hops",
    [
        pytest.param((), 1, 0, id="anchor-never-resolved"),
        pytest.param(("A",), 2, 1, id="hop-found-nothing"),
    ],
)
async def test_bfs_walk_logs_completion_even_with_zero_nodes(
    caplog: pytest.LogCaptureFixture,
    anchor_ids: tuple[str, ...],
    expected_queries: int,
    expected_hops: int,
) -> None:
    """A walk that discovered nothing still logs its completion (R8.2).

    Both zero-node shapes are covered because they cost different
    amounts, and the reason R8.2 makes the line unconditional is exactly
    that: this is the walk that spent queries and wall clock for no rows,
    i.e. the cheapest evidence that BFS_ACTIVATION_THRESHOLD is set too
    low. Logging only on success would hide it.
    """
    graph = _WalkGraph([], anchor_ids=anchor_ids)
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        result = await _walk(graph, max_depth=1, tool="trace_data_flow")

    assert result.nodes == []
    line = _log_lines(caplog, "COMPLETED")[0]
    assert "nodes=0" in line
    assert f"queries={expected_queries}" in line
    assert f"hops={expected_hops}" in line
    assert "wall_ms=" in line


async def test_bfs_walk_logs_completion_after_a_wall_clock_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A truncated walk reports too: the completion line is emitted on the
    partial-result path as well, so a walk cut short by its wall-clock
    bound is not silently missing from the log (R8.2)."""
    graph = _WalkGraph(
        [("A", "CALLS", "B"), ("B", "CALLS", "C")],
        slow_after=1,
        slow_seconds=5.0,
    )
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        result = await _walk(graph, max_depth=3, timeout_s=0.05)

    assert result.truncated is True
    assert len(_log_lines(caplog, "COMPLETED")) == 1


# ── no credentials, no payloads (R8.3) ─────────────────────────────────


async def test_bfs_walk_logs_leak_neither_tenant_nor_scope_predicate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Neither the tenant object nor the Label_Scope_Predicate reaches the
    log (R8.3).

    The tenant is the one argument that can carry deployment
    configuration, and the predicate embeds the tenant's label prefix; the
    walker takes both and logs neither. Asserted with a tenant double
    whose string form is unmistakable, so an accidental ``%s`` on the
    object would fail loudly rather than blend into the line.
    """
    from src.tools.code_analysis import _scope_and

    graph = _WalkGraph([("A", "CALLS", "B")])
    async with tenant_scope("gw_v17", _make_catalog()):
        scope = _scope_and("n")
        assert scope, "anti-vacuity: there is a predicate to leak"
        with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
            await _walk(
                graph,
                max_depth=1,
                scope_pred=scope,
                tenant=_SecretTenant(),
                label_scope_expanded=True,
                tool="trace_data_flow",
                degree=42,
            )

    text = _walker_log_text(caplog)
    assert "ACTIVATED" in text and "COMPLETED" in text
    assert _SecretTenant.SECRET not in text
    assert "Tenant" not in text
    assert "GW_V17_" not in text
    assert "labels(" not in text
    assert "STARTS WITH" not in text


async def test_bfs_walk_logs_no_discovered_node_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Discovered nodes are reported as a count, never as their contents
    (R8.3). The anchor name is logged deliberately -- it is the caller's
    own input and the key an operator correlates on -- but a node's
    ``name`` / ``path`` is result payload and stays out."""
    graph = _WalkGraph(
        [("A", "CALLS", "b1")],
        node_meta={
            "b1": {
                "name": "PAYLOAD_NODE_NAME",
                "path": "ush/payload_should_not_be_logged.sh",
                "labels": ["File", "ShellScript"],
            }
        },
    )
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        result = await _walk(graph, max_depth=1, tool="trace_data_flow")

    assert len(result.nodes) == 1, "anti-vacuity: a payload existed"
    text = _walker_log_text(caplog)
    assert "PAYLOAD_NODE_NAME" not in text
    assert "ush/payload_should_not_be_logged.sh" not in text
    assert "ShellScript" not in text
    # The count is what the requirement asks for, and it is present.
    assert "nodes=1" in text


async def test_bfs_walk_logs_no_cypher_or_frontier_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The emitted cypher and the resolved frontier ids are not logged
    either -- a hop's query text carries the scope predicate and the ids
    are graph internals (R8.3)."""
    graph = _WalkGraph([("A", "CALLS", "B")])
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        await _walk(graph, max_depth=1, tool="trace_data_flow")

    text = _walker_log_text(caplog)
    assert "MATCH" not in text
    assert "RETURN" not in text
    assert "$ids" not in text


# ── response indicator (R8.4) ──────────────────────────────────────────


def test_bfs_optimized_header_formats_the_documented_indicator() -> None:
    """The indicator is exactly the design's format -- callers recognize
    it by shape, so the text is asserted verbatim (R8.4)."""
    result = _result(
        nodes=[{"nid": str(i)} for i in range(42)],
        hops_expanded=3,
        wall_clock_ms=847,
    )
    assert bfs_optimized_header(result) == (
        "[optimized: BFS walker, 3 hops, 42 nodes, 847ms]"
    )


def test_bfs_optimized_header_is_empty_when_no_walk_ran() -> None:
    """No walk, no indicator: the single-query path renders exactly as it
    did before task 8.2 (R8.4, R5.1)."""
    assert bfs_optimized_header() == ""
    assert bfs_optimized_header(None) == ""
    assert bfs_optimized_header(None, None) == ""


def test_bfs_optimized_header_reports_a_walk_that_found_nothing() -> None:
    """A zero-node walk still gets an indicator: the line answers *which
    strategy produced this response*, which is as true of a thin response
    as of a full one, and it is what an operator correlates against the
    COMPLETED log line (R8.4)."""
    assert bfs_optimized_header(_result(queries_issued=1)) == (
        "[optimized: BFS walker, 0 hops, 0 nodes, 0ms]"
    )


def test_bfs_optimized_header_aggregates_several_walks() -> None:
    """One response can be produced by several walks (``find_callers_
    callees`` runs one per direction plus an optional cross-language
    one), and they collapse into a single line: depth is the deepest walk,
    nodes and milliseconds are the totals the caller paid (R8.4)."""
    first = _result(
        nodes=[{"nid": "1"}], hops_expanded=1, wall_clock_ms=10
    )
    second = _result(
        nodes=[{"nid": "2"}, {"nid": "3"}], hops_expanded=4, wall_clock_ms=25
    )
    assert bfs_optimized_header(first, second) == (
        "[optimized: BFS walker, 4 hops, 3 nodes, 35ms]"
    )
    # A ``None`` slot is ignored, so an optional walk needs no
    # conditional at the call site.
    assert bfs_optimized_header(first, None, second) == (
        bfs_optimized_header(first, second)
    )


def test_insert_bfs_header_lands_after_the_title() -> None:
    """Placement is line 2, after the markdown heading: a response whose
    first line is a bracketed annotation reads as noise, and consumers
    keying off the leading ``# `` keep working (R8.4)."""
    lines = [
        "# Data Flow Trace: `setuprad`",
        "",
        "## Outgoing Relationships (12)",
    ]
    insert_bfs_header(
        lines,
        _result(nodes=[{"nid": "1"}], hops_expanded=1, wall_clock_ms=34),
    )
    assert lines == [
        "# Data Flow Trace: `setuprad`",
        "[optimized: BFS walker, 1 hops, 1 nodes, 34ms]",
        "",
        "## Outgoing Relationships (12)",
    ]


def test_insert_bfs_header_adds_a_blank_line_when_the_body_is_adjacent(
) -> None:
    """A body that starts immediately after the title gains the separating
    blank line, so the indicator never runs into the first section."""
    lines = ["# Full Execution Chain: X", "## Shell Layer"]
    insert_bfs_header(lines, _result(hops_expanded=2, wall_clock_ms=7))
    assert lines == [
        "# Full Execution Chain: X",
        "[optimized: BFS walker, 2 hops, 0 nodes, 7ms]",
        "",
        "## Shell Layer",
    ]


def test_insert_bfs_header_is_a_noop_on_the_single_query_path() -> None:
    """No walk ran -> the response lines are untouched, which is how the
    single-query and degraded paths stay byte-identical to their pre-8.2
    output (R8.4, R5.1)."""
    lines = ["# Execution Path Trace: foo", "", "## Callees (2)"]
    before = list(lines)
    insert_bfs_header(lines)
    assert lines == before
    insert_bfs_header(lines, None)
    assert lines == before


def test_insert_bfs_header_is_a_noop_on_empty_lines() -> None:
    """Defensive: an empty response body has no title to insert after, so
    nothing is inserted rather than the indicator becoming line 1."""
    lines: list[str] = []
    insert_bfs_header(lines, _result(hops_expanded=1))
    assert lines == []


async def test_bfs_walk_indicator_and_completion_log_agree(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End to end: the indicator a caller renders and the COMPLETED line
    an operator reads report the same three numbers for the same walk
    (R8.2 + R8.4). This is the correlation the two exist to support, so it
    is asserted rather than assumed from their shared source."""
    graph = _WalkGraph([("A", "CALLS", "B"), ("B", "CALLS", "C")])
    with caplog.at_level(logging.INFO, logger=_WALKER_LOGGER):
        result = await _walk(
            graph, max_depth=2, tool="trace_data_flow", degree=42
        )

    header = bfs_optimized_header(result)
    assert header == (
        "[optimized: BFS walker, 2 hops, 2 nodes, "
        f"{result.wall_clock_ms}ms]"
    )
    line = _log_lines(caplog, "COMPLETED")[0]
    assert "nodes=2" in line
    assert "hops=2" in line
    assert f"wall_ms={result.wall_clock_ms}" in line
