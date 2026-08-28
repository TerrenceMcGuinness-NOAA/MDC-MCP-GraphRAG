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
import random
from typing import Any

import pytest
from hypothesis import strategies as st

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


# ===========================================================================
# default-tenant-freeze-retirement Task 1.1 -- the five shared generators
# ---------------------------------------------------------------------------
# These land in wave 0 because five later tasks consume them: 1.4, 3.4, 3.5,
# 6.2, and 8.2. Each is a Hypothesis strategy factory (a function returning a
# ``SearchStrategy``), so a consuming test uses it directly, e.g.
# ``@given(shape=case_shapes())``. Two of them -- ``structural_views`` and
# ``triple_perturbations`` -- produce ``StructuralView`` values whose type is
# built by step 6 (``tests/baselines/structural.py``); they import that type
# lazily (inside the strategy body) so this module loads with no dependency
# on a file that does not yet exist. Nothing in step 1 draws those two, so the
# lazy import never fires before step 6 lands the type.
# ===========================================================================

#: Text alphabet spanning ASCII and a wide band of non-ASCII code points
#: (surrogates excluded). ``benchmark_cases`` uses it so Property 14's ASCII
#: clause has non-ASCII input to catch.
_MIXED_TEXT = st.text(
    alphabet=st.characters(
        min_codepoint=32,
        max_codepoint=0x2FFF,
        blacklist_categories=("Cs",),
    ),
    min_size=1,
    max_size=24,
)

#: Lowercase-plus-hyphen tokens used as synthetic Physical_Collection names
#: in ``structural_views``. Deliberately excludes the ``zz-added-`` prefix
#: ``triple_perturbations`` reserves for its "add a collection" mutation, so
#: an added collection can never collide with a generated one.
_COLLECTION_NAME = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyz-",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("zz-added-"))

#: Human-readable check names used as verdict keys in ``structural_views``.
_CHECK_NAME = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters=(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
        ),
    ),
    min_size=1,
    max_size=20,
).map(lambda s: s.strip()).filter(lambda s: len(s) > 0)


def case_shapes() -> st.SearchStrategy:
    """``(matched_count, expected_length, k)`` triples for the scoring core.

    Weighted so ``expected_length`` reaches four corners -- ``0``, ``1``,
    exactly ``k``, and above ``k`` -- rather than hitting them by chance.
    The zero draw is Requirement 4 criterion 6's input (empty
    ``expected_results`` must yield precision/recall ``0``, not
    ``ZeroDivisionError`` or ``nan``); it must not be incidental. The
    above-``k`` draw exercises the precision clamp (finding 5).
    ``matched_count`` is bounded by ``[0, expected_length]`` so a triple is
    always a physically reachable match count.
    """

    @st.composite
    def _gen(draw: Any) -> tuple[int, int, int]:
        k = draw(st.sampled_from((1, 2, 3, 5, 8)))
        expected_length = draw(
            st.one_of(
                st.just(0),
                st.just(1),
                st.just(k),
                st.integers(min_value=k + 1, max_value=k + 6),
                st.integers(min_value=0, max_value=12),
            )
        )
        matched_count = draw(
            st.integers(min_value=0, max_value=expected_length)
        )
        return (matched_count, expected_length, k)

    return _gen()


