"""Unit tests for the Phase B2 (re-shipped in Phase C-2b) data layer:

* :pymod:`src.data.neptune_adapter` — GraphDBProtocol implementation
* :pymod:`src.data.unified_data_access` — facade
* :pymod:`src.data.backend_selector` — factory

These modules were originally specified in Phase B2 (Tasks 2.4 + 2.6)
but were not actually committed at the time. The Phase C-1 live-parity
run surfaced the gap (every InvokeAgentRuntime call against the
Python staging runtime fell through to ``_create_data_access``'s
``ModuleNotFoundError`` branch). The C-2b hot-fix lands the missing
modules; this test file documents the intended contract and prevents
the same gap from recurring.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.config.environment import ServerConfig
from src.data import backend_selector, neptune_adapter, unified_data_access
from src.data.backend_selector import (
    UnsupportedBackendError,
    create_data_access,
)
from src.data.neptune_adapter import NeptuneAdapter, NeptuneAdapterError
from src.data.unified_data_access import UnifiedDataAccess

pytestmark = pytest.mark.unit


# ── NeptuneAdapter ────────────────────────────────────────────────────────


class _FakeNeptuneSession:
    """Sync session mimicking ``aws_backend.NeptuneSession``."""

    def __init__(self, run_results, run_calls):
        self._run_results = run_results
        self._run_calls = run_calls

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def run(self, query, **params):
        self._run_calls.append((query, params))
        # Fake the NeptuneResult iterable contract: list of dict.
        nxt = self._run_results.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return iter([dict(row) for row in nxt])


class _FakeNeptuneDriver:
    """Sync driver mimicking ``aws_backend.NeptuneHTTPAdapter``."""

    def __init__(self, run_results=None):
        self.run_results = list(run_results or [])
        self.run_calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def session(self):
        return _FakeNeptuneSession(self.run_results, self.run_calls)

    def close(self):
        self.closed = True


@pytest.fixture()
def fake_driver(monkeypatch: pytest.MonkeyPatch):
    """Replace ``NeptuneHTTPAdapter`` with the fake driver for tests."""
    fake = _FakeNeptuneDriver()

    def _factory(endpoint, region):
        fake.endpoint = endpoint
        fake.region = region
        return fake

    monkeypatch.setattr(
        "src.data.aws_backend.NeptuneHTTPAdapter", _factory
    )
    return fake


def test_neptune_adapter_requires_endpoint() -> None:
    with pytest.raises(ValueError, match="endpoint is required"):
        NeptuneAdapter("")


# ── tenant label-prefix rewriting (relationship-type safety) ──────────────


def _rewrite_tenant(prefix: str):
    """Build a Tenant with the given label_prefix for rewrite tests."""
    from src.config.tenants import Tenant

    return Tenant(
        tenant_id="t", repo_ref="R", branch="b",
        index_prefix="", label_prefix=prefix,
        workflow_subdir="d", lifecycle="production",
    )


def test_rewrite_does_not_prefix_relationship_types() -> None:
    """Relationship types inside [...] must NOT be prefixed — only node labels.

    Regression for the bug where ``MATCH (s:File)-[r:CALLS]->()`` was
    rewritten to ``(s:GW_V17_File)-[r:GW_V17_CALLS]->()``; since Neptune
    only prefixes node labels (not relationship types), the mangled
    ``:GW_V17_CALLS`` matched nothing and counts came back 0.
    """
    adapter = NeptuneAdapter.__new__(NeptuneAdapter)
    tenant = _rewrite_tenant("GW_V17_")

    cypher = "MATCH (s:File)-[r:CALLS]->() RETURN count(r) AS count"
    out = adapter._rewrite_cypher(cypher, tenant)

    assert ":GW_V17_File" in out          # node label IS prefixed
    assert ":CALLS" in out                # rel type preserved
    assert ":GW_V17_CALLS" not in out     # rel type NOT prefixed


def test_rewrite_handles_multi_type_relationships() -> None:
    """Multiple rel types in one bracket (``[:A|B|C]``) are all preserved."""
    adapter = NeptuneAdapter.__new__(NeptuneAdapter)
    tenant = _rewrite_tenant("GW_V17_")

    cypher = (
        "MATCH (f:File)-[:IMPORTS|USES|SOURCES|INVOKES]->(m:Module) "
        "RETURN m.name AS name"
    )
    out = adapter._rewrite_cypher(cypher, tenant)

    assert ":GW_V17_File" in out
    assert ":GW_V17_Module" in out
    # The relationship bracket content is preserved verbatim.
    assert "[:IMPORTS|USES|SOURCES|INVOKES]" in out
    for rel in ("IMPORTS", "USES", "SOURCES", "INVOKES"):
        assert f"GW_V17_{rel}" not in out


def test_rewrite_handles_variable_length_relationships() -> None:
    """Variable-length rel patterns (``[:CALLS*1..3]``) keep the rel type."""
    adapter = NeptuneAdapter.__new__(NeptuneAdapter)
    tenant = _rewrite_tenant("GW_V17_")

    cypher = "MATCH (s:FortranSubroutine)-[:CALLS*1..3]->(t) RETURN t"
    out = adapter._rewrite_cypher(cypher, tenant)

    assert ":GW_V17_FortranSubroutine" in out
    assert ":CALLS" in out
    assert ":GW_V17_CALLS" not in out


def test_rewrite_empty_prefix_is_identity_with_relationships() -> None:
    """Default gw tenant (empty prefix) leaves the query untouched."""
    adapter = NeptuneAdapter.__new__(NeptuneAdapter)
    tenant = _rewrite_tenant("")

    cypher = "MATCH (s:File)-[r:CALLS]->() RETURN count(r) AS count"
    assert adapter._rewrite_cypher(cypher, tenant) == cypher


@pytest.mark.asyncio
async def test_neptune_adapter_connect_is_idempotent(fake_driver) -> None:
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    await adapter.connect()
    first_driver = adapter._driver
    await adapter.connect()
    assert adapter._driver is first_driver
    assert adapter._connected is True


@pytest.mark.asyncio
async def test_neptune_adapter_query_returns_row_dicts(fake_driver) -> None:
    fake_driver.run_results.append([{"name": "alpha", "n": 1}])
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    rows = await adapter.query(
        "MATCH (n) RETURN n.name AS name, count(n) AS n"
    )
    assert rows == [{"name": "alpha", "n": 1}]
    # Record was copied — caller mutation does NOT leak back into adapter.
    rows[0]["name"] = "MUTATED"
    fake_driver.run_results.append([{"name": "beta", "n": 1}])
    second = await adapter.query("MATCH (n) RETURN n.name AS name, count(n) AS n")
    assert second == [{"name": "beta", "n": 1}]


@pytest.mark.asyncio
async def test_neptune_adapter_query_passes_params(fake_driver) -> None:
    fake_driver.run_results.append([])
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    await adapter.query(
        "MATCH (n {id: $id}) RETURN n",
        params={"id": "JGFS_FORECAST"},
    )
    assert fake_driver.run_calls == [
        ("MATCH (n {id: $id}) RETURN n", {"id": "JGFS_FORECAST"})
    ]


# ── statement-timeout backstop (R5.1, R5.4, R5.5) ─────────────────────────


@pytest.mark.asyncio
async def test_neptune_adapter_query_timeout_none_is_unchanged(fake_driver) -> None:
    """The default ``timeout=None`` path is byte-for-byte the historical
    behaviour — no ``asyncio.wait_for`` wrapping, rows returned directly."""
    fake_driver.run_results.append([{"name": "alpha"}])
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    rows = await adapter.query("MATCH (n) RETURN n.name AS name")
    assert rows == [{"name": "alpha"}]
    # Explicit None is equivalent to omitting the kwarg.
    fake_driver.run_results.append([{"name": "beta"}])
    rows2 = await adapter.query("MATCH (n) RETURN n.name AS name", timeout=None)
    assert rows2 == [{"name": "beta"}]


@pytest.mark.asyncio
async def test_neptune_adapter_query_returns_within_timeout(fake_driver) -> None:
    """A fast query under a generous timeout returns normally."""
    fake_driver.run_results.append([{"ok": 1}])
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    rows = await adapter.query("RETURN 1 AS ok", timeout=30.0)
    assert rows == [{"ok": 1}]


@pytest.mark.asyncio
async def test_neptune_adapter_query_raises_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``_run_session`` slower than ``timeout`` raises
    NeptuneAdapterError with a timeout message and increments
    ``queries_failed`` (R5.5)."""
    import time as _time

    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    adapter._connected = True  # bypass connect()

    def _slow(cypher, params):  # runs in a worker thread
        _time.sleep(0.5)
        return []

    monkeypatch.setattr(adapter, "_run_session", _slow)
    failed_before = adapter._metrics["queries_failed"]

    with pytest.raises(NeptuneAdapterError) as exc_info:
        await adapter.query("MATCH (n) RETURN n", timeout=0.01)

    assert "statement timeout" in str(exc_info.value)
    assert exc_info.value.status is None
    assert adapter._metrics["queries_failed"] == failed_before + 1


