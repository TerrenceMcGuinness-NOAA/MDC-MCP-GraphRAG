"""A read must never create what it cannot find.

shared-scope-query-routing Task 12.3 (Requirement 12.5). Sweeps every
read-path surface this spec introduced -- ``query``,
``collection_condition``, and the Status_Reporter, Integrity_Checker, and
Health_Reporter enumerations -- against an adapter double that RAISES on
any mutating call: ``upsert_document``, ``get_or_create_collection``, any
index-creation API, any delete.

Kept in its own file, separate from ``test_scope_merge.py``, so the two
can be worked independently (tasks.md, Task 12.3).

The case that matters most
--------------------------
An ABSENT member of a Resolved_Collection_Set -- a shared collection a
tenant cannot reach, or a tenant collection never ingested -- must be
REPORTED as unprovisioned and never CREATED to make a read succeed.
ChromaDB's ``get_or_create_collection`` makes that failure mode one
keystroke away: a careless read-path implementation could call it to
"resolve" a missing collection, silently provisioning an empty one and
turning a structural blind spot into a permanent, invisible one. Every
scenario below therefore includes at least one addressed member that
does not exist on the backend double.

``collection_condition`` and the zero-hit path
-----------------------------------------------
``collection_condition`` deliberately probes on the zero-hit path via
``count_documents`` -- that is a READ and a metadata COUNT, both
permitted by R12.5. This module asserts that stays true: the raising
double allows ``count_documents`` (and ``search``/``count`` at the raw
client level for OpenSearch, ``get_collection``/``count`` for ChromaDB)
while forbidding every mutating call, so a passing sweep demonstrates the
metadata-count probe never escalates into a write.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.config.tenants import load_catalog
from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.opensearch_adapter import OpenSearchAdapter
from src.data.read_router import tenant_collection_set
from src.data.unified_data_access import UnifiedDataAccess
from src.tools import semantic_search as ss

_CATALOG = load_catalog("src/config/tenants.yaml")
_V17 = _CATALOG.by_id("gw_v17")
_GW = _CATALOG.by_id("gw")


class MutationAttempted(AssertionError):
    """Raised by the write-guarding doubles below when a mutating call is
    attempted (R12.5 violation)."""


# ---------------------------------------------------------------------------
# ChromaDB: a client double that raises on any mutating call
# ---------------------------------------------------------------------------


class _NoWriteChromaCollection:
    """A ChromaDB collection double permitting reads, forbidding writes.

    ``query`` and ``count`` are reads; ``upsert``, ``add``, ``update``,
    and ``delete`` are the mutating surface a real
    ``chromadb.Collection`` exposes and must never be reached.
    """

    def __init__(self, name: str, response: dict[str, Any]):
        self.name = name
        self._response = response

    def query(self, **kwargs: Any) -> dict[str, Any]:
        return self._response

    def count(self) -> int:
        return len(self._response.get("ids", [[]])[0])

    def upsert(self, *args: Any, **kwargs: Any) -> None:
        raise MutationAttempted(
            f"Collection.upsert called on {self.name!r} during a read path"
        )

    def add(self, *args: Any, **kwargs: Any) -> None:
        raise MutationAttempted(
            f"Collection.add called on {self.name!r} during a read path"
        )

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise MutationAttempted(
            f"Collection.update called on {self.name!r} during a read path"
        )

    def delete(self, *args: Any, **kwargs: Any) -> None:
        raise MutationAttempted(
            f"Collection.delete called on {self.name!r} during a read path"
        )


class NoWriteChromaClient:
    """A ``chromadb`` client double whose write surface always raises.

    ``get_collection`` (a read: fails with a not-found-shaped error for
    an absent name, exactly like the real client) is permitted.
    ``get_or_create_collection``, ``create_collection``, and
    ``delete_collection`` -- the client-level mutating/creating surface
    named explicitly in the task text -- all raise
    :class:`MutationAttempted`. ``list_collections`` and ``heartbeat``
    are reads.
    """

    def __init__(self, present: dict[str, dict[str, Any]] | None = None):
        self._present = {
            name: _NoWriteChromaCollection(name, response)
            for name, response in (present or {}).items()
        }

    def get_collection(self, name: str) -> _NoWriteChromaCollection:
        if name not in self._present:
            raise ValueError(f"Collection {name} does not exist.")
        return self._present[name]

    def get_or_create_collection(self, name: str) -> _NoWriteChromaCollection:
        raise MutationAttempted(
            f"get_or_create_collection called for {name!r} during a read "
            f"path -- an absent collection must be reported as "
            f"unprovisioned, never created to make a read succeed"
        )

    def create_collection(self, name: str, **kwargs: Any) -> Any:
        raise MutationAttempted(
            f"create_collection called for {name!r} during a read path"
        )

    def delete_collection(self, name: str) -> None:
        raise MutationAttempted(
            f"delete_collection called for {name!r} during a read path"
        )

    def list_collections(self) -> list[_NoWriteChromaCollection]:
        return list(self._present.values())

    def heartbeat(self) -> int:
        return 1


# ---------------------------------------------------------------------------
# OpenSearch: a raw-client double that raises on any mutating call
# ---------------------------------------------------------------------------


class _NoWriteIndexNotFoundError(Exception):
    """Mirrors ``opensearchpy.NotFoundError``'s message shape closely
    enough for ``_is_missing_index_exc``'s literal-token match."""

    def __init__(self, index: str):
        super().__init__(
            f"index_not_found_exception: no such index [{index}]"
        )
        self.index = index


