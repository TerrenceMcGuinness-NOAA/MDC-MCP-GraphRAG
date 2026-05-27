"""Pytest configuration and shared fixtures (Requirements 13.1).

Originally this file only prepended the package root to ``sys.path``.
Phase B4 extends it with:

* mock ``VectorDBProtocol`` / ``GraphDBProtocol`` implementations that
  tool-layer tests can inject in place of live AWS adapters,
* sample data fixtures (document hits, graph nodes) used by multiple
  test modules,
* an async tool-call helper that returns a ``ParityRunner``-compatible
  ``ToolCaller`` bound to a mock adapter set,
* small utilities (``FakeClock``, ``deterministic_ids``) that keep
  Hypothesis tests reproducible.

Everything here is test-only infrastructure — production code never
imports from this file.
"""

from __future__ import annotations

import sys
import tempfile
import time
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

import pytest

# ── path bootstrap ──────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── sample data ─────────────────────────────────────────────────────────


#: Canonical OpenSearch-shaped hits used by tool-layer tests. Keys match
#: :data:`src.data.protocols.VECTOR_RESULT_KEYS` so any tool that consumes
#: ``VectorDBProtocol.query`` can accept them unchanged.
SAMPLE_VECTOR_HITS: list[dict[str, Any]] = [
    {
        "id": "doc-001",
        "content": "JGLOBAL_FORECAST runs the GFS model forecast job.",
        "metadata": {
            "source_file": "jobs/JGLOBAL_FORECAST",
            "collection": "mdc-jjobs-mpnet768",
            "language": "shell",
        },
        "score": 0.92,
    },
    {
        "id": "doc-002",
        "content": "exglobal_forecast.py wraps the forecast executable.",
        "metadata": {
            "source_file": "ush/exglobal_forecast.py",
            "collection": "mdc-code-context-mpnet768",
            "language": "python",
        },
        "score": 0.81,
    },
    {
        "id": "doc-003",
        "content": "The forecast module requires ESMF and NetCDF dependencies.",
        "metadata": {
            "source_file": "docs/forecast.md",
            "collection": "mdc-workflow-docs-mpnet768",
            "language": "markdown",
        },
        "score": 0.74,
    },
]


#: Canonical graph rows used by GGSR / GraphRAGTools tests. Shape matches
#: what :pymeth:`src.graphrag.ggsr_traversal.GGSRTraversal._score_results`
#: expects — at minimum ``name`` + ``relationship`` + ``hop_distance``.
SAMPLE_GRAPH_ROWS: list[dict[str, Any]] = [
    {
        "name": "forecast",
        "relationship": "CALLS",
        "hop_distance": 1,
        "labels": ["FortranSubroutine"],
        "path": "sorc/model/forecast.F90",
    },
    {
        "name": "ush_forecast_setup",
        "relationship": "SOURCES",
        "hop_distance": 1,
        "labels": ["ShellScript"],
        "path": "ush/forecast_setup.sh",
    },
    {
        "name": "write_restart",
        "relationship": "CALLS",
        "hop_distance": 2,
        "labels": ["FortranSubroutine"],
        "path": "sorc/model/write_restart.F90",
    },
]


# ── mock adapters ───────────────────────────────────────────────────────