@pytest.mark.asyncio
async def test_neptune_adapter_query_timeout_passes_params_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The timeout path still forwards cypher + params to ``_run_session``."""
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    adapter._connected = True
    seen: list[tuple[str, dict[str, Any]]] = []

    def _fast(cypher, params):
        seen.append((cypher, params))
        return [{"deg": 7}]

    monkeypatch.setattr(adapter, "_run_session", _fast)
    rows = await adapter.query(
        "MATCH (a)-[r:CALLS]-(x) RETURN count(r) AS deg",
        params={"name": "foo"},
        timeout=30.0,
    )
    assert rows == [{"deg": 7}]
    assert seen == [
        ("MATCH (a)-[r:CALLS]-(x) RETURN count(r) AS deg", {"name": "foo"})
    ]


@pytest.mark.asyncio
async def test_neptune_adapter_translates_query_error(
    fake_driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Underlying NeptuneQueryError surfaces as NeptuneAdapterError."""
    from src.data.aws_backend import NeptuneQueryError

    fake_driver.run_results.append(NeptuneQueryError(503, "throttled"))
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    with pytest.raises(NeptuneAdapterError) as exc_info:
        await adapter.query("RETURN 1")
    assert exc_info.value.status == 503


@pytest.mark.asyncio
async def test_neptune_adapter_translates_connection_error(
    fake_driver,
) -> None:
    from src.data.aws_backend import NeptuneConnectionError

    fake_driver.run_results.append(
        NeptuneConnectionError("Neptune unreachable")
    )
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    with pytest.raises(NeptuneAdapterError) as exc_info:
        await adapter.query("RETURN 1")
    assert exc_info.value.status is None
    assert "Neptune connection error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_neptune_adapter_health_check_healthy(fake_driver) -> None:
    fake_driver.run_results.append([{"ok": 1}])
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    health = await adapter.health_check()
    assert health["status"] == "healthy"
    assert health["connected"] is True
    assert health["endpoint"] == "https://np.example/opencypher"