class NoWriteOpenSearchRawClient:
    """A raw ``opensearch-py``-shaped double whose write surface raises.

    ``search`` and ``count`` are reads and are permitted (a missing
    index raises the not-found-shaped error, exactly like production).
    ``index``, ``update``, ``delete``, ``bulk``,
    ``indices.create``, and ``indices.delete`` are the mutating /
    index-creation surface and all raise :class:`MutationAttempted`.
    ``cat.indices`` is a read.
    """

    def __init__(
        self,
        search_responses: dict[str, dict[str, Any]] | None = None,
        counts: dict[str, int] | None = None,
    ):
        self._search_responses = dict(search_responses or {})
        self._counts = dict(counts or {})
        self.cat = _NoWriteCat(self)
        self.indices = _NoWriteIndicesNamespace()

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        if index not in self._search_responses:
            raise _NoWriteIndexNotFoundError(index)
        return self._search_responses[index]

    def count(self, *, index: str) -> dict[str, Any]:
        if index not in self._counts:
            raise _NoWriteIndexNotFoundError(index)
        return {"count": self._counts[index]}

    def index(self, *args: Any, **kwargs: Any) -> Any:
        raise MutationAttempted(
            "client.index(...) called during a read path"
        )

    def update(self, *args: Any, **kwargs: Any) -> Any:
        raise MutationAttempted(
            "client.update(...) called during a read path"
        )

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise MutationAttempted(
            "client.delete(...) called during a read path"
        )

    def bulk(self, *args: Any, **kwargs: Any) -> Any:
        raise MutationAttempted(
            "client.bulk(...) called during a read path"
        )

    def add_index(
        self,
        index: str,
        *,
        hits: list[dict[str, Any]] | None = None,
        count: int | None = None,
    ) -> None:
        """Test-only helper to seed a canned search response / count."""
        self._search_responses[index] = {"hits": {"hits": hits or []}}
        if count is None:
            count = len(hits or [])
        self._counts[index] = count


