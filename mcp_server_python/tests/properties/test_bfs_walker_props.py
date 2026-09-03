"""Property-based tests for ``neptune-traversal-query-optimization``.

Feature: neptune-traversal-query-optimization

One Hypothesis test per correctness property from the design's
"Correctness Properties" section. Landed incrementally by tasks 10.1
through 10.8; this file currently covers:

* Property 1 -- UNION ALL Set Equivalence (R1.3)
* Property 2 -- BFS Subset Guarantee (R2.7)
* Property 3 -- BFS Visited-Set Prevents Cycles (R2.4)
* Property 4 -- BFS Early Termination (R2.5)
* Property 5 -- Strategy Selection Consistency (R3.1, R5.1)
* Property 6 -- Label Scope on Expanded Nodes (R4.1, R4.2)
* Property 7 -- Timeout Fallback Chain (R3.3, R5.5)
* Property 8 -- Fan-Out Limit Bounds Per-Hop Results (R2.3)

The shared harness below (the ``AnchorGraphDB`` semantic double and its
generators) is written to be extended by the remaining properties rather
than re-derived per test, so each task added a ``@given`` block and, at
most, one generator. Two properties sit outside that pattern. Property 5
constrains the pure strategy selector (``_use_bfs``), which touches no
graph, so it draws plain integers and uses none of the doubles. Property
7 is the only one whose claim is about a *tool* rather than the walker,
so it has two tests: one drives the walker under injected timeouts
(``TimeoutInjectingGraphDB``, an ``EdgeGraphDB`` subclass) and one drives
``trace_execution_path``'s whole single-query -> BFS -> Degraded_Result
chain (``ToolTimeoutGraphDB``, over the unit suite's ``MockGraphDB``).

Hermetic: no live Neptune. ``AnchorGraphDB`` is a semantic double -- it
*evaluates* the Cypher it is handed against an in-memory node set instead
of replaying canned rows, which is what makes an equivalence property
meaningful. A fragment-matching double (``tests.conftest.MockGraphDB``)
returns the rows the test seeded regardless of the predicate, so it can
assert on the query *text* but cannot show that two query shapes select
the same nodes.

The walker's entry points are ``async``; each ``@given`` example drives a
fresh event loop via :func:`asyncio.run` and the test functions stay
synchronous so Hypothesis can shrink them.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.data.neptune_adapter import NeptuneAdapterError
from src.tools import code_analysis
from src.tools._bfs_walker import BFSResult, bfs_walk, resolve_anchor_ids
from src.tools._traversal_bounds import (
    BFS_ACTIVATION_THRESHOLD,
    BFS_FAN_OUT_LIMIT,
    FAN_OUT_THRESHOLD,
    _use_bfs,
    degraded_notice,
)
from tests.conftest import MockGraphDB, MockUnifiedDataAccess

pytestmark = pytest.mark.property

_SETTINGS = settings(max_examples=100, deadline=None)

#: Opaque object the tests thread through as ``tenant=`` so an assertion
#: can confirm the walker forwarded exactly what it was given.
_TENANT_SENTINEL = ("tenant", "props")

_TIMEOUT_S = 30.0


# ---------------------------------------------------------------------------
# Shared harness: a Cypher-evaluating graph double
# ---------------------------------------------------------------------------

#: The Label_Scope_Predicate shape emitted by
#: :func:`src.tenancy.resolver.tenant_label_predicate`: an inclusion form
#: (``... > 0``, non-default tenant) or an exclusion form (``... = 0``,
#: default ``gw`` tenant with other prefixed tenants in the catalog).
_SCOPE_RE = re.compile(
    r"size\(\s*\[\s*__lbl\s+IN\s+labels\(\s*(?P<var>[A-Za-z_]\w*)\s*\)"
    r"\s+WHERE\s+(?P<conds>.*?)\s*\]\s*\)\s*(?P<op>[>=])\s*0"
)

#: One ``__lbl STARTS WITH '<prefix>'`` term inside a scope predicate.
_PREFIX_RE = re.compile(r"__lbl\s+STARTS\s+WITH\s+'(?P<prefix>[^']*)'")

#: ``<var>.<property> = $<param>`` -- the Anchor_Predicate terms both the
#: UNION ALL branches and the legacy OR disjunction are built from.
_EQUALITY_RE = re.compile(
    r"(?P<var>[A-Za-z_]\w*)\.(?P<prop>[A-Za-z_]\w*)\s*=\s*\$(?P<param>\w+)"
)


@dataclass(frozen=True)
class GraphNode:
    """One node in an :class:`AnchorGraphDB`'s in-memory graph."""

    nid: str
    name: str | None
    path: str | None
    labels: tuple[str, ...] = ()


@dataclass
class AnchorGraphDB:
    """Graph double that evaluates anchor-resolution Cypher semantically.

    Understands exactly the clause vocabulary the anchor-resolution
    queries are built from -- ``MATCH (n)``, a ``WHERE`` of
    ``<var>.<prop> = $<param>`` terms combined with ``AND`` / ``OR``, an
    optional Label_Scope_Predicate, and ``RETURN id(n) AS nid`` -- and
    matches its ``nodes`` against that predicate. ``UNION ALL`` branches
    are evaluated independently and concatenated *without* deduplication,
    which is the behaviour that makes the dedup half of Property 1 real:
    a node matching on both ``name`` and ``path`` is returned twice here,
    so a caller that failed to fold ids through a set would show it
    twice.

    Every call is recorded in :pyattr:`call_log` (same 4-tuple shape as
    ``tests.conftest.MockGraphDB``) so a test can assert on the emitted
    text and on the ``tenant`` / ``timeout`` kwargs as well as the rows.
    """

    nodes: tuple[GraphNode, ...] = ()
    call_log: list[tuple[Any, ...]] = field(default_factory=list)

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        tenant: Any = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        self.call_log.append(
            (
                "query",
                (cypher,),
                dict(params or {}),
                {"tenant": tenant, "timeout": timeout},
            )
        )
        rows: list[dict[str, Any]] = []
        for branch in _split_union_all(cypher):
            for node in self.nodes:
                if _branch_matches(branch, node, params or {}):
                    rows.append({"nid": node.nid})
        return rows

    def cyphers(self) -> list[str]:
        """Every Cypher string this double has been handed, in order."""
        return [c[1][0] for c in self.call_log if c[0] == "query"]


def _split_union_all(cypher: str) -> list[str]:
    """Split ``cypher`` into its ``UNION ALL`` branches."""
    return re.split(r"\s+UNION\s+ALL\s+", cypher)


def _where_clause(branch: str) -> str:
    """Return the text between ``WHERE`` and ``RETURN`` in ``branch``."""
    match = re.search(
        r"\bWHERE\b(?P<where>.*?)(?:\bRETURN\b|$)",
        branch,
        flags=re.DOTALL,
    )
    return match.group("where") if match else ""


def _branch_matches(
    branch: str, node: GraphNode, params: dict[str, Any]
) -> bool:
    """True when ``node`` satisfies one ``UNION ALL`` branch's predicate.

    Evaluates the branch in two parts, because the two predicate families
    combine differently and a text-level scan cannot tell their ``OR``
    tokens apart: the Label_Scope_Predicate is lifted out first (it is
    always ``AND``-ed onto the anchor terms, and its own internal ``OR``
    list belongs to the exclusion form, not to the anchor disjunction),
    then the residual text is read as the anchor predicate.
    """
    where = _where_clause(branch)

    scopes = list(_SCOPE_RE.finditer(where))
    for scope in scopes:
        if not _scope_matches(scope, node):
            return False

    anchor_text = _SCOPE_RE.sub("", where)
    return _anchor_matches(anchor_text, node, params)


def _scope_matches(scope: re.Match[str], node: GraphNode) -> bool:
    """Evaluate one Label_Scope_Predicate against ``node``'s labels."""
    prefixes = [
        m.group("prefix")
        for m in _PREFIX_RE.finditer(scope.group("conds"))
    ]
    owns = any(
        label.startswith(prefix)
        for label in node.labels
        for prefix in prefixes
        if prefix
    )
    # ``> 0`` is the inclusion form (node must own a prefixed label);
    # ``= 0`` is the default tenant's exclusion form (node must own none).
    return owns if scope.group("op") == ">" else not owns


def _anchor_matches(
    anchor_text: str, node: GraphNode, params: dict[str, Any]
) -> bool:
    """Evaluate the residual anchor predicate against ``node``.

    ``AND``-ed terms must all hold; a residual carrying an ``OR`` token is
    a disjunction and needs only one. Both shapes reduce to the same
    reading because the queries under test never mix the two connectives
    within the anchor predicate itself.
    """
    terms = list(_EQUALITY_RE.finditer(anchor_text))
    if not terms:
        # No anchor predicate at all would match every node; the queries
        # under test always carry one, so treat its absence as a harness
        # mismatch rather than silently selecting the whole graph.
        raise AssertionError(
            f"no anchor equality term found in predicate: {anchor_text!r}"
        )

    results = [
        getattr(node, term.group("prop"), None)
        == params.get(term.group("param"))
        for term in terms
    ]
    disjunctive = re.search(r"\bOR\b", anchor_text) is not None
    return any(results) if disjunctive else all(results)


# ---------------------------------------------------------------------------
# Shared harness: edge-aware expansion evaluation
# ---------------------------------------------------------------------------

#: ``MATCH (<lhs>)-[<var>?:<types>(*1..<depth>)?]->(<rhs>)`` -- the one
#: pattern shape both sides of an expansion comparison are built from:
#: the walker's single-type single-hop query (no ``*``) and the
#: variable-length pattern it replaces (``*1..N``).
_PATTERN_RE = re.compile(
    r"MATCH\s+\((?P<lhs>[A-Za-z_]\w*)\)-\[\s*(?:[A-Za-z_]\w*)?\s*:\s*"
    r"(?P<types>[A-Za-z_][A-Za-z0-9_|]*)"
    r"(?:\*1\.\.(?P<depth>\d+))?\s*\]->\((?P<rhs>[A-Za-z_]\w*)\)"
)

#: ``id(<var>) IN $ids`` -- the frontier seek. Which pattern variable it
#: names is what distinguishes an outgoing expansion from an incoming one.
_FRONTIER_RE = re.compile(r"id\(\s*(?P<var>[A-Za-z_]\w*)\s*\)\s+IN\s+\$ids")

_LIMIT_RE = re.compile(r"\bLIMIT\s+(?P<n>\d+)")

#: ``LIMIT`` for the reference variable-length query -- high enough that
#: it never truncates a generated graph, so the reference stays the *full*
#: reachable set that the walker's result is compared against.
_REFERENCE_LIMIT = 10_000


@dataclass(frozen=True)
class GraphEdge:
    """One directed, typed edge between two :class:`GraphNode` ids."""

    src: str
    dst: str
    rel_type: str


@dataclass(frozen=True)
class _Expansion:
    """The parsed shape of one expansion query.

    ``depth`` is ``1`` for a single-hop pattern and ``N`` for a
    ``*1..N`` variable-length pattern, which is the only structural
    difference between the walker's queries and the pattern it replaces.
    """

    direction: str
    types: tuple[str, ...]
    depth: int
    limit: int


def _parse_expansion(cypher: str) -> _Expansion | None:
    """Parse ``cypher`` as an expansion query, or ``None`` if it is not.

    ``None`` means "not an expansion" -- :class:`EdgeGraphDB` then hands
    the query to :class:`AnchorGraphDB`, which is how anchor resolution
    keeps working unchanged on the edge-aware double.
    """
    pattern = _PATTERN_RE.search(cypher)
    frontier = _FRONTIER_RE.search(cypher)
    if pattern is None or frontier is None:
        return None

    var = frontier.group("var")
    lhs, rhs = pattern.group("lhs"), pattern.group("rhs")
    if var not in (lhs, rhs):
        # The frontier seek names a variable the pattern never binds, so
        # Neptune would reject the query. Surface it as a harness/impl
        # mismatch rather than silently evaluating something else.
        raise AssertionError(
            f"frontier variable {var!r} is not bound by pattern "
            f"({lhs!r}, {rhs!r}) in: {cypher!r}"
        )

    depth = pattern.group("depth")
    limit = _LIMIT_RE.search(cypher)
    return _Expansion(
        # (a)-[..]->(b) walks out of the frontier; (b)-[..]->(a) walks in.
        direction="forward" if var == lhs else "reverse",
        types=tuple(pattern.group("types").split("|")),
        depth=int(depth) if depth else 1,
        limit=int(limit.group("n")) if limit else _REFERENCE_LIMIT,
    )


def _walk_endpoints(
    starts: Sequence[str],
    adjacency: dict[str, list[str]],
    depth: int,
) -> list[str]:
    """Endpoints of every walk of length ``1..depth`` from ``starts``.

    Deliberately keeps no visited-set: this is the ``*1..N``
    variable-length semantics (every path within the bound, including
    paths through an already-seen node), which is what makes it an
    *independent* reference for the walker rather than a second copy of
    the walker's own visited-set BFS. Emitted shortest-walk-first, so a
    ``LIMIT`` truncates the far end of the neighborhood the way a
    depth-ordered plan would.
    """
    endpoints: list[str] = []
    frontier = list(starts)
    for _ in range(max(0, depth)):
        nxt: list[str] = []
        for nid in frontier:
            for dst in adjacency.get(nid, ()):
                endpoints.append(dst)
                nxt.append(dst)
        if not nxt:
            break
        frontier = nxt
    return endpoints


def _scoped_reach(
    adjacency: dict[str, list[str]],
    anchor: str,
    max_depth: int,
    allowed: frozenset[str] | None,
) -> set[str]:
    """Nodes within ``max_depth`` of ``anchor``, optionally scope-gated.

    The visited-set counterpart of :func:`_walk_endpoints`, and the
    reference Property 6 compares against. ``allowed`` is the set of ids
    a Label_Scope_Predicate admits; a node outside it is not collected
    *and not expanded through*, which is what the emitted predicate does
    at the graph level -- a rejected neighbor never enters the frontier,
    so its own neighbors become unreachable too. Passing ``None`` gates
    nothing and yields the plain reachable set.

    Kept separate from :func:`_walk_endpoints` rather than parameterized
    onto it because the two model different query shapes: the walk
    enumeration there is the ``*1..N`` pattern's path semantics (no
    visited-set), while this is reachability, which is what a per-hop
    scope filter operates on.
    """
    visited = {anchor}
    frontier = [anchor]
    found: set[str] = set()
    for _ in range(max(0, max_depth)):
        nxt: list[str] = []
        for nid in frontier:
            for dst in adjacency.get(nid, ()):
                if dst in visited:
                    continue
                if allowed is not None and dst not in allowed:
                    continue
                visited.add(dst)
                found.add(dst)
                nxt.append(dst)
        if not nxt:
            break
        frontier = nxt
    return found