def benchmark_cases() -> st.SearchStrategy:
    """Synthetic ``BenchmarkCase`` values over the corpus's 15 tool names.

    ``tenant_id`` is present or absent (both partitions of Requirement 2
    criterion 8), and both ``question`` and ``expected_results`` draw from
    :data:`_MIXED_TEXT`, so a non-ASCII character can flow into the console
    output Property 14's ASCII clause guards. ``tenant_scoped`` is derived
    to agree with the presence of ``tenant_id`` in ``tool_args``, matching
    the dataclass's own derivation.
    """

    @st.composite
    def _gen(draw: Any):
        from scripts.run_benchmark import (
            CATEGORY_NAMES,
            CORPUS_TOOL_NAMES,
            BenchmarkCase,
        )

        tool = draw(st.sampled_from(CORPUS_TOOL_NAMES))
        category = draw(st.sampled_from(CATEGORY_NAMES))
        question = draw(_MIXED_TEXT)
        expected = draw(st.lists(_MIXED_TEXT, min_size=0, max_size=6))
        case_id = "bc_" + str(draw(st.integers(min_value=0, max_value=10**6)))
        tool_args: dict[str, Any] = {"query": draw(_MIXED_TEXT)}
        if draw(st.booleans()):
            tool_args["tenant_id"] = draw(
                st.sampled_from(("gw_v17", "gw_sfs", "gw_gefs_v12"))
            )
        return BenchmarkCase(
            id=case_id,
            question=question,
            tool=tool,
            tool_args=tool_args,
            expected_results=expected,
            expected_min_results=len(expected),
            category=category,
            notes="",
            tenant_scoped="tenant_id" in tool_args,
        )

    return _gen()


def structural_views() -> st.SearchStrategy:
    """``StructuralView`` values for the equivalence-relation properties.

    Collection counts include ``None`` (a collection rendered
    ``unprovisioned``), which the relation must keep distinct from ``0``
    (provisioned-empty). Verdicts range over the full ``Verdict`` set.

    The ``StructuralView`` type is built by step 6
    (``tests/baselines/structural.py``); it is imported lazily so this
    module loads before that file exists. Written against design.md's
    stated shape (``StructuralView(collections, verdicts)`` with ``Verdict``
    an enumeration of ``PASS`` / ``FAIL`` / ``SKIP``); step 6, which owns
    the type and is this generator's first consumer (Property 1, 6.2), may
    refine it.
    """

    @st.composite
    def _gen(draw: Any):
        from tests.baselines.structural import StructuralView, Verdict

        names = draw(
            st.lists(_COLLECTION_NAME, min_size=0, max_size=5, unique=True)
        )
        collections = {
            name: draw(
                st.one_of(
                    st.none(),
                    st.integers(min_value=0, max_value=10**6),
                )
            )
            for name in names
        }
        checks = draw(
            st.lists(_CHECK_NAME, min_size=0, max_size=5, unique=True)
        )
        verdicts = {
            check: draw(st.sampled_from(list(Verdict))) for check in checks
        }
        return StructuralView(collections=collections, verdicts=verdicts)

    return _gen()


def render_perturbations() -> st.SearchStrategy:
    """Identity-preserving text transforms for a rendered reporter response.

    Yields a ``perturb(text: str) -> str`` callable that applies a drawn,
    seeded sequence of transforms none of which touch an identifying line
    (one carrying a Physical_Collection with its ``documents`` /
    ``unprovisioned`` terminal, a ``[OK]`` / ``[ERROR]`` / ``[SKIP]`` token,
    or a pipe-delimited verdict row): line permutation, whitespace
    expansion, blank-line insertion, insertion of a line naming no
    collection / count / verdict, and rewording of a purely decorative line.
    Consumed by Property 2 (step 6, 6.2), which asserts the relation is
    blind to exactly these.
    """

    @st.composite
    def _gen(draw: Any):
        ops = draw(
            st.lists(
                st.sampled_from(
                    ("permute", "whitespace", "blank", "noise", "reheading")
                ),
                min_size=1,
                max_size=5,
                unique=True,
            )
        )
        seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
        noise_word = draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=(),
                    whitelist_characters=(
                        "abcdefghijklmnopqrstuvwxyz "
                    ),
                ),
                min_size=1,
                max_size=30,
            )
        )

        def perturb(text: str) -> str:
            rng = random.Random(seed)
            lines = text.split("\n")
            for op in ops:
                if op == "permute":
                    rng.shuffle(lines)
                elif op == "whitespace":
                    lines = [
                        (ln + "   ") if ln.strip() else ln for ln in lines
                    ]
                elif op == "blank":
                    pos = rng.randrange(len(lines) + 1)
                    lines.insert(pos, "")
                elif op == "noise":
                    pos = rng.randrange(len(lines) + 1)
                    lines.insert(pos, "note " + noise_word.strip())
                elif op == "reheading":
                    lines = [_reword_decorative(ln, rng) for ln in lines]
            return "\n".join(lines)

        return perturb

    return _gen()