@pytest.mark.asyncio
async def test_neptune_adapter_health_check_degraded_unexpected_payload(
    fake_driver,
) -> None:
    fake_driver.run_results.append([{"ok": "weird"}])
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    health = await adapter.health_check()
    assert health["status"] == "degraded"
    assert "unexpected" in health["reason"].lower()


@pytest.mark.asyncio
async def test_neptune_adapter_health_check_unhealthy_on_error(
    fake_driver,
) -> None:
    from src.data.aws_backend import NeptuneQueryError

    fake_driver.run_results.append(NeptuneQueryError(500, "boom"))
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    health = await adapter.health_check()
    assert health["status"] == "unhealthy"
    assert "boom" in health["error"]


@pytest.mark.asyncio
async def test_neptune_adapter_get_statistics(fake_driver) -> None:
    # 4 label counts then 1 relationship count, in order.
    fake_driver.run_results.extend(
        [
            [{"c": 1000}],   # File
            [{"c": 5000}],   # Function
            [{"c": 200}],    # Class
            [{"c": 100}],    # Module
            [{"c": 50000}],  # relationships
        ]
    )
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    stats = await adapter.get_statistics()
    assert stats == {
        "nodes": 6300,
        "relationships": 50000,
        "fileCount": 1000,
        "functionCount": 5000,
        "classCount": 200,
        "moduleCount": 100,
    }


