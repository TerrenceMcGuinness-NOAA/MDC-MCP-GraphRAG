"""Phase 83 regression tests — type-tolerant ``name`` CONTAINS predicate.

Phase 82 proved the COTS benchmark's 7 graph-query failures came from a
heterogeneous ``name`` property (321,520 strings, 452 integers, 4 lists).
Neo4j Community aborts the whole query with ``CypherTypeError`` when
``toLower`` / ``toString`` meets a non-string value; Neptune tolerates it.

Phase 83 branches the predicate on ``DB_BACKEND`` via
:func:`src.graphrag.ggsr_traversal._name_contains_predicate`:

* **cots (Neo4j)** — ``<var>.name IS :: STRING AND toLower(<var>.name)
  CONTAINS toLower($<param>)``. The ``IS :: STRING`` guard is evaluated
  first and ``AND`` short-circuits, so ``toLower`` never sees a Long or a
  StringArray.
* **aws (Neptune)** — ``toLower(toString(<var>.name)) CONTAINS
  toLower($<param>)`` (unchanged, no regression).

These tests pin the emitted Cypher at all four call sites for both
backends and assert the old single-form pattern is gone on the Neo4j path.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from src.graphrag.ggsr_traversal import GGSRTraversal, _name_contains_predicate
from src.tools import graph_rag, semantic_search
from src.sdd.session_manager import SessionManager
from tests.conftest import MockGraphDB, MockUnifiedDataAccess

pytestmark = pytest.mark.unit


# ── env helper ──────────────────────────────────────────────────────────────


@pytest.fixture
def restore_backend():
    """Save/restore ``DB_BACKEND`` so per-test overrides don't leak."""
    prev = os.environ.get("DB_BACKEND")
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("DB_BACKEND", None)
        else:
            os.environ["DB_BACKEND"] = prev


def _set_backend(value: str) -> None:
    os.environ["DB_BACKEND"] = value


# ── helper unit tests ───────────────────────────────────────────────────────


def test_predicate_aws_uses_tostring(restore_backend):
    _set_backend("aws")
    pred = _name_contains_predicate("n", "baseName")
    assert pred == "toLower(toString(n.name)) CONTAINS toLower($baseName)"
    assert "IS :: STRING" not in pred


def test_predicate_cots_uses_type_guard(restore_backend):
    _set_backend("cots")
    pred = _name_contains_predicate("n", "baseName")
    assert pred == (
        "n.name IS :: STRING AND toLower(n.name) CONTAINS toLower($baseName)"
    )
    # The Neo4j path must NOT carry toString() — that is exactly the form
    # that throws on the 4 list-named nodes (Phase 82 live evidence).
    assert "toString(" not in pred


def test_predicate_legacy_alias_maps_to_cots(restore_backend):
    _set_backend("legacy")  # Phase 63a deprecation alias → cots
    pred = _name_contains_predicate("hop1", "topic")
    assert pred == (
        "hop1.name IS :: STRING AND toLower(hop1.name) CONTAINS toLower($topic)"
    )


def test_predicate_var_and_param_substitution(restore_backend):
    _set_backend("aws")
    assert (
        _name_contains_predicate("x", "q")
        == "toLower(toString(x.name)) CONTAINS toLower($q)"
    )


# ── site 1 & 2 — GGSR 1-hop / 2-hop ─────────────────────────────────────────


async def _emit_ggsr_cypher(*, hops: int, backend: str) -> str:
    _set_backend(backend)
    graph = MockGraphDB()
    graph.canned_rows = []
    trav = GGSRTraversal(graph)
    await trav._multi_hop_query("forecast", hops=hops, limit=5)
    cyphers = [e[1][0] for e in graph.call_log if e[0] == "query"]
    assert cyphers, "no query was emitted"
    return cyphers[0]


@pytest.mark.parametrize("hops", [1, 2])
async def test_ggsr_cots_emits_type_guard(hops, restore_backend):
    cypher = await _emit_ggsr_cypher(hops=hops, backend="cots")
    assert "n.name IS :: STRING AND toLower(n.name) CONTAINS toLower($baseName)" in cypher
    assert "toString(n.name)" not in cypher


@pytest.mark.parametrize("hops", [1, 2])
async def test_ggsr_aws_emits_tostring(hops, restore_backend):
    cypher = await _emit_ggsr_cypher(hops=hops, backend="aws")
    assert "toLower(toString(n.name)) CONTAINS toLower($baseName)" in cypher
    assert "IS :: STRING" not in cypher


# ── site 3 — graph_rag fuzzy-symbol fallback ────────────────────────────────


async def _emit_fuzzy_cypher(*, backend: str) -> str:
    _set_backend(backend)
    data = MockUnifiedDataAccess()
    data.graph_db.canned_rows = []  # force node lookup → empty → fuzzy path
    session = SessionManager(None)
    await graph_rag._tool_get_code_context(
        data,
        session,
        symbol="nonexistent_symbol",
        depth=1,
        include_community=False,
        token_budget=0,  # skip the GGSR engine; exercise only node+fuzzy
    )
    cyphers = [e[1][0] for e in data.graph_db.call_log if e[0] == "query"]
    fuzzy = [c for c in cyphers if "CONTAINS toLower($name)" in c]
    assert fuzzy, f"fuzzy-fallback query not emitted; saw: {cyphers}"
    return fuzzy[0]


async def test_fuzzy_fallback_cots_emits_type_guard(restore_backend):
    cypher = await _emit_fuzzy_cypher(backend="cots")
    assert "n.name IS :: STRING AND toLower(n.name) CONTAINS toLower($name)" in cypher
    assert "toString(n.name)" not in cypher


async def test_fuzzy_fallback_aws_emits_tostring(restore_backend):
    cypher = await _emit_fuzzy_cypher(backend="aws")
    assert "toLower(toString(n.name)) CONTAINS toLower($name)" in cypher
    assert "IS :: STRING" not in cypher


def test_fuzzy_fallback_has_no_is_testing_branch():
    """The Phase 82 ``is_testing`` Cypher divergence is removed (Step 3).

    The fuzzy fallback must emit one backend-derived predicate, never a
    test-vs-production fork keyed on ``pytest`` being importable.
    """
    import inspect

    src = inspect.getsource(graph_rag._tool_get_code_context)
    assert "is_testing" not in src
    assert "PYTEST_CURRENT_TEST" not in src


# ── site 4 — semantic_search topic lookup ───────────────────────────────────


async def _emit_topic_cypher(*, backend: str) -> str:
    _set_backend(backend)
    data = MockUnifiedDataAccess()
    await semantic_search._tool_explain_with_context(
        data,
        topic="forecast",
        context_type="general",
        detail_level="standard",
    )
    cyphers = [e[1][0] for e in data.graph_db.call_log if e[0] == "query"]
    topic = [c for c in cyphers if "CONTAINS toLower($topic)" in c]
    assert topic, f"topic query not emitted; saw: {cyphers}"
    return topic[0]


async def test_topic_lookup_cots_emits_type_guard(restore_backend):
    cypher = await _emit_topic_cypher(backend="cots")
    assert "n.name IS :: STRING AND toLower(n.name) CONTAINS toLower($topic)" in cypher
    assert "toString(n.name)" not in cypher


async def test_topic_lookup_aws_emits_tostring(restore_backend):
    cypher = await _emit_topic_cypher(backend="aws")
    assert "toLower(toString(n.name)) CONTAINS toLower($topic)" in cypher
    assert "IS :: STRING" not in cypher
