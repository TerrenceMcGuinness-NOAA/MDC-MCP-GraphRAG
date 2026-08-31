"""Application-side BFS traversal helpers for the graph tools.

Home of the two query-shape optimizations introduced by the
``neptune-traversal-query-optimization`` spec:

1. **UNION_ALL_Decomposition** (:func:`resolve_anchor_ids`) — resolves a
   traversal's Anchor_Node by ``name``/``path`` using two index-seekable
   ``MATCH`` branches joined by ``UNION ALL`` instead of one
   index-defeating ``OR`` disjunction on an unlabelled node (R1.1, R1.3).
2. **BFS_Walker** (:func:`bfs_walk`, built on :func:`_expand_one_hop`
   and reported as a :class:`BFSResult`) — replaces a single multi-type
   variable-length pattern (``[:A|B|C*1..N]``) with iterative, per-type,
   single-hop queries merged in Python, so a moderately connected anchor
   no longer triggers combinatorial path enumeration (R2.1, R2.2).

Both live here rather than in
:mod:`src.tools._traversal_bounds` because that module is deliberately
import-light (``os`` + ``logging`` only) and shared by every tool; the
walker needs ``asyncio``/``time`` and issues its own queries. The
tunables it reads (:data:`~src.tools._traversal_bounds.
BFS_ACTIVATION_THRESHOLD`, :data:`~src.tools._traversal_bounds.
BFS_FAN_OUT_LIMIT`) stay in ``_traversal_bounds`` alongside the existing
traversal bounds (R6.1), as does the ``_use_bfs`` strategy selector.

This module takes the graph adapter as a parameter and imports no tool
module, so the traversal tools (``graph_rag``, ``code_analysis``) can
import it without a cycle.

Output is ASCII-only. Callers pass the tenant object and the
``_scope_and(...)`` fragment through, so tenant isolation is applied to
every query issued here exactly as it is on the tools' own queries
(R4.1, R4.4).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from src.tools._traversal_bounds import (
    BFS_ACTIVATION_THRESHOLD,
    BFS_FAN_OUT_LIMIT,
    RESULT_LIMIT,
)

log = logging.getLogger(__name__)

#: A relationship type cannot be parameterized in openCypher, so
#: :func:`_expand_one_hop` interpolates it into the pattern. Each type is
#: validated against this identifier shape first, so a caller cannot
#: smuggle pattern or clause syntax into the emitted query.
_EDGE_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: The node variable inside a Label_Scope_Predicate appears exactly once,
#: as the argument of ``labels(...)`` -- the comprehension's ``__lbl``
#: binding is local to the fragment and the prefix literals are
#: constrained to ``^([A-Z][A-Z0-9_]*_)?$`` by
#: :func:`src.config.tenants._validate_prefix`, so they can carry neither
#: parentheses nor a variable reference. Retargeting the fragment from the
#: caller's variable onto the expansion target is therefore exactly this
#: substitution, whichever variable the caller built it for (R4.4).
_LABELS_CALL_RE = re.compile(r"labels\(\s*[A-Za-z_][A-Za-z0-9_]*\s*\)")

__all__ = [
    "BFSResult",
    "bfs_fallback_failed",
    "bfs_optimized_header",
    "bfs_walk",
    "insert_bfs_header",
    "resolve_anchor_ids",
]


def _retarget_scope_pred(fragment: str, var: str) -> str:
    """Rewrite a Label_Scope_Predicate to apply to ``var`` (R4.1, R4.4).

    :func:`src.tenancy.resolver.tenant_label_predicate` references its
    node variable only as ``labels(<var>)``, so pointing the fragment at
    a different variable is a rewrite of that one call. Matching on
    ``labels(...)`` rather than on the caller's literal variable name
    means a fragment built for any variable (``_scope_and("n")``,
    ``_scope_and("a")``, ``_scope_and("source")``) retargets correctly;
    a name-specific rewrite would silently no-op on the others and emit
    a predicate over a variable the expansion pattern never binds, which
    Neptune rejects -- and because :func:`_expand_one_hop` absorbs query
    failures, that would surface as an empty hop rather than an error
    (Property 2 would then be violated invisibly).

    An empty fragment stays empty, so the caller emits no filter. A
    non-empty fragment carrying no ``labels(...)`` call cannot have come
    from ``tenant_label_predicate``; it is dropped with a log line rather
    than emitted against an unbound variable.
    """
    if not fragment:
        return ""
    retargeted, subs = _LABELS_CALL_RE.subn(f"labels({var})", fragment)
    if subs == 0:
        log.info(
            "[bfs-walker] scope predicate %r carries no labels(...) call "
            "-- cannot retarget onto %s, omitting it from this hop",
            fragment,
            var,
        )
        return ""
    return retargeted


@dataclass(frozen=True, slots=True)
class BFSResult:
    """Output of one BFS_Walker walk (R2.1).

    Immutable so a caller cannot mutate a walk's outcome while
    formatting it; ``nodes`` is a plain ``list`` (built once by
    ``bfs_walk`` and handed over) rather than a ``tuple`` because it is
    the tools' render input and is never edited after construction.

    Attributes
    ----------
    nodes
        The discovered nodes, in discovery order (hop 1 first). Each
        entry is a dict carrying:

        - ``name`` (``str``) -- the node's ``name`` property.
        - ``path`` (``str | None``) -- its ``path`` property, absent on
          nodes that carry no path (e.g. Fortran subroutines).
        - ``labels`` (``list[str]``) -- ``labels(b)`` as returned by the
          graph, tenant-prefixed for a non-default tenant.
        - ``hop`` (``int``) -- the depth at which the node was first
          discovered (1-based; the Anchor_Node itself is not listed).
        - ``relType`` (``str``) -- the relationship type of the edge
          that led here.
        - ``direction`` (``str``) -- ``"forward"`` or ``"reverse"``, the
          direction the edge was traversed in.

        The Anchor_Node is excluded, and the visited-set guarantees a
        node appears at most once even in a cyclic graph (R2.4).
    hops_expanded
        The depth actually reached, which is at most the requested
        ``max_depth`` and lower when the walk terminated early on a hop
        that produced no new nodes (R2.5).
    queries_issued
        Total graph calls made, including the anchor resolution. Bounded
        by ``1 + |edge_types| * hops_expanded`` (R2.2); reported for the
        observability logging in R8.2.
    wall_clock_ms
        Total elapsed time of the walk in milliseconds.
    truncated
        ``True`` when the walk returned a partial view of what the
        bounds would otherwise allow -- a hop hit the Fan_Out_Limit
        (R2.3), the global result cap was reached, or the overall
        Statement_Timeout expired mid-walk. Callers surface this as a
        Degraded_Result notice rather than presenting the node set as
        exhaustive.
    """

    nodes: list[dict[str, Any]]
    hops_expanded: int
    queries_issued: int
    wall_clock_ms: int
    truncated: bool


def bfs_fallback_failed(*salvaged: Sequence[Any]) -> bool:
    """True when a BFS_Walker fallback salvaged nothing (R3.3, R5.5).

    The decision function for the middle link of the design's fallback
    chain (``single-query -> BFS -> Degraded_Result``): a traversal tool
    whose single-query pattern timed out retries the expansion as a walk,
    and consults this to decide whether the retry answered or whether it
    should fall through to the existing one-hop Degraded_Result.

    Accepts one or more collections so a caller can pass either the raw
    :attr:`BFSResult.nodes` or the rows it already folded them into
    (``find_callers_callees`` salvages two lists from two walks). The
    fallback is treated as failed when *every* collection is empty.

    Why emptiness is the signal
    ---------------------------
    :func:`bfs_walk` never raises for a failed hop -- :func:`_expand_one_hop`
    is its error boundary -- and an expiry of its overall
    :func:`asyncio.wait_for` is reported as
    :attr:`BFSResult.truncated`, not as an exception. So "the BFS also
    timed out" surfaces as *no nodes plus* ``truncated``, and that shape
    returns ``True`` here.

    This widens the test to *no nodes*, ``truncated`` or not, because the
    remaining shape (no nodes, not truncated) is not distinguishable from
    it in the return value: :func:`resolve_anchor_ids` absorbs an
    anchor-resolution timeout into an empty id list, which yields a walk
    that never entered its hop loop and was therefore never marked
    truncated. Widening is also the conservative direction --  the single
    query that got us here *did* time out, so the tool has no basis for
    asserting the neighborhood is empty. Falling through keeps the
    ``bounded-graph-traversal`` [8.36.0] contract that a timeout renders a
    timeout notice, instead of converting an unknown into a rendered
    "no callees found" (R5.5).

    A fallback that found *any* node is accepted, ``truncated`` and all:
    the caller renders those nodes alongside its own partial-view notice,
    which is strictly more information than the one-hop Degraded_Result
    the walk replaces.
    """
    return not any(salvaged)


def bfs_optimized_header(*results: BFSResult | None) -> str:
    """Render the ``[optimized: ...]`` response indicator (R8.4).

    The caller-visible counterpart of the R8.1/R8.2 log lines: it puts
    the same counters in the tool's markdown response so a caller can
    tell a BFS_Walker result from a single-query result without server
    log access. The format is the design's ("Appendix: Observability")::

        [optimized: BFS walker, 3 hops, 42 nodes, 847ms]

    An empty string means "no indicator" -- returned when no walk ran, so
    the single-query path renders byte-identically to its pre-8.2 output
    (R8.4, R5.1). Anything else is a walk, *including a walk that found
    nothing*: the indicator answers "which strategy produced this
    response", which is as true of a zero-node walk as of a fruitful one,
    and it is the shape an operator correlating a thin response against
    the COMPLETED log line needs to see.

    Lives here, next to :class:`BFSResult`, rather than in either tool
    module so both render an identical string from identical counters --
    the requirement is that callers can *recognize* the indicator, which
    two independent format sites would erode.

    Aggregating several walks
    ------------------------
    Accepts varargs because a single response can be produced by more
    than one walk: ``find_callers_callees`` runs one per direction and
    its ``cross_language`` section can add a third. Those collapse into
    *one* aggregate line rather than one line per walk, because R8.4 asks
    for "a brief note in the response header" -- a per-walk breakdown
    would put three lines above a response whose useful signal is the
    single fact that the decomposed strategy ran. The aggregation is
    chosen so each number keeps the meaning it has for a single walk:

    * ``hops`` -- the **maximum** ``hops_expanded``, i.e. how deep the
      response's expansion actually reached. Summing would report a
      depth no walk ever visited.
    * ``nodes`` -- the **sum** of node counts, the total the walks
      contributed to the response. (Two walks may rediscover the same
      node; the visited-set is per-walk, so a caller reading this as
      "distinct nodes" would be slightly over-counted. It is reported as
      contributed rows because that is what the response renders.)
    * ``ms`` -- the **sum** of ``wall_clock_ms``, the wall clock the
      caller actually paid, matching the walks' sequential execution.

    ``None`` entries are ignored, so a call site can pass an optional
    walk without a conditional.
    """
    walks = [r for r in results if r is not None]
    if not walks:
        return ""
    hops = max(r.hops_expanded for r in walks)
    nodes = sum(len(r.nodes) for r in walks)
    wall_ms = sum(r.wall_clock_ms for r in walks)
    return (
        f"[optimized: BFS walker, {hops} hops, {nodes} nodes, {wall_ms}ms]"
    )


def insert_bfs_header(lines: list[str], *results: BFSResult | None) -> None:
    """Insert the R8.4 indicator into a tool's response lines, in place.

    Placement is *after* the ``# Title`` line, not before it, so the
    response still opens on its markdown heading -- a rendered document
    whose first line is a bracketed annotation reads as noise, and any
    consumer keying off the leading ``# `` (the existing
    ``test_get_code_context_*`` assertions do) keeps working. The
    indicator therefore lands on line 2, separated from the body by a
    blank line::

        # Data Flow Trace: `setuprad`
        [optimized: BFS walker, 1 hops, 12 nodes, 34ms]

        ## Outgoing Relationships (12)

    Centralized here, alongside :func:`bfs_optimized_header`, so all four
    Traversal_Tools agree on *where* the indicator goes as well as how it
    is spelled; the alternative was the same three-line insert copied
    into two tool modules.

    Does nothing when no walk ran (:func:`bfs_optimized_header` returns
    ``""``) or when ``lines`` is empty, so a single-query response and a
    degraded response are untouched (R8.4).
    """
    header = bfs_optimized_header(*results)
    if not header or not lines:
        return
    # Keep exactly one blank line between the indicator and the body:
    # every caller's lines[1] is already the title's trailing blank, so
    # only a body that starts immediately after the title needs one added.
    lines.insert(1, header)
    if len(lines) > 2 and lines[2] != "":
        lines.insert(2, "")


def _is_timeout_error(exc: BaseException) -> bool:
    """True when ``exc`` is a traversal statement-timeout.

    Matches the ``NeptuneAdapterError`` raised by
    :pymeth:`NeptuneAdapter.query` on ``asyncio.wait_for`` expiry (its
    message contains ``statement timeout``) and a bare
    :pyexc:`asyncio.TimeoutError`. Mirrors the identically-named helpers
    in :mod:`src.tools.graph_rag` and :mod:`src.tools.code_analysis`;
    duplicated rather than imported so this module stays free of any
    tool-module import (no cycle once those modules import the walker).
    """
    if isinstance(exc, asyncio.TimeoutError):
        return True
    return "statement timeout" in str(exc).lower()


def _positive_int(value: Any, default: int) -> int:
    """Coerce ``value`` to a positive int, else return ``default``.

    Mirrors the defensive coercion in
    :func:`src.tools._traversal_bounds._int_env`: a bound that arrives
    non-positive or unparseable falls back to the conservative default
    rather than disabling the bound it was meant to enforce (R6.2).
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def _valid_edge_types(edge_types: Sequence[str] | None) -> list[str]:
    """Return the usable relationship types, deduplicated, in order.

    Types are filtered against :data:`_EDGE_TYPE_RE` here as well as in
    :func:`_expand_one_hop` so that ``BFSResult.queries_issued`` counts
    only queries that are actually issued: a refused type never reaches
    the graph, so counting it would overstate the walk's cost to the
    R8.2 observability logging. Duplicates are dropped for the same
    reason -- expanding one type twice per hop is redundant work whose
    second copy the visited-set would discard anyway.
    """
    seen: set[str] = set()
    out: list[str] = []
    for et in edge_types or ():
        if not _EDGE_TYPE_RE.match(et or ""):
            log.info(
                "[bfs-walker] dropping unsupported edge type %r from the "
                "walk's edge set",
                et,
            )
            continue
        if et in seen:
            continue
        seen.add(et)
        out.append(et)
    return out