@pytest.mark.asyncio
async def test_neptune_adapter_get_statistics_degrades_on_per_label_error(
    fake_driver,
) -> None:
    from src.data.aws_backend import NeptuneQueryError

    fake_driver.run_results.extend(
        [
            [{"c": 100}],                      # File ok
            NeptuneQueryError(500, "broken"),  # Function fails
            [{"c": 50}],                       # Class ok
            [{"c": 10}],                       # Module ok
            [{"c": 1234}],                     # relationships
        ]
    )
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    stats = await adapter.get_statistics()
    assert stats["fileCount"] == 100
    assert stats["functionCount"] == 0  # gracefully degraded
    assert stats["classCount"] == 50
    assert stats["nodes"] == 100 + 0 + 50 + 10
    assert stats["relationships"] == 1234


@pytest.mark.asyncio
async def test_neptune_adapter_close_is_idempotent(fake_driver) -> None:
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    await adapter.connect()
    await adapter.close()
    assert fake_driver.closed is True
    assert adapter._connected is False
    assert adapter._driver is None
    # Second close is a no-op (no exception).
    await adapter.close()


@pytest.mark.asyncio
async def test_neptune_adapter_close_without_connect() -> None:
    """Close on a never-connected adapter must not raise."""
    adapter = NeptuneAdapter(endpoint="https://np.example/opencypher")
    await adapter.close()  # no exception


# ── UnifiedDataAccess ─────────────────────────────────────────────────────


class _FakeAdapter:
    """Minimal stub for both vector and graph adapters.

    Records lifecycle calls + canned health response. Used to test the
    facade without involving real network I/O.
    """

    def __init__(self, *, label: str, health: dict[str, Any] | None = None):
        self.label = label
        self.connected = False
        self.closed = False
        self.health_calls: list[dict[str, Any]] = []
        self._health = health or {"status": "healthy"}

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def health_check(self, **kwargs) -> dict[str, Any]:
        self.health_calls.append(kwargs)
        return dict(self._health)


@pytest.mark.asyncio
async def test_facade_connects_both_adapters_in_parallel() -> None:
    v = _FakeAdapter(label="v")
    g = _FakeAdapter(label="g")
    facade = UnifiedDataAccess(vector_db=v, graph_db=g)
    await facade.connect()
    assert v.connected and g.connected
    # Idempotent — no errors on second call.
    await facade.connect()


@pytest.mark.asyncio
async def test_facade_close_swallows_adapter_errors() -> None:
    """One adapter raising on close() must not block the other."""

    class _Boom(_FakeAdapter):
        async def close(self):
            raise RuntimeError("close failed")

    v = _Boom(label="v")
    g = _FakeAdapter(label="g")
    facade = UnifiedDataAccess(vector_db=v, graph_db=g)
    await facade.connect()
    # Should NOT raise even though v.close raises.
    await facade.close()
    assert g.closed is True