class _NoWriteCat:
    def __init__(self, owner: NoWriteOpenSearchRawClient):
        self._owner = owner

    def indices(
        self, format: str | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return [{"index": name} for name in self._owner._counts]


class _NoWriteIndicesNamespace:
    """``client.indices.*`` -- the index-creation/-deletion API surface."""

    def create(self, *args: Any, **kwargs: Any) -> Any:
        raise MutationAttempted(
            "client.indices.create(...) called during a read path"
        )

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise MutationAttempted(
            "client.indices.delete(...) called during a read path"
        )

    def exists(self, *args: Any, **kwargs: Any) -> bool:
        # A read: used by some existence-check code paths. Not exercised
        # by the Read_Router (R5.1 forbids existence probes during
        # resolution) but declared for completeness of the double.
        return False


class _NamespaceWithNoWriteRawClient:
    """Minimal stand-in for ``OpenSearchVectorClient`` exposing ``_client``."""

    def __init__(self, raw_client: NoWriteOpenSearchRawClient):
        self._client = raw_client


# ---------------------------------------------------------------------------
# Adapter construction over the write-guarding doubles
# ---------------------------------------------------------------------------


def _embedding_function(texts: list[str]) -> list[list[float]]:
    return [[0.0, 0.0] for _ in texts]


def _build_chroma_no_write(
    present: dict[str, dict[str, Any]] | None = None,
) -> ChromaDBAdapter:
    adapter = ChromaDBAdapter(embedding_function=_embedding_function)
    adapter._client = NoWriteChromaClient(present=present)
    adapter._connected = True
    return adapter


def _build_opensearch_no_write(
    search_responses: dict[str, dict[str, Any]] | None = None,
    counts: dict[str, int] | None = None,
) -> OpenSearchAdapter:
    adapter = OpenSearchAdapter(
        endpoint="https://example.invalid",
        embedding_function=_embedding_function,
    )
    raw = NoWriteOpenSearchRawClient(
        search_responses=search_responses, counts=counts
    )
    adapter._client = _NamespaceWithNoWriteRawClient(raw)
    adapter._connected = True
    return adapter


def _seed_chroma_present(name: str, hits: int = 1) -> dict[str, Any]:
    return {
        "ids": [[f"{name}-{i}" for i in range(hits)]],
        "documents": [[f"doc-{i}" for i in range(hits)]],
        "metadatas": [[{} for _ in range(hits)]],
        "distances": [[0.1 for _ in range(hits)]],
    }


# ---------------------------------------------------------------------------
# One present, one absent per scenario -- the case that matters most
# ---------------------------------------------------------------------------

_HYBRID_LOGICAL = "global-workflow-docs-v8-0-0"


@pytest.fixture(params=["chromadb", "opensearch"])
def no_write_adapter(request: pytest.FixtureRequest):
    """Yield a write-guarding adapter with a Hybrid_Domain's shared member
    present and its ``gw_v17``-prefixed member ABSENT.

    This is the resolved-set shape Task 12.3 calls out explicitly: a
    shared collection a (prefixed) tenant cannot reach must be reported,
    never created.

    Both adapters default their active profile from
    ``MCP_EMBEDDING_PROFILE``, but each has a different fallback when
    that variable is unset (OpenSearch: ``titan1024``; ChromaDB /
    ``collection_namer``: ``mpnet768``). The router resolution here must
    use the SAME profile the constructed adapter will use, or the seeded
    "present" physical name will not match what the adapter actually
    queries -- a test-harness pitfall, not a production concern (both
    deployed form factors set the variable explicitly).
    """
    profile = (
        "titan1024" if request.param == "opensearch" else "mpnet768"
    )
    resolved = tenant_collection_set(_V17, profile=profile)
    present_physical = resolved.by_logical[_HYBRID_LOGICAL][0]

    if request.param == "chromadb":
        adapter = _build_chroma_no_write(
            present={present_physical: _seed_chroma_present(present_physical)}
        )
        yield adapter
        return

    adapter = _build_opensearch_no_write(
        search_responses={
            present_physical: {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_score": 0.9,
                            "_source": {"content": "hello", "metadata": {}},
                        }
                    ]
                }
            }
        },
        counts={present_physical: 1},
    )
    yield adapter