@dataclass
class EdgeGraphDB(AnchorGraphDB):
    """:class:`AnchorGraphDB` plus semantic evaluation of expansions.

    Adds an edge set and the ability to *evaluate* the two expansion
    shapes an expansion comparison needs -- the walker's per-type
    single-hop query (:func:`~src.tools._bfs_walker._expand_one_hop`) and
    the variable-length pattern it replaces -- against the same in-memory
    graph. Both go through one evaluator, so neither side gets a
    different reading of the same graph; the only difference between them
    is the query text each emits (``depth``, ``types``, ``LIMIT``).

    Anchor-resolution queries are not expansions, so they fall through to
    :class:`AnchorGraphDB` unchanged and Property 1's harness keeps
    working here.
    """

    edges: tuple[GraphEdge, ...] = ()

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        tenant: Any = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        spec = _parse_expansion(cypher)
        if spec is None:
            return await super().query(
                cypher, params, tenant, timeout=timeout
            )
        self.call_log.append(
            (
                "query",
                (cypher,),
                dict(params or {}),
                {"tenant": tenant, "timeout": timeout},
            )
        )
        return self._expansion_rows(spec, cypher, params or {})

    def adjacency(self, spec: _Expansion) -> dict[str, list[str]]:
        """Adjacency over ``spec``'s edge types, in ``spec``'s direction.

        ``reverse`` flips each edge, so a walk from the frontier follows
        incoming edges -- the ``MATCH (b)-[:T]->(a)`` shape.
        """
        adj: dict[str, list[str]] = {}
        for edge in self.edges:
            if edge.rel_type not in spec.types:
                continue
            if spec.direction == "reverse":
                src, dst = edge.dst, edge.src
            else:
                src, dst = edge.src, edge.dst
            adj.setdefault(src, []).append(dst)
        return adj

    def _expansion_rows(
        self,
        spec: _Expansion,
        cypher: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Rows for one expansion: reach, scope-filter, DISTINCT, LIMIT.

        Clause order matches the emitted query: the
        Label_Scope_Predicate is a ``WHERE`` term, so it filters
        endpoints *before* the ``LIMIT`` truncates them.
        """
        starts = [
            str(nid)
            for nid in params.get("ids") or ()
            if nid is not None and nid != ""
        ]
        by_id = {node.nid: node for node in self.nodes}
        scopes = list(_SCOPE_RE.finditer(_where_clause(cypher)))

        rows: list[dict[str, Any]] = []
        emitted: set[str] = set()
        for nid in _walk_endpoints(starts, self.adjacency(spec), spec.depth):
            if nid in emitted:
                continue  # RETURN DISTINCT
            node = by_id.get(nid)
            if node is None:
                continue
            if any(not _scope_matches(scope, node) for scope in scopes):
                continue
            emitted.add(nid)
            rows.append(
                {
                    "nid": nid,
                    "name": node.name,
                    "path": node.path,
                    "labels": list(node.labels),
                }
            )
            if len(rows) >= spec.limit:
                break
        return rows


async def _resolve_via_or(
    graph_db: AnchorGraphDB,
    name: str,
    *,
    scope_pred: str,
    tenant: Any,
    timeout_s: float,
) -> list[str]:
    """Resolve anchor ids with the pre-optimization OR Anchor_Predicate.

    The reference implementation Property 1 compares against: the
    index-defeating disjunction that
    :func:`~src.tools._bfs_walker.resolve_anchor_ids` replaced (Root
    Cause B). Parenthesized so the scope predicate's ``AND`` cannot bind
    tighter than the disjunction, matching the original queries.
    """
    cypher = (
        "MATCH (n) WHERE (n.name = $name OR n.path = $name)"
        f"{scope_pred} "
        "RETURN id(n) AS nid"
    )
    rows = await graph_db.query(
        cypher, {"name": name}, tenant=tenant, timeout=timeout_s
    )
    return [str(row["nid"]) for row in rows or []]


async def _expand_via_variable_length(
    graph_db: EdgeGraphDB,
    name: str,
    *,
    direction: str,
    edge_types: Sequence[str],
    max_depth: int,
    scope_pred: str,
    tenant: Any,
    timeout_s: float,
) -> list[str]:
    """Reach nodes with the Multi_Type_Expansion the walker replaced.

    The reference implementation Property 2 compares against: one
    variable-length pattern spanning the whole edge set
    (``[:A|B|C*1..N]``), which is the query shape
    :func:`~src.tools._bfs_walker.bfs_walk` decomposes into per-type
    single-hop seeks. It is deliberately *unbounded* where the walker is
    bounded -- no Fan_Out_Limit, no global result cap, no per-hop cut-off
    -- so its result is the full set of nodes the original pattern could
    reach and the subset relation is a real constraint rather than a
    comparison of two equally-truncated views.

    The anchor is resolved with the pre-optimization ``OR`` predicate
    (:func:`_resolve_via_or`), so the reference path shares no code with
    the implementation under test.

    Scope is applied to the terminal node only, which is what a
    variable-length pattern's ``WHERE`` on ``b`` does: intermediate nodes
    are unconstrained. The walker filters *every* hop's target, so it can
    only ever reach fewer nodes -- exactly the direction R2.7 allows.
    """
    anchor_ids = await _resolve_via_or(
        graph_db,
        name,
        scope_pred=scope_pred,
        tenant=tenant,
        timeout_s=timeout_s,
    )
    if not anchor_ids:
        return []

    types = "|".join(edge_types)
    hops = f"*1..{max_depth}"
    if direction == "reverse":
        pattern = f"MATCH (b)-[r:{types}{hops}]->(a)"
    else:
        pattern = f"MATCH (a)-[r:{types}{hops}]->(b)"

    cypher = (
        pattern
        + " WHERE id(a) IN $ids"
        + scope_pred.replace("labels(n)", "labels(b)")
        + " RETURN DISTINCT id(b) AS nid, b.name AS name,"
        " b.path AS path, labels(b) AS labels"
        f" LIMIT {_REFERENCE_LIMIT}"
    )
    rows = await graph_db.query(
        cypher, {"ids": anchor_ids}, tenant=tenant, timeout=timeout_s
    )
    return [str(row["nid"]) for row in rows or []]


# ---------------------------------------------------------------------------
# Shared harness: timeout injection
# ---------------------------------------------------------------------------

#: The two exception shapes the implementation's ``_is_timeout_error``
#: helpers recognise as a Statement_Timeout: the ``NeptuneAdapterError``
#: :pymeth:`NeptuneAdapter.query` raises when its own
#: :func:`asyncio.wait_for` expires, and a bare
#: :pyexc:`asyncio.TimeoutError`. Both are drawn because they travel
#: different arms of that helper -- one is recognised by its *type*, the
#: other only by the ``statement timeout`` substring in its *message* --
#: so a shape-specific regression would otherwise hide behind the other.
_TIMEOUT_SHAPES = ("neptune", "asyncio")


def _timeout_error(shape: str) -> BaseException:
    """Build a Statement_Timeout exception of ``shape``.

    The Neptune shape reproduces the adapter's real message
    (``NeptuneAdapter.query`` formats ``query exceeded <N>s statement
    timeout``) rather than an arbitrary string, because that wording --
    not the exception class -- is what ``_is_timeout_error`` keys on. A
    paraphrase here would be classified as a generic failure and would
    take a different, quieter branch than the one production hits.
    """
    if shape == "asyncio":
        return asyncio.TimeoutError()
    return NeptuneAdapterError("query exceeded 30.0s statement timeout")


@dataclass(frozen=True)
class _TimeoutPlan:
    """Which of a walk's queries time out, and with which shape.

    Three independent selectors, OR-ed together, so "at random points"
    covers the three ways a real timeout distributes across a walk:

    ``indices``
        Absolute 0-based call ordinals. The positional case -- "the third
        query the walker happens to issue" -- which is the only one that
        can land mid-hop, failing one relationship type's expansion while
        its siblings in the same :func:`asyncio.gather` succeed.
    ``kinds``
        ``"anchor"`` (the UNION_ALL_Decomposition resolution) or
        ``"expansion"`` (any per-type single hop). The structural case:
        it distinguishes losing the anchor -- which ends the walk before
        it starts -- from losing hops, which yields a partial result.
    ``edge_types``
        Fails every expansion over a given relationship type, wherever it
        occurs. The case a slow edge type produces in practice: one
        branch of the walk is dark at every depth while the others
        traverse normally.

    An all-empty plan injects nothing; it is a legitimate draw (the
    control), which is why Property 7 also runs pinned plans that
    definitely fire -- see the test's anti-vacuity block.
    """

    indices: frozenset[int] = frozenset()
    kinds: frozenset[str] = frozenset()
    edge_types: frozenset[str] = frozenset()
    shape: str = "neptune"

    def fires(self, index: int, spec: _Expansion | None) -> bool:
        """True when the call at ``index`` parsing as ``spec`` should fail.

        ``spec is None`` marks a non-expansion query, which for
        :func:`~src.tools._bfs_walker.bfs_walk` is the anchor resolution
        (the only other query it issues).
        """
        if index in self.indices:
            return True
        if ("anchor" if spec is None else "expansion") in self.kinds:
            return True
        return spec is not None and bool(
            set(spec.types) & self.edge_types
        )

    def error(self) -> BaseException:
        """The exception this plan raises."""
        return _timeout_error(self.shape)


#: The no-op plan: injects nothing. Used as :class:`TimeoutInjectingGraphDB`'s
#: default and as Property 7's clean control run.
_NO_TIMEOUTS = _TimeoutPlan()


@dataclass
class TimeoutInjectingGraphDB(EdgeGraphDB):
    """:class:`EdgeGraphDB` that times out on a plan-selected subset.

    Timeouts are raised *instead of* answering, and the refused call is
    still appended to :pyattr:`~AnchorGraphDB.call_log` before the raise,
    so call ordinals stay dense: the ``index`` a plan selects on is the
    same number whether or not earlier calls succeeded, and the walker's
    ``queries_issued`` counter can be compared against the log length
    without correcting for failures.

    :pyattr:`injected` records what actually fired. Property 7's
    assertions are derived from it rather than predicted from the plan,
    because a plan can select calls a walk never makes -- an index past
    the walk's query count, or an edge type absent from the graph -- and
    a predicted expectation would then assert against a timeout that
    never happened.
    """

    plan: _TimeoutPlan = _NO_TIMEOUTS
    injected: list[tuple[int, str]] = field(default_factory=list)

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        tenant: Any = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        index = len(self.call_log)
        spec = _parse_expansion(cypher)
        if self.plan.fires(index, spec):
            self.injected.append(
                (index, "anchor" if spec is None else "expansion")
            )
            self.call_log.append(
                (
                    "query",
                    (cypher,),
                    dict(params or {}),
                    {"tenant": tenant, "timeout": timeout},
                )
            )
            raise self.plan.error()
        return await super().query(
            cypher, params, tenant, timeout=timeout
        )


# ---------------------------------------------------------------------------
# Shared harness: per-expansion row accounting
# ---------------------------------------------------------------------------


@dataclass
class RowCountingGraphDB(EdgeGraphDB):
    """:class:`EdgeGraphDB` that records each expansion's row count.

    The observable Property 8 needs and that no other property does: how
    many rows *the graph handed back* for one expansion, as opposed to how
    many the walker kept. The two differ -- the visited-set drops a
    neighbor that an earlier hop already reported -- so counting the
    walker's own output would only ever be a lower bound on the rows the
    ``LIMIT`` had to bound, and a walker that emitted no ``LIMIT`` at all
    could still look compliant on a graph whose extra neighbors happen to
    be duplicates.

    Recording happens *after* :class:`EdgeGraphDB` has evaluated the
    query, so the count is the post-``DISTINCT``, post-``LIMIT`` row set
    the walker actually received -- and the ``LIMIT`` applied is the one
    parsed out of the emitted text, not one the harness chose. An
    expansion emitted without a ``LIMIT`` therefore returns the whole
    neighborhood (``_parse_expansion`` falls back to
    :data:`_REFERENCE_LIMIT`), which is what gives the row-level
    assertion its bite rather than making it a tautology about the
    double.
    """

    returned: list[tuple[_Expansion, int]] = field(default_factory=list)

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        tenant: Any = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        rows = await super().query(cypher, params, tenant, timeout=timeout)
        spec = _parse_expansion(cypher)
        if spec is not None:
            self.returned.append((spec, len(rows)))
        return rows

    def expansions(self) -> list[str]:
        """Every expansion Cypher this double answered, in order.

        Excludes the anchor resolution, which carries no Fan_Out_Limit
        (it is bounded by the anchor's own equality predicates, not by a
        ``LIMIT``) and would fail the R2.3 assertions if swept in.
        """
        return [c for c in self.cyphers() if _parse_expansion(c) is not None]


# ---------------------------------------------------------------------------
# Shared harness: the tool-level fallback chain
# ---------------------------------------------------------------------------

#: The six query kinds ``trace_execution_path`` issues on the path
#: Property 7 drives (``include_callers`` / ``include_weights`` off), keyed
#: to a fragment unique to each. The first four are the fallback chain
#: itself -- pre-flight probes, the single-query pattern, then the walk it
#: is retried as -- and ``onehop`` is the Degraded_Result the chain ends on.
#:
#: Kind-level (rather than ordinal-level) injection is deliberate here:
#: unlike the walker, whose outcome the test reads back off the call log,
#: the tool's outcome is *predicted* from which stage failed, and a stage
#: is exactly one kind.
#: ``degree_anchor`` is the degree probe's own UNION_ALL_Decomposition
#: (task 2.6): the probe resolves its Anchor_Node's ids before counting
#: edges by ``id(a) IN $ids``, so it is two queries, not one. It is a
#: separate kind because it is separately failable -- and it is
#: distinguishable from ``walk_anchor`` only because the probe resolves on
#: its own ``a`` variable (``RETURN id(a) AS nid``) while the walker
#: resolves on ``n``. A shared projection would make the two stages
#: indistinguishable to this harness and silently mis-attribute either
#: one's timeout to the other.
_TOOL_KIND_FRAGMENTS: dict[str, str] = {
    "entity": "RETURN labels(n) AS labels LIMIT 1",
    "degree_anchor": "RETURN id(a) AS nid",
    "degree": "count(r) AS deg",
    "chain": "CALLS*1..",
    "walk_anchor": "RETURN id(n) AS nid",
    "walk_hop": "RETURN DISTINCT id(b) AS nid",
    "onehop": "coalesce(x.filepath, x.path) AS file",
}

_TOOL_KINDS = tuple(_TOOL_KIND_FRAGMENTS)


def _tool_kind(cypher: str) -> str | None:
    """Classify ``cypher`` as one of :data:`_TOOL_KIND_FRAGMENTS`' kinds.

    ``None`` means the tool issued a query this harness does not model.
    The double records those rather than raising, because the tool wraps
    its body in a broad ``except Exception`` that would convert a raise
    here into a rendered ``[ERROR]`` -- i.e. would silently absorb the
    harness's own bug report. Property 7 asserts the list is empty
    instead.
    """
    for kind, fragment in _TOOL_KIND_FRAGMENTS.items():
        if fragment in cypher:
            return kind
    return None


@dataclass
class ToolTimeoutGraphDB(MockGraphDB):
    """``MockGraphDB`` that times out whole stages of the tool chain.

    Extends the fragment-matching double the unit suite already uses (so
    each stage's canned rows are seeded exactly as
    ``test_code_analysis_tools`` seeds them) with a
    :pyattr:`fail_kinds` set naming the stages that raise a
    Statement_Timeout instead of answering.

    :pyattr:`issued` records every stage the tool reached, in order,
    which is how the test can assert on stages that were *not* reached
    (a hub-gated call never issues the single-query pattern).
    """

    fail_kinds: frozenset[str] = frozenset()
    shape: str = "neptune"
    issued: list[str] = field(default_factory=list)
    injected: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        tenant: Any = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        kind = _tool_kind(cypher)
        if kind is None:
            self.unclassified.append(cypher)
        else:
            self.issued.append(kind)
        if kind is not None and kind in self.fail_kinds:
            self.injected.append(kind)
            self.call_log.append(
                (
                    "query",
                    (cypher,),
                    dict(params or {}),
                    {"tenant": tenant, "timeout": timeout},
                )
            )
            raise _timeout_error(self.shape)
        return await super().query(
            cypher, params, tenant, timeout=timeout
        )


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

#: Tenant label prefixes, matching the catalog's shape
#: (``^([A-Z][A-Z0-9_]*_)?$``). Kept to a two-element pool so a generated
#: graph reliably mixes in-scope and out-of-scope nodes.
_LABEL_PREFIXES = ("GW_V17_", "GW_SFS_")

#: Anchor values. A tiny pool is deliberate: it makes name/path collisions
#: across nodes -- and nodes matching on *both* properties, the dedup case
#: -- common instead of astronomically unlikely.
_ANCHOR_VALUES = ("alpha", "beta", "gamma", "ush/alpha.sh")


def _labels() -> st.SearchStrategy[tuple[str, ...]]:
    """Label tuples spanning unprefixed and tenant-prefixed nodes."""
    base = st.sampled_from(("File", "ShellScript", "FortranSubroutine"))
    prefix = st.sampled_from(("",) + _LABEL_PREFIXES)
    return st.lists(
        st.tuples(prefix, base).map(lambda pb: pb[0] + pb[1]),
        min_size=0,
        max_size=2,
    ).map(tuple)


def graph_nodes(min_count: int = 0) -> (
    st.SearchStrategy[tuple[GraphNode, ...]]
):
    """Node sets whose ``name`` / ``path`` draw from :data:`_ANCHOR_VALUES`.

    Values are drawn from the shared anchor pool (and ``None``), so a
    generated graph routinely contains a node matched only by ``name``,
    one matched only by ``path``, one matched by both (the ``UNION ALL``
    duplicate), and one matched by neither.

    ``min_count`` raises the floor on the node count for callers whose
    graph shape needs a minimum -- :func:`cyclic_graphs` cannot lay a
    two-node ring on a one-node graph. It defaults to ``0`` so the
    properties that draw the full range are unaffected; expressing it as
    a floor on the ``count`` draw rather than as a ``.filter`` keeps
    Hypothesis from discarding a third of its examples and keeps the
    shrinker able to reduce the graph.
    """
    anchor_value = st.one_of(st.none(), st.sampled_from(_ANCHOR_VALUES))
    floor = max(0, min_count)

    @st.composite
    def _gen(draw: Any) -> tuple[GraphNode, ...]:
        count = draw(st.integers(min_value=floor, max_value=max(floor, 6)))
        nodes: list[GraphNode] = []
        for i in range(count):
            name = draw(anchor_value)
            # Bias a share of nodes toward name == path so the dedup half
            # of Property 1 is exercised on most examples rather than only
            # when two independent draws happen to coincide.
            if name is not None and draw(st.booleans()):
                path = name
            else:
                path = draw(anchor_value)
            nodes.append(
                GraphNode(
                    nid=f"n{i}",
                    name=name,
                    path=path,
                    labels=draw(_labels()),
                )
            )
        return tuple(nodes)

    return _gen()


#: Relationship types the generated graphs use. Three is enough to make a
#: walk issue several queries per hop and to let a drawn edge set be a
#: strict subset of the types actually present in the graph.
_EDGE_TYPES = ("CALLS", "USES", "SOURCES")


def edge_type_sets() -> st.SearchStrategy[list[str]]:
    """Non-empty, deduplicated subsets of :data:`_EDGE_TYPES`."""
    return st.lists(
        st.sampled_from(_EDGE_TYPES),
        min_size=1,
        max_size=len(_EDGE_TYPES),
        unique=True,
    )


def dag_graphs() -> (
    st.SearchStrategy[tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]]
):
    """Random DAGs: a :func:`graph_nodes` node set plus a typed edge set.

    Edges run strictly from a lower-indexed node to a higher-indexed one,
    which makes every generated graph acyclic by construction. That is
    what lets the unbounded walk enumeration in :func:`_walk_endpoints`
    stand in for a ``*1..N`` pattern without a termination guard, and it
    keeps Property 2 about the *bounds* (Fan_Out_Limit, result cap, hop
    scoping) rather than about cycle handling -- cycles are Property 3's
    subject (task 10.3), which reuses this harness with a cyclic
    generator.

    The adjacency draw depends on the drawn node set, so it is expressed
    as a composite ``draw`` rather than an ``st.data()`` interaction:
    same dependent-draw effect, and Hypothesis can shrink the graph.
    """

    @st.composite
    def _gen(draw: Any) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]:
        nodes = draw(graph_nodes())
        rel = st.sampled_from((None,) + _EDGE_TYPES)
        edges: list[GraphEdge] = []
        for i, src in enumerate(nodes):
            for dst in nodes[i + 1:]:
                rel_type = draw(rel)
                if rel_type is not None:
                    edges.append(GraphEdge(src.nid, dst.nid, rel_type))
        return nodes, tuple(edges)

    return _gen()


def anchored_dag_graphs() -> (
    st.SearchStrategy[
        tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...], str]
    ]
):
    """A :func:`dag_graphs` graph plus an anchor name to start from.

    The anchor is drawn *after* the graph and biased toward a ``name`` /
    ``path`` value the graph actually carries, because an anchor that
    matches no node resolves to no ids and yields an empty walk on both
    sides of the comparison -- true, but it exercises nothing. Drawing
    blind from :data:`_ANCHOR_VALUES` leaves the majority of examples in
    that shape; biasing raises the share that reach a real expansion
    while still drawing the unmatched case often enough to keep it
    covered.
    """

    @st.composite
    def _gen(
        draw: Any,
    ) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...], str]:
        nodes, edges = draw(dag_graphs())
        present = sorted(
            {
                value
                for node in nodes
                for value in (node.name, node.path)
                if value
            }
        )
        blind = st.sampled_from(_ANCHOR_VALUES)
        if not present:
            return nodes, edges, draw(blind)
        return nodes, edges, draw(
            st.one_of(st.sampled_from(present), blind)
        )

    return _gen()


def cyclic_graphs() -> (
    st.SearchStrategy[tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]]
):
    """Random graphs that always contain at least one directed cycle.

    The counterpart to :func:`dag_graphs` for Property 3. A cycle is laid
    down *by construction* -- a ring of one drawn relationship type over
    the first ``ring_len`` nodes -- rather than left to chance among
    random edges, because "the graph happened to be acyclic" is the one
    example shape that makes a cycle-termination property vacuous, and it
    is the majority shape when edges are drawn independently. Random
    chords are then drawn over the whole node set, so a graph also
    carries shortcut edges, back edges, second cycles of other types,
    and self-loops (``src == dst`` is drawn like any other pair -- the
    tightest cycle there is, and the one a visited-set bug hits first).

    ``ring_len`` may be smaller than the node count, which leaves nodes
    off the ring that are reachable only by chord -- so the generated
    population keeps the dead-end branches a ring over every node would
    eliminate.

    Direction matters here in a way it does not for a DAG: the ring is
    cyclic when traversed either way, so a ``reverse`` walk meets the
    same cycle a ``forward`` walk does.

    Node count starts at 2 (:func:`graph_nodes` floor) so a ring always
    has somewhere to go. Graphs stay small -- at most 6 nodes -- because
    the reference reachability this property compares against enumerates
    walks without a visited-set (:func:`_walk_endpoints`), which on a
    cyclic graph is bounded only by the depth budget.
    """

    @st.composite
    def _gen(draw: Any) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]:
        nodes = draw(graph_nodes(min_count=2))
        ring_len = draw(st.integers(min_value=2, max_value=len(nodes)))
        ring_type = draw(st.sampled_from(_EDGE_TYPES))

        edges: list[GraphEdge] = []
        seen: set[GraphEdge] = set()

        def _add(edge: GraphEdge) -> None:
            if edge in seen:
                return
            seen.add(edge)
            edges.append(edge)

        for i in range(ring_len):
            src = nodes[i].nid
            dst = nodes[(i + 1) % ring_len].nid
            _add(GraphEdge(src, dst, ring_type))

        rel = st.sampled_from((None,) + _EDGE_TYPES)
        for src_node in nodes:
            for dst_node in nodes:
                rel_type = draw(rel)
                if rel_type is not None:
                    _add(GraphEdge(src_node.nid, dst_node.nid, rel_type))

        return nodes, tuple(edges)

    return _gen()


def anchored_cyclic_graphs() -> (
    st.SearchStrategy[
        tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...], str]
    ]
):
    """A :func:`cyclic_graphs` graph plus an anchor name to start from.

    Same anchor bias as :func:`anchored_dag_graphs`, and for the same
    reason: an anchor matching no node resolves to no ids, so the walk
    never enters its hop loop and terminates for a reason that has
    nothing to do with the visited-set.
    """

    @st.composite
    def _gen(
        draw: Any,
    ) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...], str]:
        nodes, edges = draw(cyclic_graphs())
        present = sorted(
            {
                value
                for node in nodes
                for value in (node.name, node.path)
                if value
            }
        )
        blind = st.sampled_from(_ANCHOR_VALUES)
        if not present:
            return nodes, edges, draw(blind)
        return nodes, edges, draw(
            st.one_of(st.sampled_from(present), blind)
        )

    return _gen()


def _inclusion_scope(prefix: str) -> str:
    """A non-default tenant's `` AND <predicate>`` inclusion fragment.

    What ``_scope_and("n")`` yields for a tenant declaring ``prefix``:
    the node must own at least one label carrying it.
    """
    return (
        " AND size([__lbl IN labels(n) "
        f"WHERE __lbl STARTS WITH '{prefix}']) > 0"
    )


def _exclusion_scope() -> str:
    """The default ``gw`` tenant's `` AND <predicate>`` fragment.

    The complement of :func:`_inclusion_scope` over every other catalog
    prefix: the node must own *no* prefixed label, i.e. it is a baseline
    node. Admits every unprefixed node, which is why a generator can use
    it as a no-op scoping (see :func:`uniform_scopes`).
    """
    conds = " OR ".join(
        f"__lbl STARTS WITH '{p}'" for p in _LABEL_PREFIXES
    )
    return f" AND size([__lbl IN labels(n) WHERE {conds}]) = 0"


def scope_preds() -> st.SearchStrategy[str]:
    """`` AND <Label_Scope_Predicate>`` fragments, plus the empty case.

    Mirrors what ``_scope_and("n")`` yields in each situation: no scoping
    at all, a non-default tenant's inclusion form, and the default
    tenant's exclusion form over the other catalog prefixes.
    """
    inclusion = st.sampled_from(_LABEL_PREFIXES).map(_inclusion_scope)
    return st.one_of(
        st.just(""), inclusion, st.just(_exclusion_scope())
    )


def uniform_scopes() -> st.SearchStrategy[tuple[str, str]]:
    """``(scope_pred, label)`` pairs where the predicate admits ``label``.

    Covers the same three Label_Scope_Predicate shapes as
    :func:`scope_preds` -- none, a tenant's inclusion form, the default
    tenant's exclusion form -- but pairs each with a node label the
    predicate *accepts*, so scoping is exercised without changing which
    nodes a walk can reach.

    That pairing is what lets :func:`dead_end_graphs` know its own
    reachable depth by construction. Drawing the scope independently of
    the labels (as Properties 1-3 do) means an example's scope predicate
    may filter out an arbitrary subset of the graph, which is fine for a
    subset or termination claim but would leave the depth at which the
    frontier empties unknown -- and that depth is exactly what Property 4
    asserts.
    """
    pairs = [("", "File"), (_exclusion_scope(), "File")]
    pairs += [(_inclusion_scope(p), p + "File") for p in _LABEL_PREFIXES]
    return st.sampled_from(pairs)


#: Anchor value for :func:`dead_end_graphs`. Deliberately outside
#: :data:`_ANCHOR_VALUES` and not reused as any other node's ``name`` or
#: ``path``, so the anchor resolves to exactly the layer-0 node and the
#: constructed depth of every other node is the depth the walk must find
#: it at.
_DEAD_END_ANCHOR = "dead-end-anchor"


@dataclass(frozen=True)
class _DeadEndGraph:
    """A layered graph whose reachable depth is known by construction.

    Attributes
    ----------
    nodes, edges
        The graph, in :class:`EdgeGraphDB`'s vocabulary.
    depths
        ``nid`` -> distance from the anchor, in ``direction``. Every
        non-anchor node sits at exactly one distance (edges only ever
        join consecutive layers), so this doubles as the expected
        ``hop`` for each discovered node.
    anchor
        The name to start the walk from; resolves to the layer-0 node.
    reach_depth
        The greatest ``depths`` value: the deepest layer, whose nodes all
        have zero outgoing edges.
    edge_types, direction, max_depth, fan_out_limit, result_limit
        Walk parameters. ``max_depth`` is strictly greater than
        ``reach_depth``; the two limits are strictly greater than the
        whole node count, so neither can truncate the walk and the only
        thing that can end it is an empty frontier.
    scope_pred
        A Label_Scope_Predicate that admits every node in ``nodes``.
    """

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    depths: dict[str, int]
    anchor: str
    reach_depth: int
    edge_types: tuple[str, ...]
    direction: str
    max_depth: int
    fan_out_limit: int
    result_limit: int
    scope_pred: str


def dead_end_graphs() -> st.SearchStrategy[_DeadEndGraph]:
    """Graphs whose reachable neighborhood is shallower than ``max_depth``.

    The generator for Property 4. Where :func:`dag_graphs` draws edges
    independently and so has an unknown diameter, this lays down a
    *layered* DAG: one anchor at layer 0, then ``reach_depth`` layers
    joined only to their immediate neighbor, and nothing leaving the last
    layer. The reachable depth is therefore ``reach_depth`` exactly, and
    ``max_depth`` is drawn strictly above it -- so a walker that does not
    stop when its frontier empties has depth budget left to spend and its
    extra hops are visible as extra queries.

    **Dead-end branches** are the point, not just the last layer. Leaf
    nodes are hung off *interior* layers, giving nodes with no outgoing
    edges at a depth where the walk must nonetheless keep going: the
    frontier at that hop mixes exhausted leaves with layer nodes that
    still expand. A walker that terminated on the first branch to run out
    (rather than on an empty frontier) would stop short here, which a
    graph consisting only of a uniform chain cannot detect.

    ``direction`` is drawn and the construction flips with it, so a
    ``reverse`` walk gets a chain oriented *into* the anchor and reaches
    the same known depth. Building the chain one way and relying on the
    drawn direction would leave every reverse example with a reachable
    depth of zero -- terminating at hop 1 for want of any edge at all,
    which is the vacuous shape of this property.

    Sizes stay small (at most 3 layers, 2 nodes per layer, 2 leaves)
    because the assertions are per-hop exact rather than statistical; a
    bigger graph adds no additional shape.
    """

    @st.composite
    def _gen(draw: Any) -> _DeadEndGraph:
        edge_types = tuple(draw(edge_type_sets()))
        rel = st.sampled_from(edge_types)
        direction = draw(st.sampled_from(("forward", "reverse")))
        reach_depth = draw(st.integers(min_value=1, max_value=3))
        slack = draw(st.integers(min_value=1, max_value=3))
        scope_pred, label = draw(uniform_scopes())

        def _link(near: str, far: str, rel_type: str) -> GraphEdge:
            """An edge the walk traverses from ``near`` to ``far``.

            A ``reverse`` walk follows incoming edges
            (``MATCH (b)-[:T]->(a)``), so the stored edge is flipped and
            the walk still moves away from the anchor.
            """
            if direction == "reverse":
                return GraphEdge(far, near, rel_type)
            return GraphEdge(near, far, rel_type)

        nodes = [
            GraphNode(
                nid="n0",
                name=_DEAD_END_ANCHOR,
                path=None,
                labels=(label,),
            )
        ]
        depths: dict[str, int] = {"n0": 0}
        layers: list[list[str]] = [["n0"]]
        edges: list[GraphEdge] = []
        counter = 1

        def _new_node(depth: int) -> str:
            nonlocal counter
            nid = f"n{counter}"
            counter += 1
            nodes.append(
                GraphNode(
                    nid=nid,
                    name=nid,
                    path=f"ush/{nid}.sh",
                    labels=(label,),
                )
            )
            depths[nid] = depth
            return nid

        for depth in range(1, reach_depth + 1):
            width = draw(st.integers(min_value=1, max_value=2))
            layer = [_new_node(depth) for _ in range(width)]
            for near in layers[-1]:
                for far in layer:
                    edges.append(_link(near, far, draw(rel)))
            layers.append(layer)

        # Dead ends at an interior depth: a leaf hung off layer ``at``
        # sits at ``at + 1 <= reach_depth``, so it never deepens the
        # graph -- it just puts an exhausted node in a frontier that
        # still has somewhere to go.
        for _ in range(draw(st.integers(min_value=0, max_value=2))):
            at = draw(
                st.integers(min_value=0, max_value=reach_depth - 1)
            )
            parent = draw(st.sampled_from(layers[at]))
            edges.append(_link(parent, _new_node(at + 1), draw(rel)))

        total = len(nodes)
        return _DeadEndGraph(
            nodes=tuple(nodes),
            edges=tuple(edges),
            depths=depths,
            anchor=_DEAD_END_ANCHOR,
            reach_depth=reach_depth,
            edge_types=edge_types,
            direction=direction,
            max_depth=reach_depth + slack,
            # Strictly above the node count, so no hop can hit the
            # Fan_Out_Limit and no walk can hit the global cap: the
            # frontier is then the only thing that can end the walk.
            fan_out_limit=total + draw(st.integers(1, 3)),
            result_limit=total + draw(st.integers(1, 3)),
            scope_pred=scope_pred,
        )

    return _gen()


#: The depth above which the selector switches to the BFS_Walker
#: regardless of degree (R3.1, R3.2). Unlike
#: :data:`~src.tools._traversal_bounds.BFS_ACTIVATION_THRESHOLD` this is a
#: literal in ``_use_bfs`` with no env override, so the test states it
#: rather than importing it.
_SHALLOW_DEPTH = 3

#: Degrees and depths far outside any plausible operational value, drawn
#: explicitly so "full int range" is exercised on every run instead of
#: whenever ``st.integers()`` happens to reach for a large value. Python
#: ints are arbitrary-precision, so ``2 ** 128`` is a legitimate argument
#: the selector must still classify; negatives cover a degree probe or
#: depth clamp that returned nonsense.
_INT_EXTREMES = (
    -(2 ** 128),
    -(2 ** 63),
    -(2 ** 31),
    -1,
    0,
    2 ** 31,
    2 ** 63,
    2 ** 128,
)


def selector_degrees() -> st.SearchStrategy[int | None]:
    """Node_Degree values for the strategy selector, plus ``None``.

    Three pools, unioned. Unbounded :func:`~hypothesis.strategies.integers`
    is the "full int range" the task asks for; a narrow band around
    :data:`~src.tools._traversal_bounds.BFS_ACTIVATION_THRESHOLD` makes the
    boundary examples (threshold minus one, threshold exactly) common
    rather than needle-in-a-haystack, since an off-by-one in the ``>=``
    comparison is the defect this property is most likely to catch; and
    :data:`_INT_EXTREMES` pins the far ends.

    ``None`` is drawn as a first-class value, not an edge case: it is the
    degree-probe-failed signal, and R3.2's fail-safe says it selects the
    walker.

    The band is derived from the constant rather than written as ``29``
    so an env override (``MCP_BFS_ACTIVATION_THRESHOLD``) moves the
    generator with the implementation instead of quietly aiming the draws
    at the wrong boundary.
    """
    band = st.integers(
        min_value=BFS_ACTIVATION_THRESHOLD - 4,
        max_value=BFS_ACTIVATION_THRESHOLD + 4,
    )
    return st.one_of(
        st.none(),
        st.integers(),
        band,
        st.sampled_from(_INT_EXTREMES),
    )


def selector_depths() -> st.SearchStrategy[int]:
    """Effective_Depth values for the strategy selector.

    Same shape as :func:`selector_degrees` -- unbounded draws, a band
    straddling the :data:`_SHALLOW_DEPTH` cut-off, and the extremes --
    minus the ``None`` case, since ``requested_depth`` arrives from
    :func:`~src.tools._traversal_bounds.effective_depth` and is always an
    ``int``.
    """
    band = st.integers(
        min_value=_SHALLOW_DEPTH - 3,
        max_value=_SHALLOW_DEPTH + 4,
    )
    return st.one_of(
        st.integers(),
        band,
        st.sampled_from(_INT_EXTREMES),
    )


#: Anchor value for :func:`tenant_scope_cases`. Deliberately outside
#: :data:`_ANCHOR_VALUES` and never reused as another node's ``name`` or
#: ``path``, so the anchor resolves to exactly the layer-0 node -- the one
#: node whose label every generated case's scope predicate admits.
_SCOPE_ANCHOR = "scope-case-anchor"

#: Unprefixed label stems a generated node's single label is built from.
#: A node carries exactly one label here (unlike :func:`_labels`, which
#: draws 0-2) so "in scope" / "out of scope" is a property of the node
#: rather than of which of its labels the predicate happened to hit.
_SCOPE_BASE_LABELS = ("File", "ShellScript", "FortranSubroutine")


def _admits(scope_pred: str, node: GraphNode) -> bool:
    """True when the `` AND ...`` fragment ``scope_pred`` admits ``node``.

    Reads the answer off the fragment text with the same
    :func:`_scope_matches` evaluator the graph doubles use, rather than
    off the generator's own label bookkeeping, so a case's ``admitted`` /
    ``rejected`` partition is derived from the very predicate the walker
    will emit. An empty fragment contains no scope term and therefore
    admits every node.
    """
    return all(
        _scope_matches(m, node) for m in _SCOPE_RE.finditer(scope_pred)
    )


@dataclass(frozen=True)
class _ScopeCase:
    """A tenant configuration plus a graph that straddles its scope.

    Attributes
    ----------
    kind
        Which tenant configuration produced ``scope_pred``:
        ``"prefixed"`` (a non-default tenant declaring a label prefix),
        ``"default"`` (the ``gw`` tenant in a catalog that has other
        prefixed tenants), or ``"unscoped"`` (no scoping expressible at
        all). See :func:`tenant_scope_cases` for why the default tenant
        is not the omitted case.
    scope_pred
        The `` AND <Label_Scope_Predicate>`` fragment ``_scope_and("n")``
        yields for ``kind`` -- ``""`` for ``"unscoped"``.
    label_scope_expanded
        Drawn, so both settings of the walker's opt-out flag are covered
        for every tenant kind.
    nodes, edges
        A layered graph in :class:`EdgeGraphDB`'s vocabulary. Layer 0 is
        the anchor; layer 1 always contains at least one node the
        predicate admits *and* one it rejects; layer 2 hangs off both
        groups.
    anchor
        The name to walk from; resolves to the layer-0 node only.
    admitted, rejected
        The partition of ``nodes`` by :func:`_admits`. ``rejected`` is
        non-empty for both scoped kinds -- that is the anti-vacuity
        guarantee -- and empty for ``"unscoped"``.
    edge_types, direction, max_depth, fan_out_limit, result_limit
        Walk parameters. Both limits sit strictly above the whole node
        count, so nothing but the scope predicate can shrink the result
        and ``truncated`` stays ``False``.
    """

    kind: str
    scope_pred: str
    label_scope_expanded: bool
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    anchor: str
    admitted: frozenset[str]
    rejected: frozenset[str]
    edge_types: tuple[str, ...]
    direction: str
    max_depth: int
    fan_out_limit: int
    result_limit: int


def tenant_scope_cases() -> st.SearchStrategy[_ScopeCase]:
    """Tenant configurations paired with a graph that straddles them.

    The generator for Property 6. Where :func:`scope_preds` draws a
    predicate independently of the graph -- fine for a subset or
    termination claim -- this pairs each predicate with a graph built
    *around* it: the anchor is in scope, and its neighborhood deliberately
    mixes nodes the predicate admits with nodes it rejects, at more than
    one depth. That mix is what gives the property bite. A graph whose
    every node is in scope cannot distinguish a correctly-scoped
    expansion from an unscoped one, and it is the shape an
    independently-drawn predicate produces much of the time.

    Three tenant configurations, matching what ``_scope_and("n")``
    actually yields:

    ``"prefixed"``
        A non-default tenant (``gw_v17``, ``gw_sfs``, ...) declaring a
        label prefix. The inclusion form (``... > 0``): a node must own a
        label carrying the prefix. Rejects both unprefixed baseline nodes
        and another tenant's prefixed nodes, and the generator draws
        ``out_label`` from both of those shapes.
    ``"default"``
        The ``gw`` tenant in a catalog that declares other prefixed
        tenants. The exclusion form (``... = 0``) over the *other*
        prefixes: a node must own no prefixed label.
    ``"unscoped"``
        The genuinely empty fragment -- no active tenant context, or a
        catalog in which no tenant declares a prefix. This, not the
        default tenant, is R4.3's "predicate omitted" case: the default
        tenant's exclusion form is a real predicate and *is* applied to
        expanded nodes, because it admits every baseline node while still
        keeping a prefixed neighbor of a baseline anchor out of a ``gw``
        walk. Omitting it there would leak across tenants, so the test
        asserts on what the fragment says rather than mapping "default
        tenant" to "no filter". (The reasoning is
        :func:`~src.tools._bfs_walker._expand_one_hop`'s; it is restated
        here because it is the one place a reader might expect this
        generator to have three cases and find only two.)

    Graph shape. Layer 1 is seeded with one admitted and one rejected
    node before a drawn tail of either, so the straddle is by
    construction rather than by luck. Layer 2 hangs children off *both*
    groups, which is what makes per-hop scoping observable as more than
    a single node's absence: a child of a rejected layer-1 node is
    unreachable under scoping even when the child itself is admitted,
    because its parent never entered the frontier. An implementation that
    filtered only the final result -- or only the anchor -- would still
    return that child.

    ``direction`` is drawn and the edge construction flips with it, so a
    ``reverse`` walk gets a graph oriented into the anchor and meets the
    same straddle. ``max_depth`` starts at 2 so layer 2 is always within
    budget.
    """

    @st.composite
    def _gen(draw: Any) -> _ScopeCase:
        kind = draw(st.sampled_from(("prefixed", "default", "unscoped")))
        base = draw(st.sampled_from(_SCOPE_BASE_LABELS))
        other = draw(st.sampled_from(_SCOPE_BASE_LABELS))

        if kind == "prefixed":
            prefix = draw(st.sampled_from(_LABEL_PREFIXES))
            scope_pred = _inclusion_scope(prefix)
            in_label = prefix + base
            # Rejected by the inclusion form two ways: an unprefixed
            # baseline node, or a rival tenant's prefixed node.
            rivals = tuple(p for p in _LABEL_PREFIXES if p != prefix)
            out_label = draw(st.sampled_from(("",) + rivals)) + other
        elif kind == "default":
            scope_pred = _exclusion_scope()
            in_label = base
            out_label = draw(st.sampled_from(_LABEL_PREFIXES)) + other
        else:
            scope_pred = ""
            # No predicate to straddle, so the labels still mix prefixed
            # and unprefixed nodes: an implementation that invented a
            # scope would prune one group and the test would see it.
            in_label = base
            out_label = draw(st.sampled_from(_LABEL_PREFIXES)) + other

        edge_types = tuple(draw(edge_type_sets()))
        rel = st.sampled_from(edge_types)
        direction = draw(st.sampled_from(("forward", "reverse")))
        max_depth = draw(st.integers(min_value=2, max_value=4))

        def _link(near: str, far: str, rel_type: str) -> GraphEdge:
            """An edge the walk traverses from ``near`` to ``far``.

            A ``reverse`` walk follows incoming edges
            (``MATCH (b)-[:T]->(a)``), so the stored edge is flipped and
            the walk still moves away from the anchor.
            """
            if direction == "reverse":
                return GraphEdge(far, near, rel_type)
            return GraphEdge(near, far, rel_type)

        nodes = [
            GraphNode(
                nid="n0",
                name=_SCOPE_ANCHOR,
                path=None,
                labels=(in_label,),
            )
        ]
        edges: list[GraphEdge] = []
        counter = 1

        def _new_node(label: str) -> str:
            nonlocal counter
            nid = f"n{counter}"
            counter += 1
            nodes.append(
                GraphNode(
                    nid=nid,
                    name=nid,
                    path=f"ush/{nid}.sh",
                    labels=(label,),
                )
            )
            return nid

        layer1_labels = [in_label, out_label]
        for _ in range(draw(st.integers(min_value=0, max_value=2))):
            layer1_labels.append(
                draw(st.sampled_from((in_label, out_label)))
            )
        layer1 = [_new_node(label) for label in layer1_labels]
        for nid in layer1:
            edges.append(_link("n0", nid, draw(rel)))

        for parent in layer1:
            if draw(st.booleans()):
                child = _new_node(
                    draw(st.sampled_from((in_label, out_label)))
                )
                edges.append(_link(parent, child, draw(rel)))

        admitted = frozenset(
            node.nid for node in nodes if _admits(scope_pred, node)
        )
        rejected = frozenset(node.nid for node in nodes) - admitted

        total = len(nodes)
        return _ScopeCase(
            kind=kind,
            scope_pred=scope_pred,
            label_scope_expanded=draw(st.booleans()),
            nodes=tuple(nodes),
            edges=tuple(edges),
            anchor=_SCOPE_ANCHOR,
            admitted=admitted,
            rejected=rejected,
            edge_types=edge_types,
            direction=direction,
            max_depth=max_depth,
            # Strictly above the node count, so neither the Fan_Out_Limit
            # nor the global cap can bite: the scope predicate is then the
            # only thing that can keep a reachable node out of the result.
            fan_out_limit=total + draw(st.integers(1, 3)),
            result_limit=total + draw(st.integers(1, 3)),
        )

    return _gen()


def timeout_plans() -> st.SearchStrategy[_TimeoutPlan]:
    """Timeout-injection plans for a walk (see :class:`_TimeoutPlan`).

    The generator for Property 7's walker half. All three selectors are
    drawn independently of the graph, so a plan routinely selects calls
    the walk never makes (an ordinal past its query count, an edge type
    the graph does not carry) -- which is the point: the walker must be
    unmoved by a plan that does not fire, and Property 7 reads what
    actually fired back off the double rather than predicting it.

    Ordinals reach 9, comfortably past the query count of the graphs
    :func:`dead_end_graphs` produces (``1 + |edge_types| * hops``, at most
    12 at the generator's ceiling but typically 3-6), so a plan lands
    inside the walk most of the time while still drawing the
    selects-nothing case.
    """
    return st.builds(
        _TimeoutPlan,
        indices=st.frozensets(
            st.integers(min_value=0, max_value=9), max_size=3
        ),
        kinds=st.frozensets(
            st.sampled_from(("anchor", "expansion")), max_size=2
        ),
        edge_types=st.frozensets(
            st.sampled_from(_EDGE_TYPES), max_size=len(_EDGE_TYPES)
        ),
        shape=st.sampled_from(_TIMEOUT_SHAPES),
    )


def tool_fail_kinds() -> st.SearchStrategy[frozenset[str]]:
    """Subsets of :data:`_TOOL_KINDS` to time out in the tool chain.

    The generator for Property 7's tool half. Every subset is drawn,
    including the empty one (no timeout at all -- the control that shows
    the seeded chain renders normally) and the full one (every stage
    dark), because the property's claim is that *no* combination escapes
    as an exception.

    ``entity`` is drawn like any other stage even though it is the one
    whose timeout the design routes to an ``[ERROR]`` response rather
    than to a Degraded_Result ("cannot proceed without anchor" in the
    design's Error Handling table). Excluding it would leave that row
    untested; the test asserts the ``[ERROR]`` outcome for it explicitly,
    which is still a handled string and not an escaped exception.
    """
    return st.frozensets(st.sampled_from(_TOOL_KINDS))


#: Anchor value for :func:`wide_fan_out_graphs`. Deliberately outside
#: :data:`_ANCHOR_VALUES` and never reused as another node's ``name`` or
#: ``path``, so the anchor resolves to exactly the layer-0 node and every
#: other node's constructed depth is the hop the walk must find it at.
_WIDE_ANCHOR = "wide-fan-out-anchor"


@dataclass(frozen=True)
class _WideGraph:
    """A graph where every hop offers more neighbors than the limit.

    Attributes
    ----------
    nodes, edges
        The graph, in :class:`EdgeGraphDB`'s vocabulary.
    depths
        ``nid`` -> distance from the anchor, in ``direction``. Edges join
        consecutive layers only, so each node sits at exactly one
        distance and this doubles as the expected ``hop``.
    anchor
        The name to walk from; resolves to the layer-0 node only.
    edge_types, direction, max_depth
        Walk parameters. Every hop in ``1..max_depth`` has a saturating
        expansion for *every* type in ``edge_types``.
    fan_out_limit
        The Fan_Out_Limit to walk with -- strictly *below* every
        ``widths`` entry, which is what makes the bound bite.
    result_limit
        Strictly above the whole node count, so the global cap cannot
        fire and ``truncated`` is attributable to the Fan_Out_Limit
        alone.
    scope_pred
        A Label_Scope_Predicate that admits every node in ``nodes``, so
        scoping never removes a neighbor the limit was supposed to
        remove.
    widths
        Edge type -> the number of distinct hop-1 neighbors the anchor
        has of that type. Every entry exceeds ``fan_out_limit``.
    """

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    depths: dict[str, int]
    anchor: str
    edge_types: tuple[str, ...]
    direction: str
    max_depth: int
    fan_out_limit: int
    result_limit: int
    scope_pred: str
    widths: dict[str, int]

    def reachable(self) -> set[str]:
        """Non-anchor nodes within ``max_depth``, by construction."""
        return {
            nid
            for nid, depth in self.depths.items()
            if 1 <= depth <= self.max_depth
        }


def wide_fan_out_graphs() -> st.SearchStrategy[_WideGraph]:
    """Graphs whose every hop has more neighbors than the Fan_Out_Limit.

    The generator for Property 8. The other graph generators draw a limit
    independently of the graph, so most of their examples never approach
    it -- fine for a subset or termination claim, but it would make a
    bound-enforcement claim vacuous. Here the relationship is inverted:
    the limit is drawn *first*, small, and the graph is then built wide
    enough that every single expansion the walk issues has strictly more
    candidate neighbors than the limit admits. Each per-type, per-hop
    query therefore saturates, and its row count sits exactly on the
    bound rather than somewhere below it.

    Shape. Layer 0 is the anchor. For each drawn relationship type it
    gets its own fan of ``fan_out_limit + surplus`` layer-1 neighbors, so
    the types saturate independently instead of competing for one shared
    fan (a shared fan would let ``RETURN DISTINCT`` collapse the second
    type's rows and hide a per-type accounting error behind a per-hop
    total that still looked bounded). When ``max_depth`` reaches 2, a
    second fan of the same width hangs off the *first* neighbor of each
    type's layer-1 fan -- the first, because it is the one guaranteed to
    survive the hop-1 ``LIMIT`` and enter the frontier, so hop 2
    saturates too. The surplus nodes beyond the limit are unreachable
    under the bound and reachable without it, which is what the test's
    control run turns into a strict inequality.

    ``direction`` is drawn and the edge construction flips with it, so a
    ``reverse`` walk gets a fan oriented *into* the anchor and meets the
    same width. Scope is drawn from :func:`uniform_scopes` so the
    predicate admits every node: a scope that pruned neighbors would
    leave the saturation point unknown, which is the same reason
    :func:`dead_end_graphs` pairs its scope with its labels.

    Sizes. ``fan_out_limit`` is capped at 4 (and never above
    :data:`~src.tools._traversal_bounds.BFS_FAN_OUT_LIMIT`, so an env
    override cannot put the drawn limit above the constant the property
    is stated against), and depth at 2, which keeps the widest graph
    around 40 nodes while still exercising saturation at more than one
    hop.
    """

    @st.composite
    def _gen(draw: Any) -> _WideGraph:
        ceiling = max(1, min(4, BFS_FAN_OUT_LIMIT))
        fan_out_limit = draw(st.integers(min_value=1, max_value=ceiling))
        edge_types = tuple(draw(edge_type_sets()))
        direction = draw(st.sampled_from(("forward", "reverse")))
        max_depth = draw(st.integers(min_value=1, max_value=2))
        scope_pred, label = draw(uniform_scopes())

        def _link(near: str, far: str, rel_type: str) -> GraphEdge:
            """An edge the walk traverses from ``near`` to ``far``.

            A ``reverse`` walk follows incoming edges
            (``MATCH (b)-[:T]->(a)``), so the stored edge is flipped and
            the walk still moves away from the anchor.
            """
            if direction == "reverse":
                return GraphEdge(far, near, rel_type)
            return GraphEdge(near, far, rel_type)

        nodes = [
            GraphNode(
                nid="n0",
                name=_WIDE_ANCHOR,
                path=None,
                labels=(label,),
            )
        ]
        depths: dict[str, int] = {"n0": 0}
        edges: list[GraphEdge] = []
        widths: dict[str, int] = {}
        counter = 1

        def _new_node(depth: int) -> str:
            nonlocal counter
            nid = f"n{counter}"
            counter += 1
            nodes.append(
                GraphNode(
                    nid=nid,
                    name=nid,
                    path=f"ush/{nid}.sh",
                    labels=(label,),
                )
            )
            depths[nid] = depth
            return nid

        for edge_type in edge_types:
            width = fan_out_limit + draw(st.integers(1, 3))
            widths[edge_type] = width
            fan = [_new_node(1) for _ in range(width)]
            for nid in fan:
                edges.append(_link("n0", nid, edge_type))
            if max_depth >= 2:
                # Hung off fan[0] only: it is the first row the hop-1
                # LIMIT keeps, so it is in the frontier whatever the
                # limit is, and its own fan is wider than the limit too.
                deep = fan_out_limit + draw(st.integers(1, 3))
                for _ in range(deep):
                    edges.append(
                        _link(fan[0], _new_node(2), edge_type)
                    )

        return _WideGraph(
            nodes=tuple(nodes),
            edges=tuple(edges),
            depths=depths,
            anchor=_WIDE_ANCHOR,
            edge_types=edge_types,
            direction=direction,
            max_depth=max_depth,
            fan_out_limit=fan_out_limit,
            # Strictly above the node count, so the global cap cannot
            # fire: the Fan_Out_Limit is then the only bound in play.
            result_limit=len(nodes) + draw(st.integers(1, 3)),
            scope_pred=scope_pred,
            widths=widths,
        )

    return _gen()


# ---------------------------------------------------------------------------
# Property 1: UNION ALL Set Equivalence
# ---------------------------------------------------------------------------


@_SETTINGS
@given(
    nodes=graph_nodes(),
    name=st.sampled_from(_ANCHOR_VALUES),
    scope_pred=scope_preds(),
)
def test_p1_union_all_set_equivalence(
    nodes: tuple[GraphNode, ...], name: str, scope_pred: str
) -> None:
    """Feature: neptune-traversal-query-optimization, Property 1: For any
    anchor name ``n`` and scope predicate ``s``, the UNION ALL
    decomposition SHALL return the same set of node IDs as the original
    OR-predicate, with deduplication.

    Validates: Requirements 1.3
    """
    union_db = AnchorGraphDB(nodes=nodes)
    or_db = AnchorGraphDB(nodes=nodes)

    union_ids = asyncio.run(
        resolve_anchor_ids(
            union_db,
            name,
            scope_pred=scope_pred,
            tenant=_TENANT_SENTINEL,
            timeout_s=_TIMEOUT_S,
        )
    )
    or_ids = asyncio.run(
        _resolve_via_or(
            or_db,
            name,
            scope_pred=scope_pred,
            tenant=_TENANT_SENTINEL,
            timeout_s=_TIMEOUT_S,
        )
    )

    # Set-equivalent to the predicate it replaced, under every scope form.
    assert set(union_ids) == set(or_ids)
    # ...and deduplicated, even though UNION ALL itself does not dedupe:
    # a node matched by both name and path arrives from both branches.
    assert len(union_ids) == len(set(union_ids))

    # The rewrite is the point: two indexable equality branches, no
    # disjunction across two properties of an unlabelled node (R1.1).
    emitted = union_db.cyphers()
    assert len(emitted) == 1
    assert "UNION ALL" in emitted[0]
    assert "OR" not in _anchor_residual(emitted[0])
    # Both branches carry the scope predicate and the same anchor param,
    # so neither leaks another tenant's nodes into the result (R1.4).
    branches = _split_union_all(emitted[0])
    assert len(branches) == 2
    for branch in branches:
        assert "$name" in branch
        if scope_pred:
            assert scope_pred.removeprefix(" AND ") in branch
    # Statement_Timeout and tenant are carried through unchanged (R1.4).
    assert union_db.call_log[0][3] == {
        "tenant": _TENANT_SENTINEL,
        "timeout": _TIMEOUT_S,
    }


def _anchor_residual(cypher: str) -> str:
    """The anchor predicate text with scope fragments removed.

    Lets the "no ``OR`` disjunction" assertion above look at the anchor
    predicate alone: the default tenant's exclusion scope predicate
    legitimately contains ``OR`` between its prefix terms.
    """
    return " ".join(
        _SCOPE_RE.sub("", _where_clause(branch))
        for branch in _split_union_all(cypher)
    )

# ---------------------------------------------------------------------------
# Property 2: BFS Subset Guarantee
# ---------------------------------------------------------------------------


@_SETTINGS
@given(
    graph=anchored_dag_graphs(),
    direction=st.sampled_from(("forward", "reverse")),
    edge_types=edge_type_sets(),
    max_depth=st.integers(min_value=1, max_value=4),
    fan_out_limit=st.integers(min_value=1, max_value=4),
    result_limit=st.integers(min_value=1, max_value=12),
    scope_pred=scope_preds(),
)
def test_p2_bfs_subset_guarantee(
    graph: tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...], str],
    direction: str,
    edge_types: list[str],
    max_depth: int,
    fan_out_limit: int,
    result_limit: int,
    scope_pred: str,
) -> None:
    """Feature: neptune-traversal-query-optimization, Property 2: For any
    start node and edge set, the BFS Walker's result set SHALL be a subset
    of the nodes reachable via the equivalent variable-length pattern --
    it may discover fewer nodes (due to the Fan_Out_Limit) but SHALL NOT
    introduce any node that the original pattern would not reach.

    Validates: Requirements 2.7
    """
    nodes, edges, name = graph
    walk_db = EdgeGraphDB(nodes=nodes, edges=edges)
    ref_db = EdgeGraphDB(nodes=nodes, edges=edges)

    result = asyncio.run(
        bfs_walk(
            walk_db,
            start_name=name,
            direction=direction,
            edge_types=edge_types,
            max_depth=max_depth,
            fan_out_limit=fan_out_limit,
            result_limit=result_limit,
            timeout_s=_TIMEOUT_S,
            scope_pred=scope_pred,
            tenant=_TENANT_SENTINEL,
            label_scope_expanded=bool(scope_pred),
        )
    )
    reference = asyncio.run(
        _expand_via_variable_length(
            ref_db,
            name,
            direction=direction,
            edge_types=edge_types,
            max_depth=max_depth,
            scope_pred=scope_pred,
            tenant=_TENANT_SENTINEL,
            timeout_s=_TIMEOUT_S,
        )
    )

    walked = [node["nid"] for node in result.nodes]

    # The property: the decomposed walk never invents reachability the
    # single variable-length pattern did not have.
    assert set(walked) <= set(reference)

    # Each node is reported once, and every reported node carries honest
    # provenance -- an edge type from the requested set, the walk's own
    # direction, and a hop inside the depth budget. A node whose relType
    # or hop did not match would be a node the reference pattern reaches
    # by some *other* route than the one claimed, which set-containment
    # alone cannot catch.
    assert len(walked) == len(set(walked))
    assert len(walked) <= result_limit
    assert result.hops_expanded <= max_depth
    for node in result.nodes:
        assert node["relType"] in edge_types
        assert node["direction"] == direction
        assert 1 <= node["hop"] <= max_depth

    # The query-level reason the node-level subset holds: every expansion
    # the walk issued was a single hop over a requested type in the
    # requested direction. An expansion over an unrequested type would
    # reach nodes the reference pattern has no route to at all -- and it
    # would still be reported under a requested type's ``relType``, so
    # the checks above cannot see it on the graphs where the extra type
    # happens to lead nowhere new.
    for cypher in walk_db.cyphers():
        spec = _parse_expansion(cypher)
        if spec is None:
            continue  # The anchor resolution, covered by Property 1.
        assert set(spec.types) <= set(edge_types)
        assert spec.direction == direction
        assert spec.depth == 1

    # Anti-vacuity counterpart: subset alone is satisfied by a walker that
    # returns nothing, so when none of the walker's bounds can bite --
    # per-hop and global caps above the whole node count, no hop scoping
    # -- the walk must reach everything the pattern reaches. The
    # Anchor_Node is excluded because bfs_walk seeds its visited-set with
    # it while a variable-length pattern will report it as an endpoint if
    # some path leads back to it.
    anchors = {node.nid for node in nodes if name in (node.name, node.path)}
    unbounded = (
        not scope_pred
        and fan_out_limit >= len(nodes)
        and result_limit >= len(nodes)
    )
    if unbounded:
        assert set(reference) - anchors <= set(walked)


# ---------------------------------------------------------------------------
# Property 3: BFS Visited-Set Prevents Cycles
# ---------------------------------------------------------------------------

#: Wall-clock bound for a Property 3 walk. Deliberately far below
#: :data:`_TIMEOUT_S`: every query in this test is an in-memory dict
#: lookup over at most 6 nodes, so a walk that approaches even one second
#: is looping, not working. Keeping it low also means a genuine
#: non-termination bug fails the assertion in seconds instead of hanging
#: the suite for 30s per example.
_CYCLE_TIMEOUT_S = 5.0


@_SETTINGS
@given(
    graph=anchored_cyclic_graphs(),
    direction=st.sampled_from(("forward", "reverse")),
    edge_types=edge_type_sets(),
    max_depth=st.integers(min_value=1, max_value=4),
    fan_out_limit=st.integers(min_value=1, max_value=8),
    result_limit=st.integers(min_value=1, max_value=12),
    scope_pred=scope_preds(),
)
def test_p3_visited_set_prevents_cycles(
    graph: tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...], str],
    direction: str,
    edge_types: list[str],
    max_depth: int,
    fan_out_limit: int,
    result_limit: int,
    scope_pred: str,
) -> None:
    """Feature: neptune-traversal-query-optimization, Property 3: For any
    graph containing cycles, the BFS Walker SHALL terminate (never loop
    indefinitely) because a node already in the visited set is not
    re-expanded, and the frontier shrinks monotonically toward empty.

    Validates: Requirements 2.4
    """
    nodes, edges, name = graph
    walk_db = EdgeGraphDB(nodes=nodes, edges=edges)
    ref_db = EdgeGraphDB(nodes=nodes, edges=edges)

    started = time.monotonic()
    result = asyncio.run(
        bfs_walk(
            walk_db,
            start_name=name,
            direction=direction,
            edge_types=edge_types,
            max_depth=max_depth,
            fan_out_limit=fan_out_limit,
            result_limit=result_limit,
            timeout_s=_CYCLE_TIMEOUT_S,
            scope_pred=scope_pred,
            tenant=_TENANT_SENTINEL,
            label_scope_expanded=bool(scope_pred),
        )
    )
    elapsed = time.monotonic() - started

    # Termination, measured two ways. The observed wall clock shows the
    # call returned at all; the walker's own counter shows it returned
    # *on its own* rather than by having its outer wait_for expire, which
    # is the failure mode a looping expansion would produce and which
    # `elapsed` alone cannot distinguish from success.
    assert elapsed < _CYCLE_TIMEOUT_S
    assert result.wall_clock_ms < _CYCLE_TIMEOUT_S * 1000

    # Termination in query count, which is the bound that actually
    # matters operationally: 1 anchor resolution plus one query per type
    # per hop (R2.2). A walk that re-expanded visited nodes would still
    # finish quickly on a 6-node graph, so the wall-clock assertions
    # above cannot see it -- an unbounded hop count can.
    expansions = [
        call
        for call in walk_db.call_log
        if call[0] == "query" and _parse_expansion(call[1][0]) is not None
    ]
    assert len(expansions) <= len(edge_types) * max_depth
    assert result.queries_issued <= 1 + len(edge_types) * max_depth
    assert result.hops_expanded <= max_depth

    walked = [node["nid"] for node in result.nodes]

    # The property's headline consequence: each node appears once in the
    # output no matter how many cycles route back to it.
    assert len(walked) == len(set(walked))
    assert len(walked) <= result_limit
    for node in result.nodes:
        assert node["relType"] in edge_types
        assert node["direction"] == direction
        assert 1 <= node["hop"] <= max_depth

    # The Anchor_Node is seeded into the visited-set, so a cycle leading
    # back to it must not report it as a discovered neighbor. Anchor ids
    # come from the harness's independent OR resolution rather than from
    # `resolve_anchor_ids`, so the implementation is not its own oracle.
    anchor_ids = set(
        asyncio.run(
            _resolve_via_or(
                ref_db,
                name,
                scope_pred=scope_pred,
                tenant=_TENANT_SENTINEL,
                timeout_s=_CYCLE_TIMEOUT_S,
            )
        )
    )
    assert set(walked).isdisjoint(anchor_ids)

    # "The frontier shrinks monotonically toward empty", read off the
    # emitted queries: the ids each hop seeks on. All the queries in one
    # hop share a frontier (they differ only in relationship type), and
    # no id is ever expanded by two different hops -- which is the
    # visited-set doing its job at the level the walker is charged with,
    # one step below the deduplicated output above.
    frontiers = [
        tuple(call[2].get("ids") or ()) for call in expansions
    ]
    per_hop: list[tuple[str, ...]] = []
    for i in range(0, len(frontiers), len(edge_types)):
        hop = frontiers[i:i + len(edge_types)]
        assert all(f == hop[0] for f in hop)
        per_hop.append(hop[0])

    expanded: set[str] = set()
    for hop_ids in per_hop:
        # A non-empty frontier every time: an empty one would have ended
        # the walk before issuing a query (R2.5).
        assert hop_ids
        assert set(hop_ids).isdisjoint(expanded)
        expanded |= set(hop_ids)

    # Anti-vacuity. Everything above is satisfied by a walker that
    # terminates by returning nothing, so when none of the bounds can
    # bite -- no hop scoping, per-hop and global caps above the whole node
    # count -- the walk must have reached *exactly* the nodes within
    # `max_depth` of the anchor. The reference enumerates walks with no
    # visited-set at all (`_walk_endpoints`, the `*1..N` reading), so on a
    # cyclic graph it re-visits nodes freely and the equality is a real
    # statement that the walker went around each cycle and stopped rather
    # than either looping or bailing out early. Bounded by `max_depth`
    # (<= 4) over <= 6 nodes, so the enumeration stays small.
    spec = _Expansion(
        direction=direction,
        types=tuple(edge_types),
        depth=max_depth,
        limit=_REFERENCE_LIMIT,
    )
    reachable = set(
        _walk_endpoints(
            sorted(anchor_ids), ref_db.adjacency(spec), max_depth
        )
    )
    unbounded = (
        not scope_pred
        and fan_out_limit >= len(nodes)
        and result_limit >= len(nodes)
    )
    if unbounded:
        assert set(walked) == reachable - anchor_ids

# ---------------------------------------------------------------------------
# Property 4: BFS Early Termination
# ---------------------------------------------------------------------------


@_SETTINGS
@given(graph=dead_end_graphs())
def test_p4_bfs_early_termination(graph: _DeadEndGraph) -> None:
    """Feature: neptune-traversal-query-optimization, Property 4: For any
    graph where the reachable neighborhood is shallower than ``max_depth``,
    the BFS Walker SHALL stop issuing queries at the depth where the
    frontier becomes empty, and ``hops_expanded`` SHALL reflect the actual
    depth reached rather than the requested ``max_depth``.

    Validates: Requirements 2.5
    """
    walk_db = EdgeGraphDB(nodes=graph.nodes, edges=graph.edges)

    result = asyncio.run(
        bfs_walk(
            walk_db,
            start_name=graph.anchor,
            direction=graph.direction,
            edge_types=list(graph.edge_types),
            max_depth=graph.max_depth,
            fan_out_limit=graph.fan_out_limit,
            result_limit=graph.result_limit,
            timeout_s=_TIMEOUT_S,
            scope_pred=graph.scope_pred,
            tenant=_TENANT_SENTINEL,
            label_scope_expanded=bool(graph.scope_pred),
        )
    )

    # The walk expands one hop past the deepest layer -- that hop is the
    # one that discovers the frontier is empty -- and then stops. So the
    # expected depth is a constructed constant, not a re-derivation of
    # the walker's own loop: ``reach_depth`` hops that find nodes, plus
    # the one that finds none.
    expected_hops = min(graph.reach_depth + 1, graph.max_depth)

    # The headline: the counter reports where the walk actually stopped,
    # not the budget it was handed.
    assert result.hops_expanded == expected_hops
    # Nothing cut the walk short from the outside: no Fan_Out_Limit, no
    # global cap, no timeout. Without this, "stopped early" would be
    # indistinguishable from "was truncated" (R2.3 vs R2.5).
    assert result.truncated is False

    expansions = [
        call
        for call in walk_db.call_log
        if call[0] == "query" and _parse_expansion(call[1][0]) is not None
    ]
    per_type = len(graph.edge_types)

    # The observable consequence, at the level that costs money: one
    # query per type per expanded hop (R2.2) and *none at all* for the
    # hops between the empty frontier and ``max_depth``. A walker that
    # kept looping on an empty frontier would still return the same nodes
    # -- only the query count can see it.
    assert len(expansions) == per_type * expected_hops
    assert result.queries_issued == 1 + per_type * expected_hops
    if graph.max_depth > expected_hops:
        assert len(expansions) < per_type * graph.max_depth

    # Group the emitted frontiers by hop: the queries within one hop
    # differ only in relationship type, so they share a frontier.
    per_hop: list[set[str]] = []
    for i in range(0, len(expansions), per_type):
        hop_calls = [
            tuple(call[2].get("ids") or ())
            for call in expansions[i:i + per_type]
        ]
        assert all(ids == hop_calls[0] for ids in hop_calls)
        per_hop.append(set(hop_calls[0]))

    by_hop: dict[int, set[str]] = {}
    for node in result.nodes:
        by_hop.setdefault(node["hop"], set()).add(node["nid"])

    # Each hop's frontier is exactly the previous hop's discoveries, and
    # each one is non-empty -- an empty frontier would have ended the
    # walk instead of being queried. Hop 1 seeks the Anchor_Node.
    assert per_hop[0] == {"n0"}
    for hop in range(1, expected_hops):
        assert per_hop[hop] == by_hop.get(hop, set())
        assert per_hop[hop]

    # And the final hop is the one that found nothing new: it emptied the
    # frontier, which is *why* the walk stopped there rather than at
    # ``max_depth``.
    assert by_hop.get(expected_hops, set()) == set()

    # Anti-vacuity. Every assertion above is satisfied by a walker that
    # resolves the anchor and returns nothing (expected_hops would be 1
    # and the graph would have to be empty) -- and by a walker that
    # stopped at the first dead-end branch instead of the empty frontier.
    # Neither survives this: with no bound able to bite and a scope
    # predicate that admits every node, the walk must have reached the
    # whole constructed graph, at each node's constructed depth.
    walked = {node["nid"] for node in result.nodes}
    reachable = {nid for nid in graph.depths if nid != "n0"}
    assert walked == reachable
    assert walked  # reach_depth >= 1, so there is always something.
    for node in result.nodes:
        assert node["hop"] == graph.depths[node["nid"]]
        assert node["hop"] <= graph.reach_depth
        assert node["relType"] in graph.edge_types
        assert node["direction"] == graph.direction


# ---------------------------------------------------------------------------
# Property 5: Strategy Selection Consistency
# ---------------------------------------------------------------------------


def test_p5_activation_threshold_default() -> None:
    """The documented default the Property 5 draws are aimed at (R3.4).

    :func:`selector_degrees` derives its boundary band from the constant,
    so the property stays correct under an env override -- but the
    *design* commits to 30, and a silent change to that default would
    shift which operational nodes get the decomposed walk without any
    property failing. Pinned here rather than left to the unit suite so
    the number this file's draws cluster around is stated where they are
    drawn. Skipped when the override is actually in effect, since then the
    default is not the value under test.
    """
    if "MCP_BFS_ACTIVATION_THRESHOLD" in os.environ:
        pytest.skip("MCP_BFS_ACTIVATION_THRESHOLD override in effect")
    assert BFS_ACTIVATION_THRESHOLD == 30


@_SETTINGS
@given(degree=selector_degrees(), depth=selector_depths())
def test_p5_strategy_selection_consistency(
    degree: int | None, depth: int
) -> None:
    """Feature: neptune-traversal-query-optimization, Property 5: For any
    node with degree below ``BFS_ACTIVATION_THRESHOLD`` and requested depth
    <= 3, the strategy selector SHALL choose the single-query path, and the
    results SHALL be equivalent to the pre-optimization behavior.

    Validates: Requirements 3.1, 5.1
    """
    # The single-query condition, stated positively and independently of
    # the implementation's ``or`` chain: a *measured* degree strictly
    # below the threshold and a depth inside the shallow band. Any other
    # (degree, depth) -- including an unmeasured degree -- takes the
    # walker.
    single_query = (
        degree is not None
        and degree < BFS_ACTIVATION_THRESHOLD
        and depth <= _SHALLOW_DEPTH
    )

    # The biconditional, not just one direction. "Returns False only
    # when ..." forbids a False outside the band (R3.2 would then be
    # skipped for a node that needs the walker), and R3.1/R5.1 forbid a
    # True inside it (the single-query path is what preserves
    # pre-optimization results for the common case).
    assert _use_bfs(degree, depth) is (not single_query)

    # The fail-safe branch, on every example: an unmeasurable degree is
    # never allowed to fall into the single-query band no matter what
    # depth accompanies it (R3.2, mirroring ``is_hub``).
    assert _use_bfs(None, depth) is True

    # Monotone in both arguments: nothing about a *more* connected anchor
    # or a *deeper* request can turn the bounded walk back off. This is
    # what makes the selector a threshold rather than a window, and it is
    # invisible to a single point-wise check.
    if _use_bfs(degree, depth):
        assert _use_bfs(degree, depth + 1) is True
        if degree is not None:
            assert _use_bfs(degree + 1, depth) is True

    # Anti-vacuity. A single draw witnesses one side of the biconditional,
    # and the single-query band is narrow (a 30-wide degree window and a
    # 3-deep depth window inside an unbounded int range), so most examples
    # land on the BFS side and a selector hard-wired to True would survive
    # a large share of them. Pinning the drawn values into each region in
    # turn makes every example witness all four transitions, so a
    # constant selector -- or one keying on the wrong constant -- fails on
    # the first example rather than on a lucky draw.
    shallow = min(depth, _SHALLOW_DEPTH)
    low = BFS_ACTIVATION_THRESHOLD - 1
    assert _use_bfs(low, shallow) is False
    assert _use_bfs(BFS_ACTIVATION_THRESHOLD, shallow) is True
    assert _use_bfs(low, _SHALLOW_DEPTH + 1) is True
    assert _use_bfs(None, shallow) is True


# ---------------------------------------------------------------------------
# Property 6: Label Scope on Expanded Nodes
# ---------------------------------------------------------------------------


@_SETTINGS
@given(case=tenant_scope_cases())
def test_p6_label_scope_on_expanded_nodes(case: _ScopeCase) -> None:
    """Feature: neptune-traversal-query-optimization, Property 6: For any
    non-default tenant and BFS hop, every node in the expansion result
    SHALL carry a label matching the tenant's prefix (verified via the
    Label_Scope_Predicate applied to the target node in each per-hop
    query).

    Validates: Requirements 4.1, 4.2
    """
    walk_db = EdgeGraphDB(nodes=case.nodes, edges=case.edges)

    result = asyncio.run(
        bfs_walk(
            walk_db,
            start_name=case.anchor,
            direction=case.direction,
            edge_types=list(case.edge_types),
            max_depth=case.max_depth,
            fan_out_limit=case.fan_out_limit,
            result_limit=case.result_limit,
            timeout_s=_TIMEOUT_S,
            scope_pred=case.scope_pred,
            tenant=_TENANT_SENTINEL,
            label_scope_expanded=case.label_scope_expanded,
        )
    )

    anchor_cyphers: list[str] = []
    expansions: list[str] = []
    for call in walk_db.call_log:
        if call[0] != "query":
            continue
        cypher = call[1][0]
        if _parse_expansion(cypher) is None:
            anchor_cyphers.append(cypher)
        else:
            expansions.append(cypher)

    # The anchor is in scope by construction, so it resolves and the walk
    # really does reach its hop loop -- without this, every query-shape
    # assertion below would hold over an empty list.
    assert len(anchor_cyphers) == 1
    assert expansions
    # Nothing but the scope predicate can shrink this walk's result: both
    # limits sit above the node count and the timeout is far off.
    assert result.truncated is False

    # The anchor's own predicate, which the expansion's must match. It is
    # carried on every UNION ALL branch and on the anchor variable ``n``,
    # whatever ``label_scope_expanded`` says -- opting a walk out of
    # target scoping never un-scopes its anchor resolution (R1.4).
    anchor_scopes: list[str] = []
    for branch in _split_union_all(anchor_cyphers[0]):
        found = list(_SCOPE_RE.finditer(_where_clause(branch)))
        if not case.scope_pred:
            assert not found
            continue
        assert len(found) == 1
        assert found[0].group("var") == "n"
        anchor_scopes.append(found[0].group(0))
    assert len(set(anchor_scopes)) == (1 if case.scope_pred else 0)

    # R4.1 holds only when the walk was asked to scope expanded nodes;
    # ``label_scope_expanded=False`` is the documented opt-out (and an
    # empty fragment has nothing to emit either way, R4.3).
    scoped = bool(case.scope_pred and case.label_scope_expanded)

    for cypher in expansions:
        found = list(_SCOPE_RE.finditer(_where_clause(cypher)))
        if not scoped:
            # R4.3: no filter at all on the expansion.
            assert not found
            continue
        assert len(found) == 1
        # The headline (R4.1): the predicate is bound to the expansion
        # TARGET, not to the frontier node it seeks from. A predicate on
        # ``a`` would be trivially satisfied -- every frontier node was
        # already admitted when it was discovered -- so it would filter
        # nothing while looking present, and no node-level assertion
        # could tell the two apart on a double that evaluates endpoints.
        assert found[0].group("var") == "b"
        assert "labels(a)" not in cypher
        assert "labels(n)" not in cypher
        # R4.4: the *same* ``_scope_and`` output as the anchor's, differing
        # only in the variable it names. A predicate that agreed on the
        # target variable but drifted in its prefix list or its
        # ``> 0`` / ``= 0`` sense would scope the expansion to a different
        # tenant than the anchor was resolved under.
        assert found[0].group(0) == anchor_scopes[0].replace(
            "labels(n)", "labels(b)"
        )

    walked = {node["nid"] for node in result.nodes}
    by_id = {node.nid: node for node in case.nodes}

    spec = _Expansion(
        direction=case.direction,
        types=case.edge_types,
        depth=case.max_depth,
        limit=_REFERENCE_LIMIT,
    )
    adjacency = walk_db.adjacency(spec)
    reach_all = _scoped_reach(adjacency, "n0", case.max_depth, None)
    reach_scoped = _scoped_reach(
        adjacency, "n0", case.max_depth, case.admitted
    )

    if scoped:
        # The node-level consequence of the query-level claim, evaluated
        # against the predicate the walker actually emitted rather than
        # against the generator's label bookkeeping: every discovered
        # node satisfies it.
        emitted = _SCOPE_RE.search(_where_clause(expansions[0]))
        assert emitted is not None
        for nid in walked:
            assert _scope_matches(emitted, by_id[nid])
        assert walked <= case.admitted
        assert walked.isdisjoint(case.rejected)

        # Scoping at *every* hop, not just on the result: the walk reaches
        # exactly what is reachable through admitted nodes. A child of a
        # rejected layer-1 node is absent even when the child itself is
        # admitted, because its parent never entered the frontier.
        assert walked == reach_scoped

        # Anti-vacuity. Everything above is satisfied by a graph the
        # predicate happens to admit entirely -- and by a walker that
        # returns nothing. Neither survives this: the graph really does
        # carry out-of-scope neighbors that are reachable from the
        # anchor, the predicate really does exclude them, and what
        # remains is not empty.
        assert case.rejected & reach_all
        assert reach_scoped < reach_all
        assert walked

        # R4.2: the single-query variable-length pattern the walker
        # replaces scopes the *terminal* node of its path the same way,
        # so the two strategies agree on which tenant's nodes they may
        # report. It filters only the terminal node (intermediates are
        # unconstrained by a ``*1..N`` pattern's WHERE), so the walk's
        # per-hop filtering can only reach fewer nodes.
        ref_db = EdgeGraphDB(nodes=case.nodes, edges=case.edges)
        reference = asyncio.run(
            _expand_via_variable_length(
                ref_db,
                case.anchor,
                direction=case.direction,
                edge_types=list(case.edge_types),
                max_depth=case.max_depth,
                scope_pred=case.scope_pred,
                tenant=_TENANT_SENTINEL,
                timeout_s=_TIMEOUT_S,
            )
        )
        assert walked <= set(reference)
        assert set(reference).isdisjoint(case.rejected)
        for cypher in ref_db.cyphers():
            if _parse_expansion(cypher) is None:
                continue
            terminal = _SCOPE_RE.search(_where_clause(cypher))
            assert terminal is not None
            assert terminal.group("var") == "b"
    else:
        # The complement: with no predicate to apply -- or with target
        # scoping opted out -- the walk reaches the whole neighborhood.
        assert walked == reach_all
        assert walked
        if case.scope_pred:
            # It is the flag that decided, not the graph shape: the same
            # predicate that excluded these nodes above is still on the
            # anchor query, and they are all discovered anyway.
            assert case.rejected & walked
        else:
            # R4.3 with real bite: the graph mixes tenant-prefixed and
            # unprefixed nodes, so a walker that invented a scope for the
            # empty fragment would have pruned one of the two groups.
            prefixed = {
                nid
                for nid in walked
                if any(
                    label.startswith(prefix)
                    for label in by_id[nid].labels
                    for prefix in _LABEL_PREFIXES
                )
            }
            assert prefixed
            assert walked - prefixed


# ---------------------------------------------------------------------------
# Property 7: Timeout Fallback Chain
# ---------------------------------------------------------------------------

#: The exact key set :class:`~src.tools._bfs_walker.BFSResult` documents on
#: every node it reports. Asserted as an equality, not a superset: a
#: timed-out hop must not leave a node half-built (missing ``hop`` /
#: ``relType`` / ``direction``, which the walker attaches *after* the query
#: returns) nor carry a stray key a caller would then render.
_WALK_NODE_KEYS = frozenset(
    {"nid", "name", "path", "labels", "hop", "relType", "direction"}
)


def _run_walk(
    graph: _DeadEndGraph, plan: _TimeoutPlan
) -> tuple[TimeoutInjectingGraphDB, BFSResult]:
    """Walk ``graph`` with ``plan``'s timeouts injected.

    Fresh double per call so :pyattr:`TimeoutInjectingGraphDB.injected`
    and the call log describe exactly one walk -- Property 7 runs several
    plans over the same graph within one example.
    """
    walk_db = TimeoutInjectingGraphDB(
        nodes=graph.nodes, edges=graph.edges, plan=plan
    )
    result = asyncio.run(
        bfs_walk(
            walk_db,
            start_name=graph.anchor,
            direction=graph.direction,
            edge_types=list(graph.edge_types),
            max_depth=graph.max_depth,
            fan_out_limit=graph.fan_out_limit,
            result_limit=graph.result_limit,
            timeout_s=_TIMEOUT_S,
            scope_pred=graph.scope_pred,
            tenant=_TENANT_SENTINEL,
            label_scope_expanded=bool(graph.scope_pred),
        )
    )
    return walk_db, result


def _assert_walk_well_formed(
    result: BFSResult,
    walk_db: TimeoutInjectingGraphDB,
    graph: _DeadEndGraph,
    reachable: set[str],
) -> None:
    """Assert every :class:`BFSResult` invariant survives the timeouts.

    The "valid Degraded_Result" half of Property 7 at the walker level: a
    walk that lost queries must still return a *well-formed* result, not
    merely avoid raising. Applied to each of the test's runs -- the drawn
    plan and the pinned controls -- so the invariants are asserted under
    every injection pattern rather than only the drawn one.
    """
    assert isinstance(result, BFSResult)
    assert isinstance(result.truncated, bool)
    assert 0 <= result.hops_expanded <= graph.max_depth
    assert result.wall_clock_ms >= 0

    # The counters describe queries that really happened: every one the
    # walk counted is in the log (including the ones that timed out), and
    # the count matches the documented bound exactly rather than merely
    # staying under it (R2.2). A walker that kept expanding after a
    # timeout would break the equality, not the inequality.
    per_type = len(graph.edge_types)
    assert result.queries_issued == len(walk_db.call_log)
    assert result.queries_issued == 1 + per_type * result.hops_expanded

    walked = [node["nid"] for node in result.nodes]
    assert len(walked) == len(set(walked))
    assert len(walked) <= graph.result_limit
    # Partial results are a subset of the reachable set -- a lost hop can
    # only remove nodes, never invent one (R2.7).
    assert set(walked) <= reachable

    for node in result.nodes:
        assert set(node) == _WALK_NODE_KEYS
        assert isinstance(node["nid"], str)
        assert isinstance(node["labels"], list)
        assert node["relType"] in graph.edge_types
        assert node["direction"] == graph.direction
        # Provenance survives too. A node is only ever discovered at its
        # constructed depth: the layered graph joins consecutive layers
        # only, so a node missed because its hop timed out cannot turn up
        # later at a deeper hop -- its parents have already left the
        # frontier. A ``hop`` that drifted would mean the walk carried a
        # stale frontier past the failed expansion.
        assert node["hop"] == graph.depths[node["nid"]]
        assert 1 <= node["hop"] <= graph.reach_depth


@_SETTINGS
@given(graph=dead_end_graphs(), plan=timeout_plans())
def test_p7_timeout_fallback_chain(
    graph: _DeadEndGraph, plan: _TimeoutPlan
) -> None:
    """Feature: neptune-traversal-query-optimization, Property 7: For any
    traversal that times out during BFS execution, the tool SHALL catch the
    timeout and return a Degraded_Result (not an unhandled exception),
    preserving the existing bounded-graph-traversal contract.

    Validates: Requirements 3.3, 5.5

    The walker half. This is the middle link of the design's fallback
    chain -- the retry a timed-out single query is handed to -- so what it
    owes its caller is that *it* never raises and never returns a
    malformed partial view; the chain's last link (the tool's
    Degraded_Result) is asserted by
    :func:`test_p7_tool_fallback_chain_returns_degraded_result`.

    :func:`dead_end_graphs` is reused as the graph generator (rather than
    :func:`anchored_dag_graphs`) for three properties this test needs and
    would otherwise have to establish per example: the anchor always
    resolves, so an injected timeout has a walk to interrupt; the
    reachable set and each node's depth are known by construction, so the
    partial-result subset claim is checked against a constructed constant
    rather than a re-derivation of the walker's own traversal; and no
    other bound can bite (limits above the node count, scope admitting
    every node), which is what makes ``truncated`` a *biconditional* on
    the injected timeouts below instead of a one-way implication.
    """
    reachable = {nid for nid in graph.depths if nid != "n0"}
    per_type = len(graph.edge_types)

    # The property: no unhandled exception escapes, whatever the plan.
    walk_db, result = _run_walk(graph, plan)
    _assert_walk_well_formed(result, walk_db, graph, reachable)

    fired_anchor = [i for i, kind in walk_db.injected if kind == "anchor"]
    fired_hops = [i for i, kind in walk_db.injected if kind == "expansion"]

    # ``truncated`` is exactly "a hop was cut short". The reverse
    # direction is the one that matters and is the weaker of the two to
    # get right: a hop whose query timed out is absorbed as an *empty*
    # expansion, indistinguishable in the return value from an exhausted
    # branch, so a walker that did not thread that signal out would
    # present a truncated neighborhood as complete (R2.7, R5.5). The
    # forward direction holds because this graph's other bounds cannot
    # fire, so nothing else could have set the flag.
    assert result.truncated is bool(fired_hops)

    if fired_anchor:
        # Losing the anchor ends the walk before its hop loop: no nodes,
        # no hops, one query. Notably *not* truncated -- there is no
        # partial view to warn about, and the tool reads this shape as
        # "the fallback salvaged nothing" and moves to the last link of
        # the chain (`bfs_fallback_failed`).
        assert result.nodes == []
        assert result.hops_expanded == 0
        assert result.queries_issued == 1
        assert result.truncated is False
    elif not fired_hops:
        # The plan selected nothing this walk actually did (an ordinal
        # past its query count, or an absent edge type), so the walk is
        # unaffected and reaches the whole constructed graph.
        assert {node["nid"] for node in result.nodes} == reachable

    # Anti-vacuity. The assertions above are all satisfied by an example
    # whose plan never fired, and a plan drawn independently of the graph
    # often does not fire -- so the pinned plans below make every example
    # witness a timeout the walker actually had to survive, at each of
    # the two points where losing a query changes the outcome. The drawn
    # ``shape`` is carried into them so both exception forms reach these
    # paths.
    clean_db, clean = _run_walk(graph, _NO_TIMEOUTS)
    _assert_walk_well_formed(clean, clean_db, graph, reachable)
    assert clean_db.injected == []
    # Non-empty by construction (``reach_depth >= 1``), which is what
    # makes the empty results below a loss the injected timeout caused
    # rather than a graph that had nothing to find.
    assert {node["nid"] for node in clean.nodes} == reachable
    assert clean.nodes
    assert clean.truncated is False

    hops_dark = _TimeoutPlan(
        kinds=frozenset({"expansion"}), shape=plan.shape
    )
    hop_db, hop_result = _run_walk(graph, hops_dark)
    _assert_walk_well_formed(hop_result, hop_db, graph, reachable)
    # Every type's first hop timed out, so the walk salvages nothing --
    # and says so: one hop attempted, one query per type spent on it, and
    # the truncation flag set rather than an empty-but-complete result.
    assert [kind for _, kind in hop_db.injected] == (
        ["expansion"] * per_type
    )
    assert hop_result.nodes == []
    assert hop_result.truncated is True
    assert hop_result.hops_expanded == 1
    assert hop_result.queries_issued == 1 + per_type

    anchor_dark = _TimeoutPlan(
        kinds=frozenset({"anchor"}), shape=plan.shape
    )
    anchor_db, anchor_result = _run_walk(graph, anchor_dark)
    _assert_walk_well_formed(anchor_result, anchor_db, graph, reachable)
    assert [kind for _, kind in anchor_db.injected] == ["anchor"]
    assert anchor_result.nodes == []
    assert anchor_result.hops_expanded == 0
    assert anchor_result.queries_issued == 1
    assert anchor_result.truncated is False


#: Anchor name for the tool-level half. Any value works -- the double
#: answers by query shape, not by parameter -- so it is spelled
#: distinctively to make the assertions that look for it in the rendered
#: markdown unambiguous.
_TOOL_ANCHOR = "prop7_anchor"

#: Rendered heading of the one-hop Degraded_Result, i.e. the last link of
#: the fallback chain. Its presence is what distinguishes a degraded
#: response from a fallback-answered one.
_DEGRADED_HEAD = "## Direct Neighbors (one hop)"


def _run_tool(
    fail_kinds: frozenset[str],
    *,
    shape: str,
    degree: int,
    max_depth: int,
    chain_row: bool,
    hop_row: bool,
    onehop_row: bool,
) -> tuple[ToolTimeoutGraphDB, str]:
    """Drive ``trace_execution_path`` with ``fail_kinds`` timing out.

    Each of the four stages the fallback chain can reach is seeded with
    canned rows, so which stage answers is decided by ``fail_kinds``
    alone. The three row flags let a stage also be *empty* rather than
    failed, which is a different input to the chain: an empty walk
    salvages nothing and is routed onward exactly like a timed-out one
    (``bfs_fallback_failed`` treats the two alike, deliberately), and an
    empty one-hop probe is what produces the "no direct neighbors"
    degraded render.

    The tool body is called directly rather than through its FastMCP
    registration on purpose: the framework would catch an escaping
    exception and convert it into a tool-error result, which is exactly
    the outcome this property exists to rule out. Called here, an
    unhandled exception fails the test.

    ``include_callers`` / ``include_weights`` are off so the queries are
    the fallback chain's own. Both add sections whose queries sit outside
    the chain -- the callers query is unguarded and its timeout is the
    design's "propagated to the tool-level ``[ERROR]`` handler" row, not
    a fallback case -- so drawing them in would assert pre-existing
    behaviour under Property 7's name.
    """
    graph_db = ToolTimeoutGraphDB(
        canned_rows=[], fail_kinds=fail_kinds, shape=shape
    )
    graph_db.add_response(
        _TOOL_KIND_FRAGMENTS["entity"], [{"labels": ["Function"]}]
    )
    graph_db.add_response(
        _TOOL_KIND_FRAGMENTS["degree_anchor"], [{"nid": "degree_anchor0"}]
    )
    graph_db.add_response(
        _TOOL_KIND_FRAGMENTS["degree"], [{"deg": degree}]
    )
    graph_db.add_response(
        _TOOL_KIND_FRAGMENTS["chain"],
        [{"callee": "chain_callee", "file": "a.py", "depth": 1}]
        if chain_row
        else [],
    )
    graph_db.add_response(
        _TOOL_KIND_FRAGMENTS["walk_anchor"], [{"nid": "anchor0"}]
    )
    graph_db.add_response(
        _TOOL_KIND_FRAGMENTS["walk_hop"],
        [
            {
                "nid": "hop1",
                "name": "walk_callee",
                "path": "b.py",
                "labels": ["Function"],
            }
        ]
        if hop_row
        else [],
    )
    graph_db.add_response(
        _TOOL_KIND_FRAGMENTS["onehop"],
        [{"name": "one_hop_neighbor", "file": "c.py"}]
        if onehop_row
        else [],
    )

    data = MockUnifiedDataAccess(graph_db=graph_db)
    text = asyncio.run(
        code_analysis._tool_trace_execution_path(
            data,
            function_name=_TOOL_ANCHOR,
            file_path=None,
            max_depth=max_depth,
            include_callers=False,
            include_weights=False,
            token_budget=4000,
        )
    )
    return graph_db, text


def _assert_renderable(graph_db: ToolTimeoutGraphDB, text: str) -> None:
    """Assert the tool produced a well-formed response, whatever failed."""
    # A query shape the harness does not model would be answered with the
    # wrong rows (or none), quietly weakening every assertion below.
    assert graph_db.unclassified == []
    assert isinstance(text, str)
    assert text.endswith("\n")
    # ASCII-only tool output, per the repo convention -- a timeout notice
    # is still console/markdown output and must not smuggle in non-ASCII.
    assert text.isascii()


def _assert_one_hop_section(
    graph_db: ToolTimeoutGraphDB,
    text: str,
    fail_kinds: frozenset[str],
    onehop_row: bool,
) -> None:
    """Assert the Degraded_Result's neighbor section rendered correctly.

    The chain's terminal link. Its own query is allowed to time out too
    (the design's "timeout on one-hop -> empty result with timeout
    notice" step), in which case the section renders empty rather than
    propagating -- the notice above it is what carries the meaning.
    """
    assert _DEGRADED_HEAD in text
    assert "onehop" in graph_db.issued
    if "onehop" in fail_kinds or not onehop_row:
        assert "*No direct neighbors found.*" in text
    else:
        assert "one_hop_neighbor" in text


@_SETTINGS
@given(
    fail_kinds=tool_fail_kinds(),
    shape=st.sampled_from(_TIMEOUT_SHAPES),
    degree=st.integers(min_value=0, max_value=FAN_OUT_THRESHOLD),
    max_depth=st.integers(min_value=1, max_value=6),
    chain_row=st.booleans(),
    hop_row=st.booleans(),
    onehop_row=st.booleans(),
)
def test_p7_tool_fallback_chain_returns_degraded_result(
    fail_kinds: frozenset[str],
    shape: str,
    degree: int,
    max_depth: int,
    chain_row: bool,
    hop_row: bool,
    onehop_row: bool,
) -> None:
    """Feature: neptune-traversal-query-optimization, Property 7: For any
    traversal that times out during BFS execution, the tool SHALL catch the
    timeout and return a Degraded_Result (not an unhandled exception),
    preserving the existing bounded-graph-traversal contract.

    Validates: Requirements 3.3, 5.5

    The tool half, and the property's own subject: the claim is about
    what *the tool* returns, so it is asserted against a real tool
    (``trace_execution_path``, whose task-5.4 chain is single-query ->
    BFS_Walker -> one-hop Degraded_Result) driven end to end with
    timeouts injected into any subset of its stages.

    The degree is drawn strictly inside the non-hub band, because the hub
    branch returns a Degraded_Result *before* attempting any expansion --
    a true statement about the pre-existing degree gate, but one that
    would let an example satisfy this property without the fallback chain
    running at all.
    """
    graph_db, text = _run_tool(
        fail_kinds,
        shape=shape,
        degree=degree,
        max_depth=max_depth,
        chain_row=chain_row,
        hop_row=hop_row,
        onehop_row=onehop_row,
    )
    _assert_renderable(graph_db, text)

    if "entity" in fail_kinds:
        # The one stage whose timeout is not a fallback case: without the
        # anchor's classification the tool cannot pick an edge set, so the
        # design's Error Handling table routes it to the tool-level
        # `[ERROR]` render. Still a handled string -- which is the
        # property -- and the tool stops there rather than probing on.
        assert text.startswith("[ERROR] Error tracing execution path:")
        assert graph_db.issued == ["entity"]
        return

    assert not text.startswith("[ERROR]")
    assert text.startswith(f"# Execution Path Trace: {_TOOL_ANCHOR}")

    if "degree_anchor" in fail_kinds or "degree" in fail_kinds:
        # A failed probe is read as a hub (the pre-existing fail-safe), so
        # this is the Degraded_Result reached *without* a walk: neither
        # the single-query pattern nor the walker is attempted, which is
        # the design's "no BFS attempt for nodes with 100+ edges" arm
        # applied to an unmeasurable degree.
        #
        # Either of the probe's two stages losing its query produces that
        # same unmeasurable degree (task 2.6): the count cannot run
        # without the anchor ids, so a ``degree_anchor`` timeout short-
        # circuits to ``None`` exactly as a ``degree`` timeout does.
        assert degraded_notice(_TOOL_ANCHOR, None, FAN_OUT_THRESHOLD) in text
        assert "chain" not in graph_db.issued
        assert "walk_anchor" not in graph_db.issued
        if "degree_anchor" in fail_kinds:
            # The count is never attempted once resolution is lost.
            assert "degree" not in graph_db.issued
        _assert_one_hop_section(graph_db, text, fail_kinds, onehop_row)
        return

    if "chain" not in fail_kinds:
        # Control: nothing on the traversal path failed, so the ordinary
        # single-query response is returned unchanged -- no notice, no
        # walk, no R8.4 indicator (R5.1). Without this arm the property
        # would be satisfied by a tool that degraded unconditionally.
        assert "chain" in graph_db.issued
        assert "walk_anchor" not in graph_db.issued
        assert "onehop" not in graph_db.issued
        assert _DEGRADED_HEAD not in text
        assert code_analysis._timeout_notice(_TOOL_ANCHOR) not in text
        assert code_analysis._fallback_notice(_TOOL_ANCHOR) not in text
        assert "[optimized: BFS walker" not in text
        if chain_row:
            assert "chain_callee" in text
        return

    # The chain proper (R3.3): the single query timed out, so the walk is
    # attempted *before* any Degraded_Result -- the middle link exists.
    assert "walk_anchor" in graph_db.issued
    salvaged = (
        "walk_anchor" not in fail_kinds
        and "walk_hop" not in fail_kinds
        and hop_row
    )
    if salvaged:
        # The walk answered: its rows are rendered, labelled as a
        # fallback (not as a complete expansion), and the chain stops
        # there -- no one-hop probe, because there is nothing to degrade
        # to.
        assert code_analysis._fallback_notice(_TOOL_ANCHOR) in text
        assert "walk_callee" in text
        assert "[optimized: BFS walker" in text
        assert _DEGRADED_HEAD not in text
        assert "onehop" not in graph_db.issued
    else:
        # The walk salvaged nothing -- because its anchor resolution timed
        # out, because its hop timed out, or because it legitimately found
        # nothing. All three fall through to the pre-5.4 Degraded_Result,
        # which is the conservative choice: the single query that got here
        # *did* time out, so an empty walk is not evidence the
        # neighborhood is empty (R5.5).
        assert code_analysis._timeout_notice(_TOOL_ANCHOR) in text
        assert code_analysis._fallback_notice(_TOOL_ANCHOR) not in text
        _assert_one_hop_section(graph_db, text, fail_kinds, onehop_row)

    # Anti-vacuity. Most of the drawn subsets never reach the full chain
    # -- a third of them fail on `entity` and return early, and the empty
    # subset exercises no timeout at all -- so the two pinned runs below
    # make every example witness both terminal shapes of the chain with a
    # timeout that really fired. The drawn ``shape`` is carried through so
    # both exception forms reach them.
    pinned_bfs = frozenset({"chain"})
    bfs_db, bfs_text = _run_tool(
        pinned_bfs,
        shape=shape,
        degree=degree,
        max_depth=max_depth,
        chain_row=chain_row,
        hop_row=True,
        onehop_row=onehop_row,
    )
    _assert_renderable(bfs_db, bfs_text)
    assert bfs_db.injected == ["chain"]
    assert code_analysis._fallback_notice(_TOOL_ANCHOR) in bfs_text
    assert "walk_callee" in bfs_text
    assert _DEGRADED_HEAD not in bfs_text

    pinned_degraded = frozenset({"chain", "walk_hop"})
    deg_db, deg_text = _run_tool(
        pinned_degraded,
        shape=shape,
        degree=degree,
        max_depth=max_depth,
        chain_row=chain_row,
        hop_row=True,
        onehop_row=True,
    )
    _assert_renderable(deg_db, deg_text)
    assert "chain" in deg_db.injected
    assert "walk_hop" in deg_db.injected
    assert code_analysis._timeout_notice(_TOOL_ANCHOR) in deg_text
    assert _DEGRADED_HEAD in deg_text
    assert "one_hop_neighbor" in deg_text


# ---------------------------------------------------------------------------
# Property 8: Fan-Out Limit Bounds Per-Hop Results
# ---------------------------------------------------------------------------


def test_p8_fan_out_limit_default() -> None:
    """The documented Fan_Out_Limit default (R2.3, R6.1, R6.3).

    :func:`wide_fan_out_graphs` derives its own ceiling from the constant
    so the property stays correct under an env override -- but the design
    commits to 100 nodes per type per hop, and a silent change to that
    default would change how much of a hub's neighborhood every traversal
    reports without any property failing. Pinned here rather than left to
    the unit suite so the number this file's draws are bounded by is
    stated where they are drawn. Skipped when the override is actually in
    effect, since then the default is not the value under test.
    """
    if "MCP_BFS_FAN_OUT_LIMIT" in os.environ:
        pytest.skip("MCP_BFS_FAN_OUT_LIMIT override in effect")
    assert BFS_FAN_OUT_LIMIT == 100


def _run_wide_walk(
    graph: _WideGraph,
    *,
    fan_out_limit: int | None = None,
    result_limit: int | None = None,
) -> tuple[RowCountingGraphDB, BFSResult]:
    """Walk ``graph``, optionally overriding one of its two caps.

    Fresh double per call so the row-count log describes exactly one walk
    -- Property 8 runs several caps over the same graph within one
    example. The overrides are the two knobs the property varies: the
    Fan_Out_Limit itself (for the control and the R6.2 fallback runs) and
    the global result cap (to show which of the two set ``truncated``).
    """
    walk_db = RowCountingGraphDB(nodes=graph.nodes, edges=graph.edges)
    result = asyncio.run(
        bfs_walk(
            walk_db,
            start_name=graph.anchor,
            direction=graph.direction,
            edge_types=list(graph.edge_types),
            max_depth=graph.max_depth,
            fan_out_limit=(
                graph.fan_out_limit
                if fan_out_limit is None
                else fan_out_limit
            ),
            result_limit=(
                graph.result_limit if result_limit is None else result_limit
            ),
            timeout_s=_TIMEOUT_S,
            scope_pred=graph.scope_pred,
            tenant=_TENANT_SENTINEL,
            label_scope_expanded=bool(graph.scope_pred),
        )
    )
    return walk_db, result


def _emitted_limits(walk_db: RowCountingGraphDB) -> list[int]:
    """The ``LIMIT`` value carried by each expansion, in order.

    Read off the query *text* rather than off ``_Expansion.limit``, so an
    expansion emitted with no ``LIMIT`` at all is a missing entry here
    instead of silently becoming :data:`_REFERENCE_LIMIT` -- "never
    absent" is half of R2.3 and the half a parsed-with-default value
    cannot express.
    """
    limits: list[int] = []
    for cypher in walk_db.expansions():
        found = _LIMIT_RE.search(cypher)
        assert found is not None, f"expansion carries no LIMIT: {cypher!r}"
        limits.append(int(found.group("n")))
    return limits


@_SETTINGS
@given(graph=wide_fan_out_graphs())
def test_p8_fan_out_limit_bounds_per_hop_results(graph: _WideGraph) -> None:
    """Feature: neptune-traversal-query-optimization, Property 8: For any
    single BFS hop and relationship type, the number of nodes collected
    SHALL NOT exceed ``BFS_FAN_OUT_LIMIT``, ensuring that no individual
    expansion query returns an unbounded result set.

    Validates: Requirements 2.3

    Asserted at both levels the bound is observable at, because either
    alone is satisfiable without the other. The *query text* level (every
    expansion carries a ``LIMIT`` equal to the Fan_Out_Limit it was
    handed) is where R2.3 is literally spent -- it is what stops Neptune
    materializing an unbounded row set in the first place, which no
    row-count assertion can witness once the rows are already in
    Python. The *row* level (no per-hop, per-type result exceeds the
    limit) is what the caller actually receives, and it is what catches a
    ``LIMIT`` that is present but ignored -- emitted after a clause that
    voids it, or emitted per-branch on a shape that merges branches.

    :func:`wide_fan_out_graphs` supplies graphs whose every expansion has
    strictly more candidate neighbors than the drawn limit, so the bound
    is load-bearing on every example rather than on the lucky ones.
    """
    limit = graph.fan_out_limit
    per_type = len(graph.edge_types)
    walk_db, result = _run_wide_walk(graph)

    # (a) Query text. The bound is carried on every expansion, exactly
    # once, at exactly the value the caller passed -- never absent (which
    # would leave the expansion unbounded) and never larger (which would
    # bound it somewhere other than where the operator set it, R6.1/R6.2).
    limits = _emitted_limits(walk_db)
    assert limits
    assert set(limits) == {limit}
    assert len(limits) == per_type * graph.max_depth
    for cypher in walk_db.expansions():
        spec = _parse_expansion(cypher)
        assert spec is not None
        assert spec.limit == limit
        # Single-hop, single-type, in the requested direction: the shape
        # the LIMIT is meaningful on. A multi-type or variable-length
        # pattern carrying the same LIMIT would bound the merged row set
        # rather than the per-type per-hop one R2.3 speaks about.
        assert spec.depth == 1
        assert len(spec.types) == 1
        assert set(spec.types) <= set(graph.edge_types)
        assert spec.direction == graph.direction

    # (b) Rows, as the graph handed them back: no single expansion
    # returned more than its own LIMIT, nor more than the constant the
    # property is stated against.
    assert walk_db.returned
    for spec, count in walk_db.returned:
        assert count <= spec.limit
        assert count <= limit
        assert count <= BFS_FAN_OUT_LIMIT

    # ...and rows as the walker collected them, per hop per type. This is
    # the count Property 8 names. It is at most the query's row count (the
    # visited-set may drop a repeat), and here it is exactly the limit:
    # every fan is wider than the limit and no two fans share a node, so
    # each expansion saturates and contributes ``limit`` fresh nodes.
    per_hop_type: dict[tuple[int, str], int] = {}
    for node in result.nodes:
        key = (node["hop"], node["relType"])
        per_hop_type[key] = per_hop_type.get(key, 0) + 1
    assert per_hop_type
    for count in per_hop_type.values():
        assert count <= limit
        assert count <= BFS_FAN_OUT_LIMIT
    for hop in range(1, graph.max_depth + 1):
        for edge_type in graph.edge_types:
            assert per_hop_type[(hop, edge_type)] == limit

    # The aggregate the two bounds imply: the walk cannot return more
    # than ``limit`` nodes per type per hop no matter how wide the graph
    # is (R2.2's query bound times R2.3's row bound).
    assert len(result.nodes) == limit * per_type * graph.max_depth
    assert len(result.nodes) <= graph.result_limit
    assert result.hops_expanded == graph.max_depth
    assert result.queries_issued == 1 + per_type * graph.max_depth
    assert set(result.nodes[0]) == _WALK_NODE_KEYS
    walked = {node["nid"] for node in result.nodes}
    assert len(walked) == len(result.nodes)
    # Bounded, not invented: every node the capped walk reports is one
    # the unbounded graph really reaches at that hop (R2.7).
    assert walked <= graph.reachable()
    for node in result.nodes:
        assert node["hop"] == graph.depths[node["nid"]]
        assert node["direction"] == graph.direction

    # The interaction R2.3 and the design commit to: a hop that hit the
    # Fan_Out_Limit is a *partial* view of the anchor's neighborhood, so
    # the result says so rather than presenting the capped node set as
    # exhaustive. Attributable to the fan-out alone here -- the global cap
    # sits above the whole node count, the scope predicate admits every
    # node, and the timeout is far off.
    assert result.truncated is True

    # Anti-vacuity, part 1: the graph really did offer more than the
    # limit, computed from the graph itself rather than from the
    # generator's bookkeeping, so "count <= limit" is a cut and not an
    # accident of a narrow graph.
    for edge_type in graph.edge_types:
        spec = _Expansion(
            direction=graph.direction,
            types=(edge_type,),
            depth=1,
            limit=_REFERENCE_LIMIT,
        )
        available = set(
            _walk_endpoints(["n0"], walk_db.adjacency(spec), 1)
        )
        assert len(available) == graph.widths[edge_type]
        assert len(available) > limit
    assert all(count == limit for _, count in walk_db.returned)

    # Anti-vacuity, part 2: the control. Every assertion above is
    # satisfied by a walker that returns nothing, and ``truncated`` is
    # satisfied by one that sets the flag unconditionally. Re-walking the
    # same graph with a limit wider than any fan must therefore reach
    # strictly more nodes -- the whole constructed neighborhood -- and
    # must *not* report truncation, which is what shows the flag tracks
    # the fan-out rather than being hard-wired.
    generous = len(graph.nodes) + 1
    clean_db, clean = _run_wide_walk(graph, fan_out_limit=generous)
    assert set(_emitted_limits(clean_db)) == {generous}
    assert clean.truncated is False
    assert {node["nid"] for node in clean.nodes} == graph.reachable()
    assert len(clean.nodes) > len(result.nodes)

    # Anti-vacuity, part 3: the global result cap is a *different* bound
    # from the Fan_Out_Limit, and pinning it to 1 shows the per-hop LIMIT
    # is unchanged by it -- the expansions still carry the Fan_Out_Limit,
    # while the returned node list is cut to the global cap. Without this
    # the two bounds are indistinguishable on a graph where both would
    # produce a short result.
    capped_db, capped = _run_wide_walk(graph, result_limit=1)
    assert set(_emitted_limits(capped_db)) == {limit}
    assert len(capped.nodes) == 1
    assert capped.truncated is True

    # R6.2, at the walker's own boundary: a Fan_Out_Limit that arrives
    # non-positive falls back to the module default rather than disabling
    # the bound it was meant to enforce. Asserted on the emitted text,
    # since that is where "no LIMIT at all" would show up.
    fallback_db, fallback = _run_wide_walk(graph, fan_out_limit=0)
    assert set(_emitted_limits(fallback_db)) == {BFS_FAN_OUT_LIMIT}
    for _, count in fallback_db.returned:
        assert count <= BFS_FAN_OUT_LIMIT
    if BFS_FAN_OUT_LIMIT > len(graph.nodes):
        # The default is wider than this graph, so it behaves like the
        # control above. Guarded rather than assumed: an env override
        # could put the default below a fan's width, and then truncation
        # is the correct outcome instead of a regression.
        assert fallback.truncated is False
        assert {
            node["nid"] for node in fallback.nodes
        } == graph.reachable()
