"""Shared Hypothesis generators and cross-adapter fixture.

shared-scope-query-routing Task 2.4. Delivers exactly the five reusable
pieces named in the design's "Testing Strategy" section -- the four
generator functions and the ``adapters()`` fixture -- so that later
property tests (P1 through P10) and their consuming unit tests draw from
one definition instead of re-deriving the tenant catalog or the profile
list piecemeal.

Sequencing note
----------------
tasks.md schedules this file under Task 2.4 in wave 4, but Task 3.2 and
Task 4.4 both consume what is defined here and are scheduled in wave 5.
That ordering is a defect in the plan (recorded in tasks.md's "Notes"
section): 2.4 has no dependency of its own on the Scope_Authority or the
Read_Router -- ``PRODUCTION_INDICES_BY_PROFILE``, ``tenants.yaml``,
``ChromaDBAdapter``, and ``OpenSearchAdapter`` already exist in the tree.
It is therefore implemented first, in wave 0, to unblock its consumers.

Hermetic by construction: no network access, no Bedrock, no
sentence-transformers. Both adapters below are constructed with an
explicit ``embedding_function`` so neither reaches for a real embedding
provider, and each is given a client double that serves canned
responses while recording every call it receives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.config.aws_config import PRODUCTION_INDICES_BY_PROFILE
from src.config.tenants import Tenant, load_catalog
from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.opensearch_adapter import OpenSearchAdapter

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_TENANTS_YAML = (
    "src/config/tenants.yaml"
)

#: Embedding_Profile values with a registered index map today. ``nova1024``
#: is added by :func:`profiles` separately -- it deliberately has no entry
#: in ``PRODUCTION_INDICES_BY_PROFILE`` (Requirement 5.4 coverage of the
#: passthrough case) and must not be inferred from this map.
_MAPPED_PROFILES: tuple[str, ...] = ("titan1024", "mpnet768")

#: The profile with no registered index map, exercised wherever
#: Requirement 5.4 (profile invariance, including the unmapped case)
#: applies.
_UNMAPPED_PROFILE = "nova1024"


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


def logical_collections() -> tuple[str, ...]:
    """Return the five Logical_Collection identifiers in service.

    Read directly from the keys of ``PRODUCTION_INDICES_BY_PROFILE``'s
    ``titan1024`` entry (the two mapped profiles register the same five
    keys; ``titan1024`` is picked as the reference so this function has
    a single source of truth rather than a hardcoded literal that could
    drift from the config module).
    """
    return tuple(PRODUCTION_INDICES_BY_PROFILE["titan1024"].keys())


def tenants() -> tuple[Tenant, ...]:
    """Return every tenant in ``src/config/tenants.yaml``, catalog order.

    Reads the bundled catalog file rather than hardcoding
    ``gw, gw_sfs, gw_jedi_gfs, gw_v17, gw_gefs_v12`` so a future catalog
    edit cannot silently drift this generator out of sync with the
    tenant it is meant to represent.
    """
    catalog = load_catalog(_TENANTS_YAML)
    return catalog.tenants


def prefixed_tenants() -> tuple[Tenant, ...]:
    """Return the subset of :func:`tenants` with a non-empty index_prefix.

    This is the Default_Tenant-excluding subset used by properties that
    require a non-empty prefix (e.g. cross-tenant disjointness, P5).
    """
    return tuple(t for t in tenants() if t.index_prefix)


def profiles() -> tuple[str, ...]:
    """Return the Embedding_Profile short names exercised by the suite.

    ``titan1024`` and ``mpnet768`` have a registered
    ``PRODUCTION_INDICES_BY_PROFILE`` entry; ``nova1024`` is included so
    the Requirement 5.4 passthrough case (no index map registered) has
    coverage wherever a property or test iterates this tuple. Its
    absence from the index map is deliberate, not an omission to be
    patched here.
    """
    return _MAPPED_PROFILES + (_UNMAPPED_PROFILE,)


# ---------------------------------------------------------------------------
# Recording client doubles
# ---------------------------------------------------------------------------


@dataclass
class _RecordedCall:
    """One recorded invocation against a client double."""

    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


@dataclass
class _FakeChromaCollection:
    """Canned ``chromadb`` collection double.

    Serves a fixed ``collection.query(...)`` response (the raw
    ``{ids, documents, metadatas, distances}`` shape ChromaDBAdapter's
    ``_format_hits`` expects) and records every call it receives.
    """

    name: str
    response: dict[str, Any] = field(
        default_factory=lambda: {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
    )
    calls: list[_RecordedCall] = field(default_factory=list)

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(_RecordedCall("query", (), dict(kwargs)))
        return self.response

    def count(self) -> int:
        self.calls.append(_RecordedCall("count", (), {}))
        return len(self.response.get("ids", [[]])[0])


class FakeChromaClient:
    """Recording double for the ``chromadb.HttpClient`` surface.

    Later properties (P8, P10, and the no-write sweep) assert on what
    was called, not just on what came back, so every method here
    appends to :pyattr:`calls` before returning.
    """

    def __init__(
        self, collections: dict[str, _FakeChromaCollection] | None = None
    ):
        self._collections = dict(collections or {})
        self.calls: list[_RecordedCall] = []

    def get_collection(self, name: str) -> _FakeChromaCollection:
        self.calls.append(_RecordedCall("get_collection", (name,), {}))
        if name not in self._collections:
            raise ValueError(f"Collection {name} does not exist.")
        return self._collections[name]

    def get_or_create_collection(self, name: str) -> _FakeChromaCollection:
        self.calls.append(
            _RecordedCall("get_or_create_collection", (name,), {})
        )
        return self._collections.setdefault(
            name, _FakeChromaCollection(name=name)
        )

    def list_collections(self) -> list[_FakeChromaCollection]:
        self.calls.append(_RecordedCall("list_collections", (), {}))
        return list(self._collections.values())

    def heartbeat(self) -> int:
        self.calls.append(_RecordedCall("heartbeat", (), {}))
        return 1

    def add_collection(
        self, name: str, **kwargs: Any
    ) -> _FakeChromaCollection:
        """Test-only helper (not part of the chromadb client surface).

        Lets a test seed a canned response for ``name`` before issuing a
        query against it.
        """
        coll = _FakeChromaCollection(name=name, **kwargs)
        self._collections[name] = coll
        return coll


class FakeOpenSearchRawClient:
    """Recording double for the vendored ``opensearch-py`` raw client.

    ``OpenSearchAdapter._raw_client()`` reaches ``self._client._client``
    and calls ``.search(index=..., body=...)``, ``.count(index=...)``,
    and ``.cat.indices(...)``. This double serves canned per-index
    responses for each and records every call.
    """

    def __init__(
        self,
        search_responses: dict[str, dict[str, Any]] | None = None,
        counts: dict[str, int] | None = None,
    ):
        self._search_responses = dict(search_responses or {})
        self._counts = dict(counts or {})
        self.calls: list[_RecordedCall] = []
        self.cat = _FakeOpenSearchCat(self)

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(
            _RecordedCall("search", (), {"index": index, "body": body})
        )
        if index not in self._search_responses:
            raise _FakeIndexNotFoundError(index)
        return self._search_responses[index]

    def count(self, *, index: str) -> dict[str, Any]:
        self.calls.append(_RecordedCall("count", (), {"index": index}))
        if index not in self._counts:
            raise _FakeIndexNotFoundError(index)
        return {"count": self._counts[index]}

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


class _FakeOpenSearchCat:
    """Recording double for ``client.cat.indices(...)``."""

    def __init__(self, owner: FakeOpenSearchRawClient):
        self._owner = owner

    def indices(
        self, format: str | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self._owner.calls.append(
            _RecordedCall("cat.indices", (), {"format": format, **kwargs})
        )
        return [{"index": name} for name in self._owner._counts]


class _FakeIndexNotFoundError(Exception):
    """Mirrors ``opensearchpy.NotFoundError``'s message shape.

    Close enough for ``_is_missing_index_exc``'s literal-token match to
    recognise it.
    """

    def __init__(self, index: str):
        super().__init__(f"index_not_found_exception: no such index [{index}]")
        self.index = index


# ---------------------------------------------------------------------------
# adapters() fixture
# ---------------------------------------------------------------------------


@pytest.fixture(params=["chromadb", "opensearch"])
def adapters(request: pytest.FixtureRequest):
    """Yield a ``ChromaDBAdapter`` or an ``OpenSearchAdapter`` over a stub.

    Both parameter ids are exactly ``"chromadb"`` and ``"opensearch"`` --
    a later meta-test (Task 2.5) asserts both strings appear in the
    collected node ids so a future change cannot quietly drop one
    backend from the sweep.

    Each adapter is constructed with an explicit ``embedding_function``
    so the fixture needs neither Bedrock nor sentence-transformers, and
    each is wired to a client double (:class:`FakeChromaClient` /
    :class:`FakeOpenSearchRawClient`) that serves recorded responses and
    records every call it receives, since later properties (P8, P10,
    and the no-write sweep) assert on what was called, not just on what
    came back.

    Yields
    ------
    tuple[ChromaDBAdapter | OpenSearchAdapter, Any]
        The adapter, already marked connected, and the raw client
        double so the test can seed collections/indices and inspect
        ``.calls``.
    """
    def embedding_function(texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0] for _ in texts]

    if request.param == "chromadb":
        adapter = ChromaDBAdapter(embedding_function=embedding_function)
        fake_client = FakeChromaClient()
        adapter._client = fake_client
        adapter._connected = True
        yield adapter, fake_client
        return

    if request.param == "opensearch":
        adapter = OpenSearchAdapter(
            endpoint="https://example.invalid",
            embedding_function=embedding_function,
        )
        fake_raw = FakeOpenSearchRawClient()
        # ``_raw_client()`` reaches ``self._client._client``; the adapter's
        # own ``_client`` is normally an ``OpenSearchVectorClient`` wrapper,
        # so a bare namespace exposing ``_client`` is sufficient here.
        adapter._client = _NamespaceWithRawClient(fake_raw)
        adapter._connected = True
        yield adapter, fake_raw
        return

    raise AssertionError(  # pragma: no cover
        f"unknown adapters() param: {request.param!r}"
    )


class _NamespaceWithRawClient:
    """Minimal stand-in for ``OpenSearchVectorClient`` exposing ``_client``.

    ``OpenSearchAdapter._raw_client()`` only ever reaches through this one
    attribute, so nothing else needs to be modeled.
    """

    def __init__(self, raw_client: FakeOpenSearchRawClient):
        self._client = raw_client