@dataclass
class MockVectorDB:
    """In-memory double for :class:`src.data.protocols.VectorDBProtocol`.

    The adapter is *structural* — it deliberately does not subclass the
    Protocol (Python's ``Protocol`` classes are implicit). Tests that
    use ``isinstance(vector, VectorDBProtocol)`` will still see it as a
    match because all required methods are present.

    Behaviour knobs:

    * ``hits`` — list returned by :pymeth:`query`. Defaults to
      :data:`SAMPLE_VECTOR_HITS`.
    * ``collections`` — returned by :pymeth:`list_collections`.
    * ``health`` — overrides the dict returned by :pymeth:`health_check`.
    * ``raise_on_query`` — a ``BaseException`` instance; if set, every
      :pymeth:`query` call will raise it (for testing error-path code).
    * ``call_log`` — every ``(method, args)`` tuple is appended so tests
      can assert the adapter was reached with the expected inputs.
    """

    hits: list[dict[str, Any]] = field(default_factory=lambda: list(SAMPLE_VECTOR_HITS))
    collections: list[str] = field(
        default_factory=lambda: [
            "mdc-code-context-mpnet768",
            "mdc-workflow-docs-mpnet768",
            "mdc-jjobs-mpnet768",
            "mdc-community-summaries-mpnet768",
            "mdc-ee2-standards-mpnet768",
        ]
    )
    health: dict[str, Any] | None = None
    raise_on_query: BaseException | None = None
    connected: bool = False
    call_log: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        default_factory=list
    )

    async def connect(self) -> None:
        self.connected = True
        self.call_log.append(("connect", (), {}))

    async def close(self) -> None:
        self.connected = False
        self.call_log.append(("close", (), {}))

    async def query(
        self,
        collection: str,
        query_text: str,
        *,
        k: int = 10,
        similarity_threshold: float = 0.0,
        where: dict[str, Any] | None = None,
        include_graph: bool = True,
    ) -> list[dict[str, Any]]:
        self.call_log.append(
            (
                "query",
                (collection, query_text),
                {
                    "k": k,
                    "similarity_threshold": similarity_threshold,
                    "where": where,
                    "include_graph": include_graph,
                },
            )
        )
        if self.raise_on_query is not None:
            raise self.raise_on_query
        filtered = [h for h in self.hits if h["score"] >= similarity_threshold]
        return filtered[:k]

    async def multi_collection_query(
        self,
        collections: list[str],
        query_text: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.call_log.append(
            ("multi_collection_query", tuple(collections), {"query_text": query_text, **kwargs})
        )
        merged: list[dict[str, Any]] = []
        for coll in collections:
            merged.extend(await self.query(coll, query_text, **kwargs))
        merged.sort(key=lambda h: h.get("score", 0.0), reverse=True)
        return merged[: kwargs.get("k", 10)]

    async def list_collections(self) -> list[str]:
        self.call_log.append(("list_collections", (), {}))
        return list(self.collections)

    async def health_check(self, *, deep: bool = False) -> dict[str, Any]:
        self.call_log.append(("health_check", (), {"deep": deep}))
        if self.health is not None:
            return dict(self.health)
        return {
            "status": "healthy",
            "connected": self.connected,
            "collections": list(self.collections),
            "indices": list(self.collections),
            "total_documents": len(self.hits),
            "latency_ms": 5,
        }


@dataclass
class MockGraphDB:
    """In-memory double for :class:`src.data.protocols.GraphDBProtocol`.

    Maintains a simple map from cypher query string to a list of rows.
    Tests can either seed ``canned_rows`` directly or register query
    templates via :pymeth:`add_response`.

    ``statistics`` backs :pymeth:`get_statistics` used by HealthChecker
    parity.
    """

    canned_rows: list[dict[str, Any]] = field(
        default_factory=lambda: list(SAMPLE_GRAPH_ROWS)
    )
    responses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    statistics: dict[str, Any] = field(
        default_factory=lambda: {
            "nodes": 59_759,
            "relationships": 2_633_374,
            "fileCount": 8_000,
            "functionCount": 42_000,
            "classCount": 1_500,
            "moduleCount": 800,
        }
    )
    health: dict[str, Any] | None = None
    raise_on_query: BaseException | None = None
    connected: bool = False
    call_log: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        default_factory=list
    )

    def add_response(
        self, query_fragment: str, rows: list[dict[str, Any]]
    ) -> None:
        """Register ``rows`` to be returned when any substring of ``query``
        matches ``query_fragment``. Later registrations override earlier
        ones for the same fragment."""
        self.responses[query_fragment] = list(rows)

    async def connect(self) -> None:
        self.connected = True
        self.call_log.append(("connect", (), {}))

    async def close(self) -> None:
        self.connected = False
        self.call_log.append(("close", (), {}))

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.call_log.append(("query", (cypher,), dict(params or {})))
        if self.raise_on_query is not None:
            raise self.raise_on_query
        # First check for a registered fragment match (longest wins so a
        # more specific registration beats a generic one).
        match = ""
        for frag in self.responses:
            if frag and frag in cypher and len(frag) > len(match):
                match = frag
        if match:
            return list(self.responses[match])
        return list(self.canned_rows)

    async def get_statistics(self) -> dict[str, Any]:
        self.call_log.append(("get_statistics", (), {}))
        return dict(self.statistics)

    async def health_check(self) -> dict[str, Any]:
        self.call_log.append(("health_check", (), {}))
        if self.health is not None:
            return dict(self.health)
        return {
            "status": "healthy",
            "connected": self.connected,
            "nodes": self.statistics.get("nodes", 0),
            "relationships": self.statistics.get("relationships", 0),
            "latency_ms": 12,
        }