@pytest.mark.asyncio
async def test_facade_health_check_healthy_when_both_ok() -> None:
    v = _FakeAdapter(
        label="v",
        health={
            "status": "healthy",
            "indices": ["a", "b", "c", "d", "e"],
            "total_documents": 100,
            "latency_ms": 12,
        },
    )
    g = _FakeAdapter(
        label="g",
        health={
            "status": "healthy",
            "nodes": 1000,
            "relationships": 5000,
            "latency_ms": 8,
        },
    )
    facade = UnifiedDataAccess(vector_db=v, graph_db=g)
    out = await facade.health_check(deep=True, min_indices=5)
    assert out["status"] == "healthy"
    assert out["vector"]["ok"] is True
    assert out["vector"]["indexCount"] == 5
    assert out["graph"]["ok"] is True
    assert out["graph"]["nodeCount"] == 1000
    # health_check on vector_db forwards `deep` arg
    assert v.health_calls[-1] == {"deep": True}


@pytest.mark.asyncio
async def test_facade_health_degraded_when_only_one_side() -> None:
    v = _FakeAdapter(
        label="v",
        health={"status": "healthy", "indices": ["a", "b", "c", "d", "e"]},
    )
    g = _FakeAdapter(
        label="g",
        health={"status": "healthy", "nodes": 0, "relationships": 0},
    )
    facade = UnifiedDataAccess(vector_db=v, graph_db=g)
    out = await facade.health_check()
    assert out["status"] == "degraded"
    assert out["vector"]["ok"] is True
    assert out["graph"]["ok"] is False
    assert out["graph"]["reason"] == "graph database has 0 nodes"


@pytest.mark.asyncio
async def test_facade_disabled_side_when_adapter_is_none() -> None:
    g = _FakeAdapter(
        label="g",
        health={"status": "healthy", "nodes": 100, "relationships": 200},
    )
    facade = UnifiedDataAccess(vector_db=None, graph_db=g)
    out = await facade.health_check()
    assert out["vector"]["status"] == "disabled"
    assert out["vector"]["ok"] is False
    # vector NOT ok and graph IS ok → overall degraded
    assert out["status"] == "degraded"


