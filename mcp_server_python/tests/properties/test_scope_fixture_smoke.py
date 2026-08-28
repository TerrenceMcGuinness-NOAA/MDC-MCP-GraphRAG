"""Self-checks for the Task 2.4 generators and ``adapters()`` fixture.

Not a property test for P1 through P10 -- those belong to their own
tasks (Requirement 13.7 tags them separately). This module verifies the
deliverable itself: the four generator functions return the expected,
catalog-derived content, and the cross-adapter fixture yields a usable,
call-recording double for each backend with no network access.

Marked ``unit`` rather than ``property`` since nothing here is a
Hypothesis-driven property.
"""

from __future__ import annotations

import pytest

from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.opensearch_adapter import OpenSearchAdapter
from tests.properties.conftest import (
    logical_collections,
    prefixed_tenants,
    profiles,
    tenants,
)

pytestmark = pytest.mark.unit


def test_logical_collections_matches_production_index_map():
    """The five keys come from PRODUCTION_INDICES_BY_PROFILE, not a literal."""
    from src.config.aws_config import PRODUCTION_INDICES_BY_PROFILE

    cols = logical_collections()
    assert len(cols) == 5
    assert set(cols) == set(PRODUCTION_INDICES_BY_PROFILE["titan1024"])
    assert set(cols) == set(PRODUCTION_INDICES_BY_PROFILE["mpnet768"])


def test_tenants_reads_the_catalog_not_a_hardcoded_list():
    """Every tenant in tenants.yaml appears, in catalog order."""
    ids = [t.tenant_id for t in tenants()]
    assert ids == ["gw", "gw_sfs", "gw_jedi_gfs", "gw_v17", "gw_gefs_v12"]


def test_prefixed_tenants_excludes_only_the_default_tenant():
    """gw has an empty index_prefix and must not appear; all others must."""
    prefixed_ids = {t.tenant_id for t in prefixed_tenants()}
    assert "gw" not in prefixed_ids
    assert prefixed_ids == {
        "gw_sfs", "gw_jedi_gfs", "gw_v17", "gw_gefs_v12",
    }
    assert all(t.index_prefix for t in prefixed_tenants())


def test_profiles_includes_mapped_and_unmapped():
    """titan1024/mpnet768 have index maps; nova1024 deliberately does not."""
    from src.config.aws_config import PRODUCTION_INDICES_BY_PROFILE

    p = profiles()
    assert "titan1024" in p
    assert "mpnet768" in p
    assert "nova1024" in p
    assert "nova1024" not in PRODUCTION_INDICES_BY_PROFILE


class TestAdaptersFixture:
    """Exercises the ``adapters()`` fixture itself via parametrize.

    pytest fixtures cannot be called directly, so this class uses the
    fixture indirectly through normal dependency injection -- the point
    is to confirm both parameter ids are reachable and behave per the
    task's constraints, not to reimplement fixture machinery.
    """

    def test_yields_a_connected_adapter_with_explicit_embedding_function(
        self, adapters
    ):
        adapter, _double = adapters
        assert isinstance(adapter, (ChromaDBAdapter, OpenSearchAdapter))
        assert adapter._connected is True
        assert adapter._embedding_function is not None
        # No provider should have been constructed: the explicit
        # embedding_function makes the adapter hermetic (no Bedrock,
        # no sentence-transformers).
        assert adapter._provider is None
        assert adapter._provider_error is None

    @pytest.mark.asyncio
    async def test_double_records_every_call(self, adapters):
        adapter, double = adapters
        if isinstance(adapter, ChromaDBAdapter):
            double.add_collection("existing", response={
                "ids": [["doc-1"]],
                "documents": [["hello world"]],
                "metadatas": [[{"source": "test"}]],
                "distances": [[0.1]],
            })
        else:
            double.add_index(
                "existing",
                hits=[
                    {
                        "_id": "doc-1",
                        "_score": 0.9,
                        "_source": {
                            "content": "hello world",
                            "metadata": {"source": "test"},
                        },
                    }
                ],
            )

        results = await adapter.query("existing", "hello", k=5)

        assert len(results) == 1
        assert results[0]["id"] == "doc-1"
        assert len(double.calls) >= 1

    @pytest.mark.asyncio
    async def test_missing_collection_raises_without_network_access(
        self, adapters
    ):
        adapter, double = adapters
        with pytest.raises(Exception):
            await adapter.query("does-not-exist", "hello", k=5)
        assert len(double.calls) >= 1


def test_both_backend_ids_are_collected(pytestconfig):
    """Meta-check mirroring Task 2.5's guard.

    Confirms that this module's own indirect use of ``adapters()``
    produces both the ``chromadb`` and ``opensearch`` parameter ids so
    the fixture is exercised for both backends here too, without
    waiting on the separate Task 2.5 module.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            __file__ + "::TestAdaptersFixture", "--collect-only", "-q",
        ],
        capture_output=True,
        text=True,
        cwd=pytestconfig.rootpath,
    )
    assert "chromadb" in result.stdout
    assert "opensearch" in result.stdout
