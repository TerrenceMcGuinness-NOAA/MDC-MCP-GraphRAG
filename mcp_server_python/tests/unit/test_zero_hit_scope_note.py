"""Zero-hit scope annotation + diagnostic confinement.

shared-scope-query-routing Task 7.5 (Requirements 6.6, 6.8, 7.7).

``_zero_hit_scope_note`` names each addressed Physical_Collection that is
unprovisioned or provisioned-empty (with its Collection_Scope) when a read
returns zero hits under a prefixed tenant, and returns nothing at all
under the Default_Tenant (empty prefix) so the rendered gw body stays
byte-equivalent and the condition is left to the log channel. The note is
a plain body note, never a Routing_Diagnostic: the ``[routing]``
diagnostic string is confined to ``log.info`` and must never appear in
tool output on any path.
"""
from __future__ import annotations

import pytest

from src.data.read_router import (
    CollectionCondition,
    RoutingDiagnostic,
)
from tests.conftest import MockVectorDB
from src.tools._common import _zero_hit_scope_note

pytestmark = pytest.mark.unit


class _FakeTenant:
    def __init__(self, tenant_id: str, index_prefix: str) -> None:
        self.tenant_id = tenant_id
        self.index_prefix = index_prefix


_DOCS = "global-workflow-docs-v8-0-0"
_EE2 = "ee2-standards-v5-0-0-enhanced"


@pytest.mark.asyncio
async def test_default_tenant_returns_no_note_and_probes_nothing():
    """R6.8: empty prefix -> [] with no backend touch (byte-equivalence)."""
    vector = MockVectorDB()
    note = await _zero_hit_scope_note(
        vector, tenant=None, collections=_EE2, profile="titan1024"
    )
    assert note == []
    # Gate returns before any collection_condition probe.
    assert not any(c[0] == "collection_condition" for c in vector.call_log)


@pytest.mark.asyncio
async def test_default_tenant_empty_prefix_object_returns_no_note():
    """A tenant object with empty index_prefix is also gated off."""
    vector = MockVectorDB()
    note = await _zero_hit_scope_note(
        vector,
        tenant=_FakeTenant("gw", ""),
        collections=_EE2,
        profile="titan1024",
    )
    assert note == []


@pytest.mark.asyncio
async def test_prefixed_tenant_names_unprovisioned_member_and_scope():
    """R7.7: an unprovisioned member is named with its scope + condition."""
    v17 = _FakeTenant("gw_v17", "gw_v17_")
    # Hybrid docs under gw_v17 -> two members: shared (populated) +
    # prefixed (unprovisioned).
    vector = MockVectorDB(
        condition_overrides={
            "mdc-workflow-docs-titan1024":
                CollectionCondition.PROVISIONED_POPULATED,
            "gw_v17_mdc-workflow-docs-titan1024":
                CollectionCondition.UNPROVISIONED,
        }
    )
    note = await _zero_hit_scope_note(
        vector, tenant=v17, collections=_DOCS, profile="titan1024"
    )
    text = "\n".join(note)
    assert "gw_v17_mdc-workflow-docs-titan1024" in text
    assert "shared" in text  # the Hybrid_Domain member's scope
    assert "unprovisioned" in text
    # The populated shared member is NOT named (genuine reach).
    assert "mdc-workflow-docs-titan1024 (shared): " not in text.replace(
        "gw_v17_mdc-workflow-docs-titan1024", "X"
    )


@pytest.mark.asyncio
async def test_prefixed_tenant_names_provisioned_empty_member():
    """R7.7: provisioned-empty is named distinctly from unprovisioned."""
    v17 = _FakeTenant("gw_v17", "gw_v17_")
    vector = MockVectorDB(
        condition_overrides={
            "mdc-ee2-standards-titan1024":
                CollectionCondition.PROVISIONED_EMPTY,
        }
    )
    note = await _zero_hit_scope_note(
        vector, tenant=v17, collections=_EE2, profile="titan1024"
    )
    text = "\n".join(note)
    assert "mdc-ee2-standards-titan1024" in text
    assert "provisioned-empty" in text


@pytest.mark.asyncio
async def test_all_populated_members_yield_no_note():
    """A genuine no-match (every member populated) adds no annotation."""
    v17 = _FakeTenant("gw_v17", "gw_v17_")
    vector = MockVectorDB(
        condition_overrides={
            "mdc-ee2-standards-titan1024":
                CollectionCondition.PROVISIONED_POPULATED,
        }
    )
    note = await _zero_hit_scope_note(
        vector, tenant=v17, collections=_EE2, profile="titan1024"
    )
    assert note == []


@pytest.mark.asyncio
async def test_note_never_contains_the_routing_diagnostic_marker():
    """R6.6: the note is a body note, never a Routing_Diagnostic string."""
    v17 = _FakeTenant("gw_v17", "gw_v17_")
    vector = MockVectorDB(
        condition_overrides={
            "mdc-ee2-standards-titan1024":
                CollectionCondition.UNPROVISIONED,
        }
    )
    note = await _zero_hit_scope_note(
        vector, tenant=v17, collections=_EE2, profile="titan1024"
    )
    text = "\n".join(note)
    assert text  # non-empty (an unprovisioned member was flagged)
    assert "[routing]" not in text


def test_routing_diagnostic_marker_is_what_we_confine():
    """Sanity: the confined diagnostic string is the ``[routing]`` line."""
    rendered = RoutingDiagnostic(
        tenant_id="gw_v17",
        logical=_DOCS,
        profile="titan1024",
        members=(("mdc-workflow-docs-titan1024", "shared", False),),
        transport="builtin",
    ).render()
    assert rendered.startswith("[routing]")