@dataclass
class MockUnifiedDataAccess:
    """Composite mock standing in for ``src.data.UnifiedDataAccess``.

    Exposes the attributes the tool layer reads directly (``vector_db``,
    ``graph_db``) plus a convenience ``health_check()`` facade that
    aggregates the two adapter results the way the Node.js
    ``HealthChecker.checkDatabases`` does.
    """

    vector_db: MockVectorDB = field(default_factory=MockVectorDB)
    graph_db: MockGraphDB = field(default_factory=MockGraphDB)

    async def connect(self) -> None:
        await self.vector_db.connect()
        await self.graph_db.connect()

    async def close(self) -> None:
        await self.vector_db.close()
        await self.graph_db.close()

    async def health_check(
        self, *, deep: bool = False, min_indices: int = 5
    ) -> dict[str, Any]:
        """Return the shape the utility tool module consumes.

        Matches the aggregated structure produced by the Node.js
        ``HealthChecker.checkDatabases`` with an added ``deep`` flag
        forwarded to the vector adapter so the tool-layer code path
        exercised by ``mcp_health_check(deep=True)`` is testable here.
        """
        vec_health = await self.vector_db.health_check(deep=deep)
        graph_health = await self.graph_db.health_check()
        vec_indices = len(vec_health.get("indices") or vec_health.get("collections") or [])
        vec_ok = vec_health.get("status") == "healthy" and vec_indices >= min_indices
        graph_ok = graph_health.get("status") == "healthy" and graph_health.get(
            "nodes", 0
        ) > 0
        return {
            "status": "healthy" if (vec_ok and graph_ok) else "degraded",
            "vector": {
                "ok": vec_ok,
                "status": vec_health.get("status", "unknown"),
                "indexCount": vec_indices,
                "totalDocuments": vec_health.get("total_documents", 0),
                "latency_ms": vec_health.get("latency_ms"),
                "reason": None
                if vec_ok
                else f"only {vec_indices} indices (need ≥{min_indices})",
            },
            "graph": {
                "ok": graph_ok,
                "status": graph_health.get("status", "unknown"),
                "nodeCount": graph_health.get("nodes", 0),
                "relationshipCount": graph_health.get("relationships", 0),
                "latency_ms": graph_health.get("latency_ms"),
                "reason": None if graph_ok else "graph database has 0 nodes",
            },
        }


# ── pytest fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def sample_vector_hits() -> list[dict[str, Any]]:
    """Fresh copy of the canonical vector-hit samples (safe to mutate)."""
    return [dict(h, metadata=dict(h["metadata"])) for h in SAMPLE_VECTOR_HITS]


@pytest.fixture()
def sample_graph_rows() -> list[dict[str, Any]]:
    """Fresh copy of the canonical graph-row samples (safe to mutate)."""
    return [dict(r, labels=list(r["labels"])) for r in SAMPLE_GRAPH_ROWS]


@pytest.fixture()
def mock_vector_db() -> MockVectorDB:
    return MockVectorDB()


@pytest.fixture()
def mock_graph_db() -> MockGraphDB:
    return MockGraphDB()