@pytest.mark.asyncio
async def test_facade_unhealthy_when_both_disabled() -> None:
    facade = UnifiedDataAccess(vector_db=None, graph_db=None)
    out = await facade.health_check()
    assert out["vector"]["status"] == "disabled"
    assert out["graph"]["status"] == "disabled"
    assert out["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_facade_health_handles_adapter_exception() -> None:
    class _Boom(_FakeAdapter):
        async def health_check(self, **kwargs):
            raise RuntimeError("probe failed")

    v = _Boom(label="v")
    g = _FakeAdapter(label="g", health={"status": "healthy", "nodes": 100})
    facade = UnifiedDataAccess(vector_db=v, graph_db=g)
    out = await facade.health_check()
    assert out["vector"]["ok"] is False
    assert out["vector"]["status"] == "unhealthy"
    assert "probe failed" in out["vector"]["reason"]


@pytest.mark.asyncio
async def test_facade_uses_get_statistics_when_health_lacks_counts() -> None:
    """Graph adapters without nodes in health response fall back to
    get_statistics() for the count."""

    class _StatsAdapter(_FakeAdapter):
        async def get_statistics(self) -> dict[str, Any]:
            return {"nodes": 9999, "relationships": 5}

    g = _StatsAdapter(
        label="g",
        # Note: health response has no nodes key.
        health={"status": "healthy"},
    )
    v = _FakeAdapter(
        label="v",
        health={"status": "healthy", "indices": ["a", "b", "c", "d", "e"]},
    )
    facade = UnifiedDataAccess(vector_db=v, graph_db=g)
    out = await facade.health_check()
    assert out["graph"]["nodeCount"] == 9999
    assert out["graph"]["relationshipCount"] == 5
    assert out["graph"]["ok"] is True


# ── backend_selector ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_backend_raises() -> None:
    cfg = ServerConfig(db_backend="legacy")
    with pytest.raises(UnsupportedBackendError, match="legacy"):
        await create_data_access(cfg)


@pytest.mark.asyncio
async def test_unknown_backend_raises() -> None:
    cfg = ServerConfig(db_backend="redis")
    with pytest.raises(UnsupportedBackendError, match="redis"):
        await create_data_access(cfg)


@pytest.mark.asyncio
async def test_aws_backend_with_injected_adapters() -> None:
    """When both adapters are pre-built, the selector skips
    config-driven construction entirely."""
    v = _FakeAdapter(
        label="v",
        health={"status": "healthy", "indices": ["a", "b", "c", "d", "e"]},
    )
    g = _FakeAdapter(
        label="g", health={"status": "healthy", "nodes": 100}
    )
    cfg = ServerConfig(
        db_backend="aws",
        neptune_endpoint="https://np.example/opencypher",
        opensearch_endpoint="https://os.example",
    )
    facade = await create_data_access(cfg, vector_db=v, graph_db=g)
    assert facade.vector_db is v
    assert facade.graph_db is g
    assert facade.backend == "aws"
    assert v.connected and g.connected


@pytest.mark.asyncio
async def test_aws_backend_disables_vector_on_empty_endpoint() -> None:
    cfg = ServerConfig(
        db_backend="aws",
        neptune_endpoint="",
        opensearch_endpoint="",
    )
    facade = await create_data_access(cfg)
    assert facade.vector_db is None
    assert facade.graph_db is None


@pytest.mark.asyncio
async def test_aws_backend_nulls_adapter_on_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When vector_db.connect() raises, the selector nulls the slot
    instead of propagating — graceful degrade per R1.7."""

    class _BoomAdapter(_FakeAdapter):
        async def connect(self):
            raise RuntimeError("opensearch unreachable")

    v_boom = _BoomAdapter(label="v")
    g_ok = _FakeAdapter(label="g", health={"status": "healthy", "nodes": 100})
    cfg = ServerConfig(
        db_backend="aws",
        neptune_endpoint="https://np.example",
        opensearch_endpoint="https://os.example",
    )
    facade = await create_data_access(cfg, vector_db=v_boom, graph_db=g_ok)
    assert facade.vector_db is None
    assert facade.graph_db is g_ok


@pytest.mark.asyncio
async def test_aws_backend_builds_real_adapters_when_endpoints_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without injected adapters, the selector should construct real
    OpenSearchAdapter + NeptuneAdapter instances. We don't actually
    connect — both adapters are stubbed at the connect layer to avoid
    network access."""
    built: dict[str, Any] = {}

    class _FakeOS:
        def __init__(self, *, endpoint, region):
            built["os"] = (endpoint, region)
            self.endpoint = endpoint

        async def connect(self):
            built["os_connected"] = True

        async def close(self):
            pass

    class _FakeNP:
        def __init__(self, *, endpoint, region):
            built["np"] = (endpoint, region)
            self.endpoint = endpoint

        async def connect(self):
            built["np_connected"] = True

        async def close(self):
            pass

    monkeypatch.setattr(
        "src.data.opensearch_adapter.OpenSearchAdapter", _FakeOS
    )
    monkeypatch.setattr(
        "src.data.neptune_adapter.NeptuneAdapter", _FakeNP
    )

    cfg = ServerConfig(
        db_backend="aws",
        neptune_endpoint="https://np.example/opencypher",
        opensearch_endpoint="https://os.example",
        aws_region="us-east-1",
    )
    facade = await create_data_access(cfg)
    assert built["os"] == ("https://os.example", "us-east-1")
    assert built["np"] == ("https://np.example/opencypher", "us-east-1")
    assert built.get("os_connected") is True
    assert built.get("np_connected") is True
    assert facade.backend == "aws"
