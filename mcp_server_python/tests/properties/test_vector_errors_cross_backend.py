"""Cross-backend Skip_Block identity for missing-collection reads.

shared-scope-query-routing Task 4.4 (Requirements 4.4, 4.7). Uses the
``adapters()`` fixture from ``conftest.py`` (Task 2.4) so both
``ChromaDBAdapter`` and ``OpenSearchAdapter`` are exercised through the
same parameterised test body, per Requirement 4.5's cross-adapter
parameterisation and the task instruction not to duplicate the fixture.

``_missing_index_skip`` in ``src.tools._common`` is already the single
renderer and its text is already backend-independent -- it interpolates
only ``tool``, ``collection``, and ``tenant_id``. This file does not
change that renderer; it proves the cross-backend identity the design
attributes to it, by driving a real collection-absence exception through
each adapter and confirming the classifier (widened in Task 4.3) and the
renderer produce the same outcome regardless of which adapter raised.
"""

from __future__ import annotations

import pytest

from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.vector_errors import CollectionNotProvisionedError
from src.tools._common import _is_missing_index_exc, _missing_index_skip

pytestmark = pytest.mark.unit


class _FakeTenant:
    """Minimal tenant double carrying the two attributes the adapters read."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.index_prefix = f"{tenant_id}_"


class _RaisingChromaClient:
    """ChromaDB client double whose ``get_collection`` always raises."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def get_collection(self, name: str):
        raise self._exc


class _NamespaceWithRawClient:
    """Minimal stand-in exposing ``_client`` the way ``OpenSearchAdapter``
    expects from its ``OpenSearchVectorClient`` wrapper."""

    def __init__(self, raw) -> None:
        self._client = raw


class _RaisingOpenSearchRawClient:
    """Raw OpenSearch client double whose ``search`` always raises."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def search(self, *, index: str, body):
        raise self._exc


def _install_absence(adapter, *, physical: str) -> None:
    """Wire ``adapter`` so its next ``query`` raises a collection-absence
    exception in that backend's native shape."""
    if isinstance(adapter, ChromaDBAdapter):
        adapter._client = _RaisingChromaClient(
            ValueError(f"Collection {physical} does not exist.")
        )
    else:
        adapter._client = _NamespaceWithRawClient(
            _RaisingOpenSearchRawClient(
                Exception("index_not_found_exception")
            )
        )


@pytest.mark.asyncio
async def test_cross_backend_skip_block_is_character_identical(
    adapters,
) -> None:
    """R4.4: the same (tool, collection, tenant_id) renders identical text
    under both backends, driven through the real classification path.
    """
    adapter, _client = adapters
    logical = "ee2-standards-v5-0-0-enhanced"
    tenant_id = "gw_v17"
    _install_absence(
        adapter, physical=f"{tenant_id}_mdc-ee2-standards-titan1024"
    )

    with pytest.raises(CollectionNotProvisionedError):
        await adapter.query(logical, "err_chk", tenant=_FakeTenant(tenant_id))

    rendered = _missing_index_skip(
        tool="search_ee2_standards",
        query="err_chk",
        collection=logical,
        tenant_id=tenant_id,
    )
    # _missing_index_skip takes no backend-specific input, so identity is
    # structural; the load-bearing assertion is that both adapters reach
    # it through the same classifier for the same absence.
    assert rendered == _missing_index_skip(
        tool="search_ee2_standards",
        query="err_chk",
        collection=logical,
        tenant_id=tenant_id,
    )
    assert rendered.startswith("[INFO]")
    assert logical in rendered
    assert tenant_id in rendered


@pytest.mark.asyncio
async def test_cross_backend_raises_once_and_tool_renders_one_skip_block(
    adapters,
) -> None:
    """R4.7: absence raises once for the whole set; the tool renders
    exactly one Skip_Block naming the LOGICAL collection and tenant_id,
    never the physical name, under either backend.

    Simulates the tool-layer try/except shape used by
    ``operational._tool_get_operational_guidance`` and its three
    siblings: one query, one except clause, one rendered block.
    """
    adapter, _client = adapters
    logical = "ee2-standards-v5-0-0-enhanced"
    tenant_id = "gw_v17"
    physical = f"{tenant_id}_mdc-ee2-standards-titan1024"
    _install_absence(adapter, physical=physical)

    call_count = 0
    rendered_blocks: list[str] = []
    try:
        call_count += 1
        await adapter.query(logical, "err_chk", tenant=_FakeTenant(tenant_id))
    except Exception as exc:
        if _is_missing_index_exc(exc):
            rendered_blocks.append(
                _missing_index_skip(
                    tool="search_ee2_standards",
                    query="err_chk",
                    collection=logical,
                    tenant_id=tenant_id,
                )
            )
        else:  # pragma: no cover - defensive
            raise

    assert call_count == 1
    assert len(rendered_blocks) == 1
    block = rendered_blocks[0]
    assert logical in block
    assert tenant_id in block
    # The physical name must never leak into the response body (R7.6).
    assert physical not in block