@pytest.fixture()
def mock_data_access() -> MockUnifiedDataAccess:
    return MockUnifiedDataAccess()


# ── deterministic time / IDs for Hypothesis reproducibility ────────────


class FakeClock:
    """Monotonically increasing ISO-8601 clock suitable for test injection.

    Each call advances by one second starting from ``start_seconds``.
    Unlike ``freezegun`` this doesn't patch the real ``datetime`` module
    — the caller must inject the clock where needed (that's the whole
    point: side-effect-free).
    """

    def __init__(self, start_seconds: int = 0) -> None:
        self._tick = start_seconds

    def __call__(self) -> str:
        self._tick += 1
        hours, rem = divmod(self._tick, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"2026-05-12T{hours:02d}:{minutes:02d}:{seconds:02d}.000Z"


@pytest.fixture()
def fake_clock() -> FakeClock:
    return FakeClock()


def make_deterministic_id_factory(
    prefix: str = "id", width: int = 6
) -> Callable[[], str]:
    """Return a zero-arg factory that produces ``{prefix}{000001}``-shaped IDs.

    The ``SessionManager`` / any other class that accepts an
    ``id_factory`` can use this instead of the default random-alnum
    generator so Hypothesis shrinks are fully reproducible.
    """
    counter = count(1)

    def factory() -> str:
        return f"{prefix}{next(counter):0{width}d}"

    return factory


@pytest.fixture()
def deterministic_id_factory() -> Callable[[], str]:
    return make_deterministic_id_factory()


# ── ParityRunner-compatible tool caller for mock servers ────────────────


def build_mock_tool_caller(
    responses: dict[str, Any] | None = None,
    *,
    latency_ms: float = 0.0,
    side_effect: Callable[[str, dict[str, Any]], Any] | None = None,
) -> Callable[[str, dict[str, Any]], Awaitable[Any]]:
    """Create a :data:`tests.parity.parity_runner.ToolCaller` from a dict.

    Parameters
    ----------
    responses
        Mapping from tool name to the value the caller should return.
    latency_ms
        Artificial latency to simulate — useful when exercising the
        ``asyncio.gather`` concurrency in ``ParityRunner.assert_parity``.
    side_effect
        Optional callable invoked before returning (e.g. to raise an
        exception for a specific tool name).

    Returns
    -------
    Awaitable callable suitable as ``nodejs_caller`` or ``python_caller``.
    """
    table = dict(responses or {})

    async def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        if side_effect is not None:
            ret = side_effect(tool_name, arguments)
            if ret is not None:
                return ret
        if latency_ms:
            # ``asyncio.sleep`` is cheap and lets gather() interleave.
            import asyncio as _asyncio
            await _asyncio.sleep(latency_ms / 1000.0)
        if tool_name not in table:
            raise KeyError(f"mock caller has no response for {tool_name!r}")
        value = table[tool_name]
        if callable(value):
            return value(arguments)
        return value

    return _call


# ── generic helpers ─────────────────────────────────────────────────────


@pytest.fixture()
def tmp_state_dir(tmp_path: Path) -> Path:
    """Scratch directory for SessionManager-style state files.

    Pre-creates ``checkpoints/`` so tests don't have to.
    """
    state = tmp_path / "state"
    (state / "checkpoints").mkdir(parents=True, exist_ok=True)
    return state


@pytest.fixture(scope="session")
def monotonic_wall_clock() -> Callable[[], float]:
    """A monotonic wall-clock timer (seconds float).

    Not ISO-8601 — use :class:`FakeClock` for that. This one is handy
    for latency measurements in tests.
    """
    return time.monotonic


# ── embedding provider fixtures (Phase C-2c, Req 11.6) ─────────────────


class MockBedrockProvider:
    """In-memory stand-in for
    :class:`src.data.embedding_provider.BedrockProvider`.

    Emits zero-vectors of length ``profile.dimensions`` without
    touching boto3 or AWS. Used by ``OpenSearchAdapter`` tests after
    the Phase C-2c swap so the same fixture works for ``titan1024``
    (1024-dim) and any other profile (Nova at 256/512/1024/3072).

    The class deliberately does not subclass ``BedrockProvider`` —
    that would force a boto3 client construction at ``__init__``.
    Duck-typing satisfies the
    :class:`src.data.embedding_provider.EmbeddingProvider` protocol
    everywhere the adapter touches.
    """

    def __init__(self, profile: Any) -> None:
        self._profile = profile
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.0] * self._profile.dimensions for _ in texts]

    @property
    def dimensions(self) -> int:
        return self._profile.dimensions


