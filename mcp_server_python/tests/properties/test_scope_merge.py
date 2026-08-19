"""Property 10 -- result cap, provenance, and total ordering.

# Feature: shared-scope-query-routing, Property 10: Result cap, provenance,
# and total ordering

shared-scope-query-routing Task 7.4 (Requirements 3.4, 3.5, 3.7, 3.8,
13.7). For any Resolved_Collection_Set and any ``k`` in ``[1, 1000]``, a
multi-member read through a Vector_Adapter:

* returns at most ``k`` hits;
* stamps exactly one ``physical_collection`` on every hit, drawn from the
  addressed set;
* returns scores in non-increasing order;
* uses an injective ordering key ``(-score, member_index, hit_id)`` over
  the returned hits;
* returns no two hits sharing a normalized content digest.

Forced score collisions are a FIRST-CLASS generation strategy, not an
incidental case. OpenSearch clamps a ``bool.should`` of BM25 + k-NN onto
``[0.0, 1.0]``, so raw BM25 scores above 1.0 all land on exactly ``1.0``
and ties are common in production. A generator producing only distinct
scores would exercise the R3.7 member-position tie-break almost never and
would pass while the total-order guarantee was broken -- so scores are
drawn from a small discrete set including ``1.0`` with elevated weight,
alongside a continuous range.

Run against BOTH adapters. Hypothesis does not compose cleanly with a
function-scoped, per-example pytest fixture (the ``adapters()`` fixture
yields one adapter per test, but each example needs a fresh client), so
this module reuses that fixture's client doubles -- ``FakeChromaClient``,
``FakeOpenSearchRawClient`` -- and builds a fresh adapter per example,
parameterised over the same two backend ids the fixture exposes. That
runs the property against both adapters without leaking seeded state
across examples.

Per-member realism is preserved: within one Physical_Collection ids and
content are unique and hits arrive score-sorted (a real backend returns
them that way), which is exactly the input the single-member identity
path assumes. Duplicate ids, duplicate content, and colliding scores are
introduced ACROSS members, which is where the inner merge's tie-break and
de-duplication carry the guarantee.
"""

from __future__ import annotations

import asyncio
import hashlib
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.config.tenants import load_catalog
from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.opensearch_adapter import OpenSearchAdapter
from src.data.read_router import resolve_read_targets
from tests.properties.conftest import (
    FakeChromaClient,
    FakeOpenSearchRawClient,
    _NamespaceWithRawClient,
)

pytestmark = pytest.mark.property

_CATALOG = load_catalog("src/config/tenants.yaml")
_V17 = _CATALOG.by_id("gw_v17")

_WHITESPACE_RUN = re.compile(r"\s+")

#: Distinct content pool. Kept small and whitespace-free so cross-member
#: duplication is common and the digest is a simple sha256 of the word.
_CONTENT_POOL = ("alpha", "beta", "gamma", "delta", "epsilon")

#: Score strategy: a small discrete set with ``1.0`` heavily weighted (the
#: production clamp bucket) unioned with a continuous range.
_SCORE_ST = st.one_of(
    st.sampled_from([1.0, 1.0, 1.0, 1.0, 0.9, 0.5, 0.25, 0.0]),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False,
              allow_infinity=False),
)


def _embedding_function(texts: list[str]) -> list[list[float]]:
    return [[0.0, 0.0] for _ in texts]


@st.composite
def _member_specs(draw: st.DrawFn) -> list[list[dict]]:
    """Draw 1 or 2 members, each a per-member-valid list of hits.

    Within a member: distinct contents (hence distinct ids), each with a
    drawn score, sorted score-descending to mirror a real backend.
    """
    n_members = draw(st.integers(min_value=1, max_value=2))
    members: list[list[dict]] = []
    for _ in range(n_members):
        contents = draw(
            st.lists(
                st.sampled_from(_CONTENT_POOL),
                min_size=1,
                max_size=len(_CONTENT_POOL),
                unique=True,
            )
        )
        hits = [
            {
                "id": f"id-{content}",
                "content": content,
                "score": round(float(draw(_SCORE_ST)), 6),
            }
            for content in contents
        ]
        # Backend realism: a real query returns hits score-descending.
        hits.sort(key=lambda h: -h["score"])
        members.append(hits)
    return members