async def resolve_anchor_ids(
    graph_db: Any,
    name: str,
    *,
    scope_pred: str,
    tenant: Any,
    timeout_s: float,
    var: str = "n",
    error_sink: list[str] | None = None,
) -> list[str]:
    """Resolve Anchor_Node ids for ``name`` via UNION_ALL_Decomposition.

    Replaces the index-defeating Anchor_Predicate
    ``(n.name = $name OR n.path = $name)`` with two single-property
    equality branches joined by ``UNION ALL``::

        MATCH (n) WHERE n.name = $name <scope_pred> RETURN id(n) AS nid
        UNION ALL
        MATCH (n) WHERE n.path = $name <scope_pred> RETURN id(n) AS nid

    A disjunction across two different properties of an unlabelled node
    cannot be satisfied from an index, so Neptune evaluates the predicate
    against every node; split into single-property equalities, each
    branch is an indexable lookup. The same rewrite in
    :func:`src.tools.semantic_search._enrich_with_graph_counts` took a
    live-Neptune query from 28.57s to 0.06s on 2026-08-27 (R1.1, R1.5).

    The two branches are set-equivalent to the original ``OR`` form once
    deduplicated: a node matching on both ``name`` and ``path`` appears
    in both branches (``UNION ALL`` does not dedupe), so ids are folded
    through a ``set`` here (R1.3, Property 1).

    Parameters
    ----------
    graph_db
        The graph adapter (must accept ``tenant=`` and ``timeout=``).
    name
        The Anchor_Node's ``name`` or ``path`` value.
    scope_pred
        The ``_scope_and(<var>)`` fragment (`` AND <predicate>`` or ``""``
        for the default ``gw`` tenant), applied to *both* branches so the
        resolution is tenant-scoped exactly like the traversal it seeds
        (R1.4, R4.4). It must be built for the same variable as ``var``.
    tenant
        The active tenant object, forwarded so the adapter applies
        label-prefix rewriting.
    timeout_s
        Statement_Timeout (seconds) carried on the query (R1.4).
    var
        The node variable to bind in both branches, default ``"n"``. It
        exists so a caller whose surrounding query already names its
        anchor something else can reuse this resolution *without*
        retargeting its Label_Scope_Predicate:
        :func:`src.tools._traversal_bounds.anchor_degree` counts edges on
        ``a`` and its callers hand it ``_scope_and("a")``, so it passes
        ``var="a"`` and the fragment drops straight in. The variable also
        reaches the projection (``RETURN id(a) AS nid``), which keeps a
        probe's resolution distinguishable from a walk's in a call log.
        Validated against :data:`_EDGE_TYPE_RE` -- it is interpolated into
        the pattern, so it must be a bare identifier -- and falls back to
        ``"n"`` otherwise.
    error_sink
        Optional list this function appends a short reason (``"timeout"``
        or ``"error"``) to when the query fails, following the
        ``timeout_sink`` convention of :func:`_expand_one_hop`. It is the
        one signal the return value cannot carry: a failed resolution and
        a resolution that matched nothing are both ``[]``, which is the
        right default for the walker (it cannot traverse either way) but
        *not* for the degree probe, whose contract distinguishes "degree
        0" from "degree unmeasurable" (R1.5 fail-safe). Left ``None`` by
        callers that do not need the distinction, so their behaviour is
        unchanged.

    Returns
    -------
    list[str]
        Deduplicated node ids, in no guaranteed order. Empty when
        ``name`` is blank, when nothing matches, or when the query fails
        or times out -- callers cannot traverse without an anchor and
        render their own notice rather than raising (R1.4, Property 7).
    """
    if not name:
        return []

    node_var = var if _EDGE_TYPE_RE.match(var or "") else "n"
    if node_var != var:
        log.info(
            "[bfs-walker] refusing node variable %r in anchor resolution "
            "-- falling back to 'n'",
            var,
        )

    cypher = (
        f"MATCH ({node_var}) WHERE {node_var}.name = $name"
        f"{scope_pred} "
        f"RETURN id({node_var}) AS nid "
        "UNION ALL "
        f"MATCH ({node_var}) WHERE {node_var}.path = $name"
        f"{scope_pred} "
        f"RETURN id({node_var}) AS nid"
    )

    try:
        rows = await graph_db.query(
            cypher, {"name": name}, tenant=tenant, timeout=timeout_s
        )
    except Exception as exc:  # noqa: BLE001 - anchor loss is graceful
        if _is_timeout_error(exc):
            if error_sink is not None:
                error_sink.append("timeout")
            log.info(
                "[bfs-walker] anchor resolution timed out for anchor=%s "
                "-- returning no anchor ids",
                name,
            )
        else:
            if error_sink is not None:
                error_sink.append("error")
            log.info(
                "[bfs-walker] anchor resolution failed for anchor=%s: %s "
                "-- returning no anchor ids",
                name,
                exc,
            )
        return []

    # UNION ALL emits one row per matching branch, so a node matched by
    # both name and path arrives twice; the set folds it back to one id.
    ids: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        nid = row.get("nid")
        if nid is None or nid == "":
            continue
        ids.add(str(nid))
    return list(ids)


