"""Property test for the addressed-set and hit-provenance checks (Task 8.2).

Feature: default-tenant-freeze-retirement (SDD Phase 80).

Covers Property 13: Addressed-set invariance and hit provenance. Two
clauses, kept in one property because they are two halves of the same
Requirement 11 criterion 2 check, but asserted with separate failure
messages because they fail for different reasons -- "you dropped a
collection" is a different investigation from "a hit lost its
provenance", mirroring how ``structural.py``'s collection and verdict
findings are kept distinguishable.

Nothing here is wired into ``test_default_tenant_byte_equivalence.py``
yet. Byte-equality stays in force for all four Query_Tool scenarios
through this task; Task 8.3 is the atomic step that swaps this check in
alongside the R6.2 supersession.
"""

from __future__ import annotations

import asyncio
import builtins
import json
import socket
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.data.read_router import resolve_read_targets
from tests.baselines.addressing import (
    TOOL_LOGICAL_COLLECTIONS,
    addressed_set,
    check_hit_provenance,
)
from tests.properties.conftest import profiles

pytestmark = pytest.mark.property

_QUERY_TOOLS = tuple(TOOL_LOGICAL_COLLECTIONS)

_EXPECTED_PATH = (
    Path(__file__).resolve().parents[1]
    / "baselines"
    / "expected"
    / "addressed_sets.json"
)


def _raise_on_io(*_args, **_kwargs):
    """Stand-in that fails if ``addressed_set`` attempts I/O."""
    raise AssertionError(
        "addressed_set attempted socket or file I/O during resolution "
        "(Property 13 purity violation)"
    )


# Feature: default-tenant-freeze-retirement, Property 13: Addressed-set
# invariance and hit provenance
@settings(max_examples=100, deadline=None)
@given(
    tool_name=st.sampled_from(_QUERY_TOOLS),
    profile=st.sampled_from(profiles()),
)
def test_p13_addressed_set_matches_recorded_expectation_and_is_pure(
    tool_name: str, profile: str
) -> None:
    """The Default_Tenant addressed set equals the recorded expectation.

    Recorded in ``tests/baselines/expected/addressed_sets.json``. This is
    the check a quality score structurally cannot make: dropping one
    member of a two-member Resolved_Collection_Set may leave ``coverage``
    untouched -- the surviving member still answers every corpus query --
    while the tool now sees half of what it should (Requirement 11
    criterion 4).

    Purity is asserted structurally, not by inspection, mirroring
    ``test_scope_routing.py``'s Property 9 technique: ``socket.socket``
    and ``builtins.open`` are replaced with raising doubles around the
    call, so an accidental network request, filesystem read, or
    collection-existence probe fails loudly rather than passing silently.
    """
    with patch.object(socket, "socket", side_effect=_raise_on_io), \
            patch.object(builtins, "open", side_effect=_raise_on_io):
        actual = addressed_set(tool_name, tenant=None, profile=profile)

    expected = json.loads(_EXPECTED_PATH.read_text())
    assert actual == frozenset(expected[tool_name][profile]), (
        f"addressed_set({tool_name!r}, profile={profile!r}) = "
        f"{sorted(actual)}, expected "
        f"{sorted(expected[tool_name][profile])}"
    )


# Feature: default-tenant-freeze-retirement, Property 13: Addressed-set
# invariance and hit provenance (provenance clause)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    tool_name=st.sampled_from(_QUERY_TOOLS),
    hit_count=st.integers(min_value=0, max_value=5),
)
def test_p13_hits_carry_provenance_within_the_addressed_set(
    tool_name: str, hit_count: int, adapters
) -> None:
    """Every hit from either Vector_Adapter carries valid provenance.

    Sweeps both ``ChromaDBAdapter`` and ``OpenSearchAdapter`` through the
    shared ``adapters()`` fixture (``tests/properties/conftest.py``) --
    provenance asserted on one backend and broken on the other is exactly
    the shape of bug this would otherwise miss. Seeds the addressed
    Default_Tenant collection(s) for ``tool_name`` with ``hit_count``
    canned hits and asserts every returned row's ``physical_collection``
    is non-empty and a member of :func:`addressed_set`.
    """
    adapter, fake_client = adapters
    profile = adapter._profile.short_name
    expected = addressed_set(tool_name, tenant=None, profile=profile)

    logical_collections = TOOL_LOGICAL_COLLECTIONS[tool_name]
    canned_hits = [
        {"id": f"hit-{i}", "content": "x", "score": 0.5}
        for i in range(hit_count)
    ]

    all_hits: list[dict] = []
    for logical in logical_collections:
        resolved = resolve_read_targets(logical, None, profile=profile)
        physical_name = resolved.physical_names[0]
        if hasattr(fake_client, "add_collection"):
            fake_client.add_collection(
                physical_name,
                response={
                    "ids": [[h["id"] for h in canned_hits]],
                    "documents": [[h["content"] for h in canned_hits]],
                    "metadatas": [[{} for _ in canned_hits]],
                    "distances": [[0.1 for _ in canned_hits]],
                },
            )
        else:
            fake_client.add_index(
                physical_name,
                hits=[
                    {
                        "_id": h["id"],
                        "_score": 0.9,
                        "_source": {"content": h["content"], "metadata": {}},
                    }
                    for h in canned_hits
                ],
            )

        hits = asyncio.run(
            adapter.query(logical, "probe query", k=max(hit_count, 1))
        )
        all_hits.extend(hits)

    findings = check_hit_provenance(all_hits, expected)
    assert findings == [], "\n".join(findings)
