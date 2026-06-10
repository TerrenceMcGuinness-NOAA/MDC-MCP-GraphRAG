"""Bounded-graph-traversal guards — shared constants and helpers.

Single home for the traversal tunables (Requirement 6.1) and the helper
functions the graph-traversal tools (``trace_full_execution_chain``,
``trace_execution_path``, ``find_callers_callees``, ``trace_data_flow``,
and the circular-dependency check in ``find_dependencies``) use to bound
a query before it issues a variable-length path expansion against
Neptune.

Three guards stack, cheapest first (see ``bounded-graph-traversal``
design):

1. **Pre-flight degree check** — :func:`anchor_degree` runs a single-hop
   ``count`` over the traversal's edge set so the caller knows the
   anchor node's degree *before* any variable-length expansion. Over
   :data:`FAN_OUT_THRESHOLD` (or probe failure) → caller returns a
   one-hop Degraded_Result instead of expanding.
2. **Effective depth cap** — :func:`effective_depth` clamps the caller's
   ``max_depth`` to a conservative per-tool ceiling so the emitted
   pattern is always an explicit ``*1..N`` bound (never unbounded).
3. **Statement-timeout backstop** — every traversal query carries
   :data:`TIMEOUT_S` to :pymeth:`NeptuneAdapter.query`; on timeout the
   tool returns a Degraded_Result rather than raising.

The degree check is the primary fix: it prevents the combinatorial
Path_Materialization from ever starting on a hub node such as
``JGLOBAL_FORECAST`` (500+ edges). The depth cap and timeout are
defense-in-depth for moderately-connected nodes and unforeseen shapes.

This module is import-light (only :mod:`os`, :mod:`logging`) so it can be
imported by every tool module without pulling in adapters.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


# ── env helpers ──────────────────────────────────────────────────────────


def _int_env(name: str, default: int) -> int:
    """Return a positive int env override for ``name`` or ``default``.

    Non-positive, missing, or unparseable values fall back to the
    conservative ``default`` (R6.2).
    """
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    """Return a positive float env override for ``name`` or ``default``.

    Non-positive, missing, or unparseable values fall back to the
    conservative ``default`` (R6.2).
    """
    try:
        v = float(os.environ.get(name, ""))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


# ── tunables (R6.1, R6.2, R6.3) ─────────────────────────────────────────
# One location, env-overridable, conservative defaults that are safe on
# the current ``gw`` baseline (where JGLOBAL_FORECAST and similar hubs
# exist).

#: Node_Degree above which a traversal switches from full variable-length
#: expansion to a one-hop Degraded_Result.
FAN_OUT_THRESHOLD: int = _int_env("MCP_TRAVERSAL_FANOUT_THRESHOLD", 100)

#: Effective_Depth ceiling for the cross-language full-chain traversal
#: (``trace_full_execution_chain`` / ``_cross_language_nodes``); reduced
#: from the historical 10.
FULL_CHAIN_DEPTH: int = _int_env("MCP_TRAVERSAL_FULLCHAIN_DEPTH", 5)

#: Effective_Depth ceiling for the single-edge-type call-chain traversal
#: (``trace_execution_path`` / ``find_callers_callees`` / ``_call_chain``).
CALL_CHAIN_DEPTH: int = _int_env("MCP_TRAVERSAL_CALLCHAIN_DEPTH", 4)

#: Effective_Depth ceiling for ``trace_data_flow``'s shortestPath.
DATA_FLOW_DEPTH: int = _int_env("MCP_TRAVERSAL_DATAFLOW_DEPTH", 5)

#: Maximum number of rows any variable-length / one-hop traversal query
#: returns.
RESULT_LIMIT: int = _int_env("MCP_TRAVERSAL_RESULT_LIMIT", 200)

#: Per-query Statement_Timeout (seconds) passed to the Neptune adapter on
#: traversal queries.
TIMEOUT_S: float = _float_env("MCP_TRAVERSAL_TIMEOUT_S", 30.0)


# ── helpers ──────────────────────────────────────────────────────────────


def effective_depth(requested: Any, ceiling: int) -> tuple[int, bool]:
    """Clamp ``requested`` depth into ``[1, ceiling]``.

    Returns ``(depth, clamped)`` where ``depth`` is the value to embed in
    the ``*1..N`` pattern and ``clamped`` is ``True`` when the caller
    asked for *more* than the ceiling (so the response can note the
    traversal was bounded, R2.3). Negative / zero / unparseable requests
    are raised to ``1`` but do not set ``clamped`` (no meaningful request
    was reduced).

    Guarantees ``1 <= depth <= max(1, ceiling)`` for any input, so the
    emitted pattern is always an explicit, finite bound (R2.1, R2.4,
    Property 1).
    """
    safe_ceiling = ceiling if ceiling >= 1 else 1
    try:
        r = int(requested)
    except (TypeError, ValueError):
        return safe_ceiling, False
    depth = max(1, min(r, safe_ceiling))
    clamped = r > safe_ceiling
    return depth, clamped


def degraded_notice(anchor: str, degree: int | None, threshold: int) -> str:
    """Render the standard Degraded_Result notice block (R4.2, R4.3).

    ASCII-only (R8.2). Includes the anchor name, the measured degree
    (or a clear "could not be measured" note when the probe failed /
    timed out), and the fan-out threshold that triggered the
    degradation, so the guard that fired is discoverable from the tool
    output alone (R8.3).
    """
    if degree is None:
        measured = (
            "its degree could not be measured (the degree probe failed or "
            f"timed out), so it is treated as a hub (fan-out threshold "
            f"{threshold})"
        )
    else:
        measured = (
            f"its measured degree {degree} exceeds the fan-out threshold "
            f"{threshold}"
        )
    return (
        f"[INFO] Highly connected node `{anchor}`: {measured}. "
        "To avoid an unbounded path expansion, this traversal was limited "
        "to the node's direct (one-hop) neighbors. Re-run against a less "
        "connected node, or narrow the query, for a full traversal."
    )


def truncation_marker(shown: int, total: int) -> str:
    """Return a ``[truncated: N of M shown]`` marker, or ``""`` (R4.5).

    Emitted only when ``total`` exceeds ``shown``.
    """
    if total > shown:
        return f"[truncated: {shown} of {total} shown]"
    return ""


async def anchor_degree(
    graph_db: Any,
    name: str,
    rel_types: str,
    tenant: Any,
    scope_pred: str = "",
) -> int | None:
    """Single-hop degree probe for ``name`` over ``rel_types`` (R1.1, R1.4).

    Runs a count-only, single-hop query — never a variable-length
    pattern — so counting a hub node's edges cannot itself become an
    expensive path materialization::

        MATCH (a)-[r:<rel_types>]-(x)
        WHERE (a.name = $name OR a.path = $name) <scope_pred>
        RETURN count(r) AS deg

    Parameters
    ----------
    graph_db
        The graph adapter (must accept ``tenant=`` and ``timeout=``).
    name
        The anchor node's name/path.
    rel_types
        Pipe-joined edge set the caller will traverse (e.g. ``"CALLS"``
        or ``"SOURCES|INVOKES|EXECUTES"``), so the degree reflects the
        relevant fan-out.
    tenant
        The active tenant object, forwarded so the adapter applies
        label-prefix rewriting (Property 5).
    scope_pred
        The ``_scope_and(...)`` fragment (`` AND <predicate>`` or ``""``)
        so the probe is tenant-scoped exactly like the real traversal
        (Property 5).

    Returns
    -------
    int | None
        The measured degree on success (``0`` when the node has no
        matching edges or the probe returns no ``deg`` value — a
        non-hub, so the expansion proceeds unchanged). ``None`` only when
        the probe raises or times out: callers treat ``None`` as a hub
        and fall back to the Degraded_Result (R1.5 fail-safe).

    The direction-agnostic ``-[r]-`` probe counts both incident
    directions (conservative; see design Open Question 3).
    """
    cypher = (
        f"MATCH (a)-[r:{rel_types}]-(x) "
        "WHERE (a.name = $name OR a.path = $name)"
        f"{scope_pred} "
        "RETURN count(r) AS deg"
    )
    try:
        rows = await graph_db.query(
            cypher, {"name": name}, tenant=tenant, timeout=TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001 - fail safe toward hub (R1.5)
        log.info(
            "[traversal-bounds] degree probe failed for anchor=%s rels=%s: %s "
            "-- treating as hub",
            name,
            rel_types,
            exc,
        )
        return None
    if not rows:
        return 0
    raw = rows[0].get("deg")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def is_hub(degree: int | None, threshold: int = FAN_OUT_THRESHOLD) -> bool:
    """Return ``True`` when ``degree`` is a hub (None → fail-safe hub).

    A node is a hub when the probe failed (``degree is None``, R1.5) or
    its degree exceeds ``threshold`` (R1.2). Degree ``<= threshold``
    (including ``0``) is a non-hub and proceeds with expansion (R1.3).
    """
    return degree is None or degree > threshold


__all__ = [
    "FAN_OUT_THRESHOLD",
    "FULL_CHAIN_DEPTH",
    "CALL_CHAIN_DEPTH",
    "DATA_FLOW_DEPTH",
    "RESULT_LIMIT",
    "TIMEOUT_S",
    "effective_depth",
    "degraded_notice",
    "truncation_marker",
    "anchor_degree",
    "is_hub",
]