@pytest.fixture()
def mock_bedrock_provider() -> Callable[[Any], MockBedrockProvider]:
    """Factory that builds a :class:`MockBedrockProvider` for a profile.

    Tests that just want the provider object call this with the
    profile they need. The ``OpenSearchAdapter`` does not consume the
    profile from the provider directly, but the dimension comes from
    the profile so the zero-vector matches the expected length.
    """

    def _build(profile: Any) -> MockBedrockProvider:
        return MockBedrockProvider(profile)

    return _build


@pytest.fixture()
def bedrock_provider_factory(monkeypatch: pytest.MonkeyPatch):
    """Patch :func:`create_provider` to yield a :class:`MockBedrockProvider`.

    Patches the import-bound name in
    :mod:`src.data.opensearch_adapter` so the ``OpenSearchAdapter``
    constructor pulls the mock provider for any profile, replacing
    the real Bedrock client construction. Returns the patch handle so
    individual tests can also pre-seed canned vectors via
    :pyattr:`MockBedrockProvider.calls` introspection.

    Notes
    -----
    Phase C-2c (Bedrock-native embedding swap) retires the prior
    mpnet-stub fixtures that injected
    ``embedding_function=lambda xs: [[0.0]*768 for _ in xs]`` into
    ``OpenSearchAdapter``. The dimension is now derived from the
    active profile (``profile.dimensions``) so the same fixture
    works for ``titan1024`` (1024-dim) and the Nova family.
    """
    built: list[MockBedrockProvider] = []

    def _factory(profile: Any) -> MockBedrockProvider:
        provider = MockBedrockProvider(profile)
        built.append(provider)
        return provider

    monkeypatch.setattr(
        "src.data.opensearch_adapter.create_provider", _factory
    )

    return built


# ── re-export everything tests might want to import ─────────────────────

__all__ = [
    "SAMPLE_VECTOR_HITS",
    "SAMPLE_GRAPH_ROWS",
    "MockVectorDB",
    "MockGraphDB",
    "MockUnifiedDataAccess",
    "MockBedrockProvider",
    "FakeClock",
    "make_deterministic_id_factory",
    "build_mock_tool_caller",
]


# ── tenant test helpers ─────────────────────────────────────────────────


@pytest.fixture
def tenant_context_for_test(tmp_path):
    """Fixture that sets a TenantContext on the ContextVar for the test scope.

    Usage::

        def test_something(tenant_context_for_test):
            ctx = tenant_context_for_test(workflow_root=tmp_path / "wf")
            # get_current_tenant() now returns ctx
    """
    from src.config.tenants import Tenant
    from src.tenancy.resolver import TenantContext, _ctx_var

    def _factory(
        tenant_id: str = "gw",
        workflow_root: Path | None = None,
    ) -> TenantContext:
        subdir = "develop" if workflow_root is None else workflow_root.name
        root = workflow_root or tmp_path / "develop"
        root.mkdir(parents=True, exist_ok=True)
        tenant = Tenant(
            tenant_id=tenant_id,
            repo_ref="NOAA-EMC/global-workflow",
            branch="develop",
            index_prefix="",
            label_prefix="",
            workflow_subdir=subdir,
            lifecycle="production",
            description="test",
        )
        # Monkey-patch workflow_root to use the tmp_path
        object.__setattr__(tenant, "workflow_root", root)
        ctx = TenantContext(tenant_id=tenant_id, tenant=tenant)
        _ctx_var.set(ctx)
        return ctx

    yield _factory
    _ctx_var.set(None)