def test_query_does_not_write_with_absent_member(no_write_adapter) -> None:
    """``query`` against a Hybrid_Domain with one absent member never
    creates the absent member; it returns the present member's hits."""
    results = asyncio.run(
        no_write_adapter.query(_HYBRID_LOGICAL, "err_chk", k=10, tenant=_V17)
    )
    # No MutationAttempted was raised getting here -- the assertion below
    # additionally confirms the read still produced results from the
    # present member rather than failing outright (R7.1).
    assert isinstance(results, list)
    assert len(results) >= 1


def test_query_all_absent_reports_not_created(no_write_adapter) -> None:
    """Every member absent: the adapter raises a read-level classification,
    never attempting to create a collection to satisfy the read."""
    from src.data.vector_errors import CollectionNotProvisionedError

    with pytest.raises(CollectionNotProvisionedError):
        asyncio.run(
            no_write_adapter.query(
                "jjobs-v8-0-0", "some query", k=5, tenant=_V17
            )
        )


@pytest.mark.parametrize("backend", ["chromadb", "opensearch"])
def test_collection_condition_never_writes(backend: str) -> None:
    """``collection_condition`` on an absent physical name never creates it.

    This is the zero-hit-path ambiguity probe (design "Cross-backend
    normalization"): it must resolve to UNPROVISIONED via a read-only
    existence/count check, never via ``get_or_create_collection`` or an
    index-creation call.
    """
    from src.data.read_router import CollectionCondition

    if backend == "chromadb":
        adapter = _build_chroma_no_write(present={})
    else:
        adapter = _build_opensearch_no_write()

    condition = asyncio.run(
        adapter.collection_condition("gw_v17_mdc-jjobs-titan1024")
    )
    assert condition == CollectionCondition.UNPROVISIONED


@pytest.mark.parametrize("backend", ["chromadb", "opensearch"])
def test_collection_condition_probes_only_count_on_zero_hit(
    backend: str,
) -> None:
    """A present-but-empty collection is classified via a metadata COUNT,
    not a write -- ``count_documents`` is a read and a metadata count,
    both permitted by R12.5. Asserted by the fact that reaching a
    correct PROVISIONED_EMPTY classification against these doubles
    could only have happened through the read surface, since every
    mutating method on both doubles raises."""
    from src.data.read_router import CollectionCondition

    name = "mdc-ee2-standards-titan1024"
    empty_response = {
        "ids": [[]], "documents": [[]],
        "metadatas": [[]], "distances": [[]],
    }
    if backend == "chromadb":
        adapter = _build_chroma_no_write(present={name: empty_response})
    else:
        adapter = _build_opensearch_no_write(
            search_responses={name: {"hits": {"hits": []}}},
            counts={name: 0},
        )

    condition = asyncio.run(adapter.collection_condition(name))
    assert condition == CollectionCondition.PROVISIONED_EMPTY


# ---------------------------------------------------------------------------
# Status_Reporter, Integrity_Checker, Health_Reporter enumerations
# ---------------------------------------------------------------------------


def _build_reporting_adapter(backend: str, present_physical: str):
    """Build a write-guarding adapter with exactly one member of the
    active tenant's Resolved_Collection_Sets present, all others absent.
    """
    if backend == "chromadb":
        return _build_chroma_no_write(
            present={
                present_physical: _seed_chroma_present(present_physical)
            }
        )
    return _build_opensearch_no_write(
        search_responses={present_physical: {"hits": {"hits": []}}},
        counts={present_physical: 3},
    )


def _reporting_profile(backend: str) -> str:
    """Match the adapter's own profile default (see ``no_write_adapter``
    fixture docstring for why the two backends' unset-env defaults
    differ and must be pinned explicitly in a test harness)."""
    return "titan1024" if backend == "opensearch" else "mpnet768"