def triple_perturbations() -> st.SearchStrategy:
    """Single-element mutations of the Requirement 9 identifying triple.

    Yields a ``mutate(view) -> tuple[StructuralView, str]`` callable that
    applies **exactly one** of: drop a collection, add a collection, change
    one document count, or flip one verdict -- and returns the mutated view
    together with the name of the perturbed element, so Property 3 (step 6,
    6.2) can assert that exactly one finding names it. When the chosen op has
    no target in the view (e.g. "drop" on a view with no collections) the
    mutation falls back to "add", so exactly one change always occurs.

    Like :func:`structural_views`, the ``StructuralView`` type is imported
    lazily; step 6 owns it and is this generator's first consumer.
    """

    @st.composite
    def _gen(draw: Any):
        op = draw(st.sampled_from(("drop", "add", "count", "verdict")))
        seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
        add_count = draw(
            st.one_of(st.none(), st.integers(min_value=0, max_value=10**6))
        )

        def mutate(view: Any):
            from tests.baselines.structural import StructuralView, Verdict

            collections = dict(view.collections)
            verdicts = dict(view.verdicts)
            rng = random.Random(seed)

            effective = op
            if op == "drop" and not collections:
                effective = "add"
            elif op == "count" and not collections:
                effective = "add"
            elif op == "verdict" and not verdicts:
                effective = "add"

            if effective == "drop":
                name = rng.choice(sorted(collections))
                del collections[name]
            elif effective == "count":
                name = rng.choice(sorted(collections))
                collections[name] = _different_count(
                    collections[name], add_count
                )
            elif effective == "verdict":
                name = rng.choice(sorted(verdicts))
                verdicts[name] = _different_verdict(
                    verdicts[name], list(Verdict)
                )
            else:  # add a fresh collection guaranteed absent from the view
                name = "zz-added-" + format(seed, "x")
                while name in collections:
                    name += "x"
                collections[name] = add_count

            return (
                StructuralView(collections=collections, verdicts=verdicts),
                name,
            )

        return mutate

    return _gen()


# ---------------------------------------------------------------------------
# Small helpers for the perturbation generators
# ---------------------------------------------------------------------------


def _reword_decorative(line: str, rng: random.Random) -> str:
    """Reword ``line`` iff it is purely decorative, else return it unchanged.

    A decorative line carries no identifying content -- no Physical_Collection
    terminal, no verdict token, and no pipe-delimited row -- so rewording it
    cannot alter the Requirement 9 triple.
    """
    lowered = line.lower()
    if (
        " documents" in lowered
        or "unprovisioned" in lowered
        or "[ok]" in lowered
        or "[error]" in lowered
        or "[skip]" in lowered
        or "|" in line
    ):
        return line
    stripped = line.strip()
    if not stripped:
        return line
    suffix = "" if rng.random() < 0.5 else " section"
    return line.replace(stripped, stripped + suffix, 1)


def _different_count(old: int | None, candidate: int | None) -> int | None:
    """Return a document count guaranteed to differ from ``old``.

    ``None`` (unprovisioned) and ``0`` (provisioned-empty) are distinct
    values the relation must not conflate, so the returned value differs from
    ``old`` under that distinction.
    """
    if old is None:
        return candidate if candidate is not None else 0
    if candidate is not None and candidate != old:
        return candidate
    return old + 1


def _different_verdict(old: Any, all_verdicts: list) -> Any:
    """Return a ``Verdict`` value guaranteed to differ from ``old``."""
    for verdict in all_verdicts:
        if verdict != old:
            return verdict
    return old