async def _expand_one_hop(
    graph_db: Any,
    frontier_ids: Iterable[str],
    edge_type: str,
    direction: str,
    fan_out_limit: int,
    scope_pred_on_target: str,
    tenant: Any,
    timeout_s: float,
    *,
    timeout_sink: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Expand one frontier by one hop over one edge type (R2.2, R2.3).

    The single query primitive the BFS_Walker iterates. It is
    deliberately the simplest shape Neptune can plan -- one relationship
    type, one hop, an ``id()`` seek on the frontier, and a ``LIMIT`` --
    so a hop can never become the combinatorial Path_Materialization
    that a multi-type variable-length pattern
    (``[:A|B|C*1..N]``) produces::

        MATCH (a)-[:CALLS]->(b)
        WHERE id(a) IN $ids <scope_pred_on_b>
        RETURN DISTINCT id(b) AS nid, b.name AS name, b.path AS path,
               labels(b) AS labels
        LIMIT <fan_out_limit>

    Issuing ``|edge_types|`` of these per depth level, instead of one
    pattern spanning all of them, keeps the per-query cost flat in the
    depth budget: the caller pays ``|edge_types| * depth`` cheap seeks
    rather than one query that enumerates every type-interleaved path
    (R2.1, R2.2).

    Tenant scoping is applied to the *target* node ``b``, not just the
    anchor, so nodes belonging to another tenant are excluded before they
    enter the frontier rather than after (R2.6, R4.1). The caller passes
    the fragment built for its anchor variable (i.e. ``_scope_and("n")``)
    and :func:`_retarget_scope_pred` points it at ``b``; an empty
    fragment emits no filter at all (R4.3, R4.4).

    Note that the default ``gw`` tenant does *not* reach that empty case
    in a catalog declaring other tenants:
    :func:`~src.tenancy.resolver.tenant_label_predicate` returns the
    *exclusion* form for an empty label prefix (``size([... STARTS WITH
    '<other tenant>' ...]) = 0``), which admits every unprefixed baseline
    node and rejects only another tenant's prefixed nodes. Applying it to
    ``b`` is therefore what R4.3 intends -- it cannot exclude the default
    tenant's own nodes, and omitting it would let a prefixed neighbor of
    a baseline anchor into a ``gw`` walk. The fragment is genuinely
    ``""`` only when no scoping is expressible at all: no active tenant
    context, or a catalog in which no tenant declares a label prefix.

    Errors are absorbed here rather than raised: this function is the
    BFS_Walker's error boundary, so a hop that times out or fails
    contributes no nodes instead of aborting the whole walk. That keeps
    the walk's result a subset of what the original pattern would reach
    (R2.7, Property 2) and keeps the tool contract free of unhandled
    exceptions (Property 7). Because a swallowed timeout is
    indistinguishable from an empty expansion in the return value, the
    optional ``timeout_sink`` gives the caller the one signal it cannot
    otherwise recover: :func:`bfs_walk` passes a shared list and reports
    ``BFSResult.truncated`` when any hop deposited an entry in it, so a
    hop that timed out is never presented as an exhausted branch.

    Parameters
    ----------
    graph_db
        The graph adapter (must accept ``tenant=`` and ``timeout=``).
    frontier_ids
        Node ids to expand from, as returned by
        :func:`resolve_anchor_ids` or a previous hop. Blank / ``None``
        entries are dropped; an empty frontier short-circuits with no
        query issued.
    edge_type
        A single relationship type (e.g. ``"CALLS"``). Interpolated into
        the pattern, so it must match :data:`_EDGE_TYPE_RE`; anything
        else (including a pipe-joined set) is refused with an empty
        result rather than emitted.
    direction
        ``"reverse"`` traverses incoming edges
        (``MATCH (b)-[:TYPE]->(a)``); any other value traverses outgoing
        edges (``MATCH (a)-[:TYPE]->(b)``).
    fan_out_limit
        Fan_Out_Limit for this hop -- the ``LIMIT`` carried on the query,
        so no single expansion returns an unbounded row set (R2.3,
        Property 8). Non-positive / unparseable values fall back to
        :data:`~src.tools._traversal_bounds.BFS_FAN_OUT_LIMIT`.
    scope_pred_on_target
        The ``_scope_and(<var>)`` fragment (`` AND <predicate>`` or
        ``""``), retargeted onto ``b`` here by
        :func:`_retarget_scope_pred` regardless of which variable the
        caller built it for. Pass ``""`` to skip target scoping.
    tenant
        The active tenant object, forwarded so the adapter applies
        label-prefix rewriting.
    timeout_s
        Statement_Timeout (seconds) carried on the query.
    timeout_sink
        Optional list this hop appends ``edge_type`` to when its query
        times out, so a caller can distinguish "this branch is exhausted"
        from "this branch was cut short". Left ``None`` by callers that
        do not need the distinction.

    Returns
    -------
    list[dict[str, Any]]
        One dict per discovered neighbor, each carrying ``nid`` (``str``,
        so it compares cleanly against the caller's visited-set),
        ``name``, ``path``, and ``labels`` (always a ``list``). The
        BFS_Walker adds ``hop`` / ``relType`` / ``direction`` before
        these reach :class:`BFSResult`. Empty when the frontier is empty,
        the edge type is refused, nothing matches, or the query fails or
        times out.
    """
    ids = [
        str(fid)
        for fid in (frontier_ids or ())
        if fid is not None and fid != ""
    ]
    if not ids:
        return []

    if not _EDGE_TYPE_RE.match(edge_type or ""):
        log.info(
            "[bfs-walker] refusing to expand unsupported edge type %r "
            "-- returning no nodes for this hop",
            edge_type,
        )
        return []

    try:
        limit = int(fan_out_limit)
    except (TypeError, ValueError):
        limit = BFS_FAN_OUT_LIMIT
    if limit < 1:
        limit = BFS_FAN_OUT_LIMIT

    if direction == "reverse":
        pattern = f"MATCH (b)-[:{edge_type}]->(a)"
    else:
        pattern = f"MATCH (a)-[:{edge_type}]->(b)"

    # The caller builds the fragment for its own anchor variable (``n``);
    # retarget it at the expansion target so it filters ``labels(b)``.
    scope_on_target = _retarget_scope_pred(scope_pred_on_target or "", "b")

    cypher = (
        pattern
        + " WHERE id(a) IN $ids"
        + scope_on_target
        + " RETURN DISTINCT id(b) AS nid, b.name AS name,"
        " b.path AS path, labels(b) AS labels"
        f" LIMIT {limit}"
    )

    try:
        rows = await graph_db.query(
            cypher, {"ids": ids}, tenant=tenant, timeout=timeout_s
        )
    except Exception as exc:  # noqa: BLE001 - hop loss is graceful
        if _is_timeout_error(exc):
            if timeout_sink is not None:
                timeout_sink.append(edge_type)
            log.info(
                "[bfs-walker] hop expansion timed out (edge=%s "
                "direction=%s frontier=%d) -- returning no nodes for "
                "this hop",
                edge_type,
                direction,
                len(ids),
            )
        else:
            log.info(
                "[bfs-walker] hop expansion failed (edge=%s direction=%s "
                "frontier=%d): %s -- returning no nodes for this hop",
                edge_type,
                direction,
                len(ids),
                exc,
            )
        return []

    nodes: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        nid = row.get("nid")
        if nid is None or nid == "":
            continue
        labels = row.get("labels")
        nodes.append(
            {
                "nid": str(nid),
                "name": row.get("name"),
                "path": row.get("path"),
                "labels": (
                    list(labels)
                    if isinstance(labels, (list, tuple))
                    else []
                ),
            }
        )
    return nodes


async def bfs_walk(
    graph_db: Any,
    *,
    start_name: str,
    direction: str,
    edge_types: Sequence[str],
    max_depth: int,
    fan_out_limit: int,
    result_limit: int,
    timeout_s: float,
    scope_pred: str,
    tenant: Any,
    label_scope_expanded: bool,
    tool: str | None = None,
    degree: int | None = None,
) -> BFSResult:
    """Walk the graph breadth-first, one type and one hop at a time.

    The BFS_Walker (R2.1). Replaces a single Multi_Type_Expansion
    pattern such as ``[:SOURCES|INVOKES|EXECUTES|CALLS|USES|DEFINES*1..5]``
    -- whose cost grows combinatorially in the depth budget because
    Neptune enumerates every type-interleaved path before applying the
    row limit -- with ``|edge_types|`` cheap single-hop seeks per depth
    level (:func:`_expand_one_hop`), merged in Python. Total graph calls
    are therefore ``1 + |edge_types| * hops_expanded`` and grow
    *linearly* in depth (R2.2).

    The walk is bounded four independent ways, so no input can make it
    unbounded:

    * **Depth** -- at most ``max_depth`` hops (the caller passes the
      already-clamped :func:`~src.tools._traversal_bounds.
      effective_depth` value).
    * **Per-hop breadth** -- ``fan_out_limit`` rows per type per hop, as
      a ``LIMIT`` on each expansion query (R2.3).
    * **Total rows** -- ``result_limit`` nodes overall, after which the
      walk stops.
    * **Wall clock** -- the whole walk, anchor resolution included, runs
      inside a single :func:`asyncio.wait_for` bounded by ``timeout_s``.

    Two behaviours make the walk cheap on real graphs. A visited-set
    carried across hops means a node discovered at depth N is never
    re-expanded at depth N+1, so a cycle terminates instead of looping
    and each node is reported once (R2.4). And a hop that yields no
    unvisited nodes empties the frontier, which ends the walk on the next
    iteration regardless of remaining depth budget (R2.5).

    Together with the Fan_Out_Limit this makes the result a *subset* of
    what the original pattern would return -- possibly fewer paths, never
    a node the pattern could not reach (R2.7, Property 2).

    Notes
    -----
    **The Anchor_Node is not included in** ``nodes``. The design
    pseudocode fetches hop-0 seed metadata via a ``_fetch_node_metadata``
    call; this implementation follows the :class:`BFSResult` contract
    instead (``hop`` is 1-based, anchor excluded), because every caller
    integrating the walker in task 5.x already knows and renders its own
    anchor -- the tools take ``start``/``function_name``/``from_symbol``
    from the request. Re-fetching it would spend one extra query per walk
    to recover a value the caller supplied, and would put a hop-0 row in
    ``nodes`` that each caller then has to filter back out of its
    neighbor rendering.

    Failure is absorbed rather than raised. :func:`_expand_one_hop` is
    the error boundary and already returns ``[]`` for a failed hop, so
    the :func:`asyncio.gather` here rarely sees an exception; it is
    nonetheless run with ``return_exceptions=True`` and any exception
    that does surface is logged and flagged as truncation rather than
    re-raised (the design pseudocode re-raises non-timeout errors; this
    deviates so a tool call always yields a renderable Degraded_Result,
    per Property 7). Cancellation is unaffected: the outer
    ``wait_for``'s :pyexc:`asyncio.CancelledError` is a
    :pyexc:`BaseException` and propagates through both layers.

    Parameters
    ----------
    graph_db
        The graph adapter (must accept ``tenant=`` and ``timeout=``).
    start_name
        The Anchor_Node's ``name`` or ``path``, resolved to ids via
        :func:`resolve_anchor_ids` (R1.1).
    direction
        ``"forward"`` to follow outgoing edges, ``"reverse"`` for
        incoming. Applied uniformly to every hop; a caller wanting both
        (e.g. ``find_callers_callees``) runs two walks.
    edge_types
        Relationship types to expand, one query each per hop. Entries
        that are not plain identifiers are dropped (with a log line), and
        duplicates are folded, so ``queries_issued`` reflects real cost.
    max_depth
        Maximum hops to expand. Non-positive / unparseable falls back to
        ``1``.
    fan_out_limit
        Fan_Out_Limit per type per hop (R2.3). Non-positive /
        unparseable falls back to :data:`~src.tools._traversal_bounds.
        BFS_FAN_OUT_LIMIT`.
    result_limit
        Global cap on returned nodes. Non-positive / unparseable falls
        back to :data:`~src.tools._traversal_bounds.RESULT_LIMIT`.
    timeout_s
        Bound for the walk overall *and* for each individual query
        inside it.
    scope_pred
        The ``_scope_and("n")`` fragment, applied to the anchor
        resolution always (R1.4) and to each expansion's target node
        when ``label_scope_expanded`` is set (R4.1).
    tenant
        The active tenant object, forwarded so the adapter applies
        label-prefix rewriting.
    label_scope_expanded
        ``True`` to scope expanded nodes by tenant label as well as the
        anchor (R4.1); ``False`` to scope only the anchor (R4.3).

        Every current caller passes ``bool(scope_pred)``, which makes the
        flag redundant with ``scope_pred`` itself -- an empty fragment
        already emits no filter, and a non-empty one is always wanted on
        the target. It is kept as an explicit parameter because it is the
        design's contract for this behaviour and the knob a caller needs
        to opt a walk out of target scoping without also un-scoping the
        anchor resolution, which stays scoped either way (R1.4).
    tool
        Name of the Traversal_Tool this walk serves, for the R8.1
        activation log line. Optional so an internal or test caller can
        omit it; it then reports ``tool=unknown``. It is threaded from the
        call site rather than inferred here because several helpers are
        reachable from more than one tool (``_cross_language_nodes`` runs
        for both ``trace_full_execution_chain`` and
        ``find_callers_callees``), so the walker cannot name its caller
        without guessing.
    degree
        The anchor's measured Node_Degree that selected this walk, for
        the same log line (R8.1). ``None`` means the degree was not
        probed for this walk's edge set -- the value ``_use_bfs`` reads as
        unknown -- and is logged as ``degree=unknown`` rather than as a
        number the operator could mistake for a real measurement.

    Returns
    -------
    BFSResult
        The discovered nodes plus the counters
        (``hops_expanded`` / ``queries_issued`` / ``wall_clock_ms``) the
        R8.2 activation logging and R8.4 response header report, and
        ``truncated`` when any bound cut the walk short. An unresolvable
        anchor yields an empty, non-truncated result: the caller renders
        its own "not found" notice, exactly as it does for the
        single-query path.
    """
    t0 = time.monotonic()

    depth_budget = _positive_int(max_depth, 1)
    row_cap = _positive_int(result_limit, RESULT_LIMIT)
    hop_limit = _positive_int(fan_out_limit, BFS_FAN_OUT_LIMIT)
    types = _valid_edge_types(edge_types)
    # R4.1/R4.3/R4.4: the target-node predicate is the anchor's own
    # predicate, retargeted onto ``b`` inside _expand_one_hop. Callers
    # pass label_scope_expanded=bool(scope_pred), so this is normally
    # just ``scope_pred``; the flag exists to opt a walk out of target
    # scoping while the anchor resolution below stays scoped (R1.4).
    scope_on_target = scope_pred if label_scope_expanded else ""

    # R8.1 activation log. Emitted here rather than in each strategy
    # selector so every BFS activation is logged exactly once, in one
    # format, including the fallback-chain activations that no selector
    # decided (a timed-out single query retried as a walk).
    #
    # R8.3: only the anchor name, the counters, and the bounds are
    # logged. The tenant object, the Label_Scope_Predicate fragment, and
    # the node payloads are deliberately absent -- ``tenant`` can carry
    # deployment configuration and the payloads are the full result the
    # requirement excludes.
    tool_name = tool or "unknown"
    anchor_label = start_name or "unknown"
    log.info(
        "[bfs-walker] ACTIVATED tool=%s anchor=%s degree=%s threshold=%d "
        "direction=%s max_depth=%d",
        tool_name,
        anchor_label,
        "unknown" if degree is None else degree,
        BFS_ACTIVATION_THRESHOLD,
        direction,
        depth_budget,
    )

    # Mutated by the inner walk through ``nonlocal`` / in place, so a
    # partial walk survives the outer wait_for cancelling it and is
    # still reported below (R2.7 partial results on timeout).
    nodes: list[dict[str, Any]] = []
    hop_timeouts: list[str] = []
    hops_expanded = 0
    queries_issued = 0
    truncated = False

    async def _walk() -> None:
        nonlocal hops_expanded, queries_issued, truncated

        # Step 1 -- anchor resolution (UNION_ALL_Decomposition, R1.1).
        anchor_ids = await resolve_anchor_ids(
            graph_db,
            start_name,
            scope_pred=scope_pred,
            tenant=tenant,
            timeout_s=timeout_s,
        )
        queries_issued += 1
        if not anchor_ids:
            return

        # Step 2 -- seed the visited-set with the anchor so the walk can
        # never come back to it, and the frontier with the same ids.
        visited: set[str] = set(anchor_ids)
        frontier: list[str] = list(anchor_ids)

        # Step 3 -- expand one depth level at a time.
        for depth in range(1, depth_budget + 1):
            if not frontier or not types:
                break  # Early termination (R2.5).

            hop_results = await asyncio.gather(
                *(
                    _expand_one_hop(
                        graph_db,
                        frontier,
                        edge_type,
                        direction,
                        hop_limit,
                        scope_on_target,
                        tenant,
                        timeout_s,
                        timeout_sink=hop_timeouts,
                    )
                    for edge_type in types
                ),
                return_exceptions=True,
            )
            queries_issued += len(types)
            hops_expanded = depth

            next_frontier: list[str] = []
            for edge_type, result in zip(types, hop_results):
                if isinstance(result, BaseException):
                    # _expand_one_hop absorbs its own failures, so this
                    # is a defensive branch; degrade, never propagate.
                    log.info(
                        "[bfs-walker] hop %d over %s raised past the hop "
                        "error boundary: %s -- treating as truncated",
                        depth,
                        edge_type,
                        result,
                    )
                    truncated = True
                    continue
                if len(result) >= hop_limit:
                    # Hit the Fan_Out_Limit, so this branch is a partial
                    # view of the anchor's neighborhood (R2.3).
                    truncated = True
                for node in result:
                    nid = node.get("nid")
                    if not nid or nid in visited:
                        continue  # Cycle prevention (R2.4).
                    visited.add(nid)
                    next_frontier.append(nid)
                    node["hop"] = depth
                    node["relType"] = edge_type
                    node["direction"] = direction
                    nodes.append(node)

            frontier = next_frontier

            if len(nodes) >= row_cap:
                truncated = True
                del nodes[row_cap:]
                break

    try:
        await asyncio.wait_for(_walk(), timeout=timeout_s)
    except asyncio.TimeoutError:
        # The walk is cancelled mid-flight; whatever it had already
        # merged into ``nodes`` is a valid partial result (R2.7).
        truncated = True
        log.info(
            "[bfs-walker] walk exceeded its %.1fs wall-clock bound "
            "(anchor=%s direction=%s hops=%d nodes=%d) -- returning "
            "partial results",
            timeout_s,
            start_name,
            direction,
            hops_expanded,
            len(nodes),
        )

    # A hop query that timed out was absorbed by _expand_one_hop as an
    # empty expansion; the sink is the only signal that the branch was
    # cut short rather than exhausted.
    if hop_timeouts:
        truncated = True

    if len(nodes) > row_cap:
        del nodes[row_cap:]

    wall_ms = int((time.monotonic() - t0) * 1000)

    # R8.2 completion log, emitted unconditionally -- including the
    # zero-node walk. An anchor that resolved to nothing, or a hop that
    # found nothing, is exactly the case an operator tuning
    # BFS_ACTIVATION_THRESHOLD needs to see: it is the walk that spent
    # queries and wall clock for no rows. Logging it only on success
    # would hide the cheapest signal that the threshold is too low.
    log.info(
        "[bfs-walker] COMPLETED tool=%s anchor=%s nodes=%d queries=%d "
        "hops=%d wall_ms=%d",
        tool_name,
        anchor_label,
        len(nodes),
        queries_issued,
        hops_expanded,
        wall_ms,
    )

    return BFSResult(
        nodes=nodes,
        hops_expanded=hops_expanded,
        queries_issued=queries_issued,
        wall_clock_ms=wall_ms,
        truncated=truncated,
    )