@pytest.mark.parametrize("backend", ["chromadb", "opensearch"])
def test_status_reporter_does_not_write_with_absent_members(
    backend: str,
) -> None:
    """The Status_Reporter, run for a prefixed tenant with most of its
    Resolved_Collection_Sets unprovisioned, never triggers a mutating
    call -- absent members render as unprovisioned, not as created."""
    profile = _reporting_profile(backend)
    tcs = tenant_collection_set(_V17, profile=profile)
    present_physical = tcs.physical_names[0]
    adapter = _build_reporting_adapter(backend, present_physical)

    prior_profile = ss.os.environ.get("MCP_EMBEDDING_PROFILE")
    ss.os.environ["MCP_EMBEDDING_PROFILE"] = profile
    prior_tenant_fn = ss._tenant
    ss._tenant = lambda: _V17
    try:
        lines = asyncio.run(ss._render_vector_status_block(adapter))
    finally:
        ss._tenant = prior_tenant_fn
        if prior_profile is None:
            ss.os.environ.pop("MCP_EMBEDDING_PROFILE", None)
        else:
            ss.os.environ["MCP_EMBEDDING_PROFILE"] = prior_profile

    assert any(present_physical in ln for ln in lines)


@pytest.mark.parametrize("backend", ["chromadb", "opensearch"])
def test_integrity_checker_does_not_write_with_absent_members(
    backend: str,
) -> None:
    """The Integrity_Checker's scoped sampler never triggers a mutating
    call even when most of the tenant's members are unprovisioned."""
    profile = _reporting_profile(backend)
    tcs = tenant_collection_set(_V17, profile=profile)
    present_physical = tcs.physical_names[0]
    adapter = _build_reporting_adapter(backend, present_physical)

    counts: dict[str, int] = {}
    records = asyncio.run(
        ss._allocate_scoped_sample(
            adapter, list(tcs.physical_names), 25, counts
        )
    )
    assert isinstance(records, list)
    # Every named member is accounted for, present or absent alike --
    # none was created to make the sample succeed.
    assert set(counts.keys()) == set(tcs.physical_names)


@pytest.mark.parametrize("backend", ["chromadb", "opensearch"])
def test_health_reporter_does_not_write_with_absent_members(
    backend: str,
) -> None:
    """The Health_Reporter's scoped enumeration never triggers a mutating
    call: an absent member is named 'unprovisioned', not created."""
    profile = _reporting_profile(backend)
    prior_profile = ss.os.environ.get("MCP_EMBEDDING_PROFILE")
    ss.os.environ["MCP_EMBEDDING_PROFILE"] = profile
    try:
        tcs = tenant_collection_set(_V17, profile=profile)
        present_physical = tcs.physical_names[0]
        adapter = _build_reporting_adapter(backend, present_physical)

        raw = asyncio.run(adapter.health_check(deep=True))
        uda = UnifiedDataAccess(vector_db=adapter, graph_db=None)
        block = uda._scoped_vector_health(raw, _V17)
    finally:
        if prior_profile is None:
            ss.os.environ.pop("MCP_EMBEDDING_PROFILE", None)
        else:
            ss.os.environ["MCP_EMBEDDING_PROFILE"] = prior_profile

    names_and_conditions = {
        c["name"]: c["condition"] for c in block["collections"]
    }
    assert set(names_and_conditions) == set(tcs.physical_names)
    unprovisioned = {
        name
        for name, condition in names_and_conditions.items()
        if condition == "unprovisioned"
    }
    # At least one member is unprovisioned in this scenario (only one
    # physical name was seeded as present), and reaching this line at
    # all means nothing raised MutationAttempted while producing that
    # classification.
    assert unprovisioned


def test_default_tenant_status_reporter_does_not_write() -> None:
    """The Default_Tenant path (legacy, unscoped enumeration) also never
    writes when its single collection is absent from the backend."""
    adapter = _build_chroma_no_write(present={})

    prior_tenant_fn = ss._tenant
    ss._tenant = lambda: _GW
    try:
        lines = asyncio.run(ss._render_vector_status_block(adapter))
    finally:
        ss._tenant = prior_tenant_fn

    assert isinstance(lines, list)
