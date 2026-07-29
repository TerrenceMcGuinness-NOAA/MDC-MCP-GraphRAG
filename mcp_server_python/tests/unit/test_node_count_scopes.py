"""Graph node-count scope annotations + whole-graph count.

graph-node-count-scope-documentation (SDD Phase 73). Exercises
`_render_graph_status_block` scope labelling and the `all_tenants` whole-graph
count, and `_whole_graph_node_count`, without a live graph.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.tools import semantic_search as ss

pytestmark = pytest.mark.unit


class _Graph:
    """Graph double: health reports 100 nodes/200 rels; the unfiltered
    whole-graph query returns ``whole``; label/rel queries return 0/none."""

    def __init__(self, whole: int = 900):
        self._whole = whole
        self.saw_whole_query = False

    async def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "nodes": 100, "relationships": 200}

    async def query(self, cypher: str, tenant: Any = None, **_kw: Any):
        if "count(n) AS total" in cypher and "WHERE" not in cypher and ":" not in cypher:
            self.saw_whole_query = True
            return [{"total": self._whole}]
        if "AS count" in cypher:
            return [{"count": 0}]
        return []


class _Tenant:
    def __init__(self, tid: str, prefix: str):
        self.tenant_id = tid
        self.index_prefix = prefix
        self.label_prefix = prefix.upper()


def _render(graph: Any, tenant: Any = None, all_tenants: bool = False) -> str:
    lines = asyncio.run(
        ss._render_graph_status_block(graph, tenant=tenant, all_tenants=all_tenants)
    )
    return "\n".join(lines)


# ── R2.2 tenant-scope annotation ─────────────────────────────────────────


def test_total_nodes_default_labeled_tenant_scope() -> None:
    text = _render(_Graph(), tenant=None)
    assert "- **Total Nodes (tenant scope):** 100" in text
    assert "all tenants" not in text


def test_total_nodes_labeled_with_tenant_id() -> None:
    text = _render(_Graph(), tenant=_Tenant("gw_v17", "gw_v17_"))
    assert "- **Total Nodes (tenant gw_v17):** 100" in text


# ── R4 whole-graph (all_tenants) ─────────────────────────────────────────


def test_all_tenants_adds_whole_graph_line() -> None:
    graph = _Graph(whole=900)
    text = _render(graph, tenant=None, all_tenants=True)
    assert "- **Total Nodes (tenant scope):** 100" in text
    assert "- **Total Nodes (all tenants, all labels):** 900" in text
    assert graph.saw_whole_query is True
    # Whole-graph count >= tenant-scoped count (R4 success criterion).
    assert 900 >= 100


def test_default_has_no_whole_graph_line() -> None:
    text = _render(_Graph(), tenant=None, all_tenants=False)
    assert "all tenants" not in text


def test_whole_graph_count_helper_handles_query_failure() -> None:
    class _Boom:
        async def query(self, *_a: Any, **_k: Any):
            raise RuntimeError("neptune timeout")

    assert asyncio.run(ss._whole_graph_node_count(_Boom())) is None


def test_all_tenants_renders_placeholder_on_failure() -> None:
    class _G(_Graph):
        async def query(self, cypher: str, tenant: Any = None, **_kw: Any):
            if "count(n) AS total" in cypher and ":" not in cypher:
                raise RuntimeError("neptune full-scan timeout")
            return await super().query(cypher, tenant, **_kw)

    text = _render(_G(), tenant=None, all_tenants=True)
    assert "- **Total Nodes (all tenants, all labels):** [unavailable]" in text