def _build_adapter(backend: str):
    if backend == "chromadb":
        adapter = ChromaDBAdapter(embedding_function=_embedding_function)
        client = FakeChromaClient()
        adapter._client = client
        adapter._connected = True
        return adapter, client
    adapter = OpenSearchAdapter(
        endpoint="https://example.invalid",
        embedding_function=_embedding_function,
    )
    raw = FakeOpenSearchRawClient()
    adapter._client = _NamespaceWithRawClient(raw)
    adapter._connected = True
    return adapter, raw


def _seed(backend: str, client, physical: str, hits: list[dict]) -> None:
    if backend == "chromadb":
        client.add_collection(
            physical,
            response={
                "ids": [[h["id"] for h in hits]],
                "documents": [[h["content"] for h in hits]],
                "metadatas": [[{} for _ in hits]],
                # score = 1 - distance/2  =>  distance = 2 * (1 - score)
                "distances": [[2.0 * (1.0 - h["score"]) for h in hits]],
            },
        )
    else:
        client.add_index(
            physical,
            hits=[
                {
                    "_id": h["id"],
                    "_score": h["score"],
                    "_source": {"content": h["content"], "metadata": {}},
                }
                for h in hits
            ],
        )


def _digest(hit: dict) -> str:
    text = hit.get("content") or hit.get("document") or hit.get("text") or ""
    normalized = _WHITESPACE_RUN.sub(" ", text.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("backend", ["chromadb", "opensearch"])
@settings(max_examples=150, deadline=None)
@given(members=_member_specs(), k=st.integers(min_value=1, max_value=1000))
def test_p10_cap_provenance_and_total_ordering(
    backend: str, members: list[list[dict]], k: int
) -> None:
    adapter, client = _build_adapter(backend)

    n_members = len(members)
    if n_members == 1:
        # Shared, non-hybrid, unprefixed default tenant -> one member.
        collection = "ee2-standards-v5-0-0-enhanced"
        tenant = None
    else:
        # Hybrid_Domain under a prefixed tenant -> exactly two members.
        collection = "global-workflow-docs-v8-0-0"
        tenant = _V17

    resolved = resolve_read_targets(
        collection, tenant, profile=adapter._profile.short_name
    )
    targets = resolved.targets
    assert len(targets) == n_members

    addressed = {t.physical for t in targets}
    index_of = {t.physical: i for i, t in enumerate(targets)}
    for target, member_hits in zip(targets, members):
        # A real backend honours ``n_results``/``size`` = k, returning at
        # most k hits per member; the fake clients do not, so truncate the
        # seed here to model that cap. The single-member identity path
        # relies on this backend-side cap rather than re-capping (R3.4
        # applies only to multi-member merges).
        _seed(backend, client, target.physical, member_hits[:k])

    results = asyncio.run(
        adapter.query(collection, "q", k=k, tenant=tenant)
    )

    # (a) At most k hits.
    assert len(results) <= k

    # (b) Exactly one physical_collection per hit, drawn from the set.
    for hit in results:
        physical = hit.get("physical_collection")
        assert physical in addressed

    # (c) Score sequence is non-increasing.
    scores = [float(hit["score"]) for hit in results]
    assert all(
        scores[i] >= scores[i + 1] for i in range(len(scores) - 1)
    )

    # (d) The ordering key (-score, member_index, hit_id) is injective.
    keys = [
        (
            -float(hit["score"]),
            index_of[hit["physical_collection"]],
            str(hit["id"]),
        )
        for hit in results
    ]
    assert len(set(keys)) == len(keys)

    # (e) No two survivors share a normalized content digest.
    digests = [_digest(hit) for hit in results]
    assert len(set(digests)) == len(digests)
