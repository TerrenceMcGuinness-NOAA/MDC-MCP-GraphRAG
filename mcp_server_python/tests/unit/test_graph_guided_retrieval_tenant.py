"""Tests for GraphGuidedRetrieval tenant forwarding (Task 8.1).

shared-scope-query-routing Requirements 1.5, 2.5.

``GraphGuidedRetrieval._safe_semantic_enrich`` used to call
``self._vector_db.query(...)`` with no ``tenant=`` argument, so every
GGSR-enriched read resolved as the Default_Tenant regardless of which
tenant was actually active -- tenancy was bypassed, not merely degraded.
This module asserts the tenant now reaches the adapter, and that the
latent physical-name default (``DEFAULT_SEMANTIC_COLLECTION``) resolves
cleanly through the R1.5 fallback rather than raising if it is ever the
effective value reaching the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.config.tenants import Tenant
from src.data.read_router import CollectionCondition
from src.graphrag.ggsr_traversal import GGSRTraversal
from src.graphrag.graph_guided_retrieval import (
    DEFAULT_SEMANTIC_COLLECTION,
    GraphGuidedRetrieval,
)


def _make_tenant(
    tenant_id: str = "gw_v17", index_prefix: str = "gw_v17_"
) -> Tenant:
    """Build a minimal Tenant for tests, mirroring the tenants.yaml shape."""
    return Tenant(
        tenant_id=tenant_id,
        repo_ref="ufs-community/global-workflow",
        branch="dev/gfs.v17",
        index_prefix=index_prefix,
        label_prefix="GW_V17_",
        workflow_subdir="dev-v17",
        lifecycle="staging",
    )


@dataclass
class _RecordingVectorDB:
    """Minimal VectorDBProtocol double that records every ``query`` call.

    Deliberately local to this test module rather than a change to the
    shared ``tests/conftest.py::MockVectorDB`` double, whose ``query``
    call-log entry does not capture the ``tenant`` kwarg and which is
    out of scope for Task 8.1.
    """

    hits: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    raise_on_query: BaseException | None = None

    async def connect(self) -> None:  # pragma: no cover - unused
        return None

    async def close(self) -> None:  # pragma: no cover - unused
        return None

    async def query(
        self,
        collection: str,
        query_text: str,
        *,
        k: int = 10,
        similarity_threshold: float = 0.0,
        where: dict[str, Any] | None = None,
        include_graph: bool = True,
        tenant: Any = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "collection": collection,
                "query_text": query_text,
                "k": k,
                "similarity_threshold": similarity_threshold,
                "where": where,
                "include_graph": include_graph,
                "tenant": tenant,
            }
        )
        if self.raise_on_query is not None:
            raise self.raise_on_query
        return list(self.hits)

    async def multi_collection_query(
        self, collections: list[str], query_text: str, **kwargs: Any
    ) -> list[dict[str, Any]]:  # pragma: no cover - unused
        return []

    async def list_collections(self) -> list[str]:  # pragma: no cover
        return []

    async def count_documents(
        self, collection: str
    ) -> int:  # pragma: no cover
        return 0

    async def collection_condition(
        self, physical_collection: str
    ) -> CollectionCondition:  # pragma: no cover - unused
        return CollectionCondition.PROVISIONED_POPULATED


class _EmptyGraphAdapter:
    """Graph adapter double whose queries always return no rows.

    ``GGSRTraversal.budget_aware_neighborhood`` is exercised for real
    (not stubbed out) so the test covers ``get_code_context`` end to
    end; a graph adapter that returns nothing keeps the GGSR half of
    the parallel gather cheap and deterministic.
    """

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return []


@pytest.fixture
def ggsr_engine_parts():
    """Return a ``(vector_db, ggsr)`` pair wired for get_code_context tests."""
    vector_db = _RecordingVectorDB(
        hits=[
            {
                "id": "doc-1",
                "content": "def setuprad(): ...",
                "metadata": {"source": "sorc/gfs.fd/setuprad.f"},
                "score": 0.9,
            }
        ]
    )
    ggsr = GGSRTraversal(_EmptyGraphAdapter())
    return vector_db, ggsr


class TestTenantForwarding:
    """R1.5, R2.5: the active tenant must reach the vector adapter."""

    @pytest.mark.asyncio
    async def test_tenant_reaches_adapter_via_get_code_context(
        self, ggsr_engine_parts
    ):
        vector_db, ggsr = ggsr_engine_parts
        engine = GraphGuidedRetrieval(
            ggsr=ggsr,
            vector_db=vector_db,
            default_collection="code-with-context-v8-0-0",
        )
        tenant = _make_tenant()

        await engine.get_code_context(
            "setuprad",
            collection="code-with-context-v8-0-0",
            tenant=tenant,
        )

        assert len(vector_db.calls) == 1
        assert vector_db.calls[0]["tenant"] is tenant

    @pytest.mark.asyncio
    async def test_default_tenant_none_preserves_existing_behaviour(
        self, ggsr_engine_parts
    ):
        """Omitting ``tenant`` must keep today's unprefixed-default shape."""
        vector_db, ggsr = ggsr_engine_parts
        engine = GraphGuidedRetrieval(
            ggsr=ggsr,
            vector_db=vector_db,
            default_collection="code-with-context-v8-0-0",
        )

        await engine.get_code_context(
            "setuprad", collection="code-with-context-v8-0-0"
        )

        assert len(vector_db.calls) == 1
        assert vector_db.calls[0]["tenant"] is None

    @pytest.mark.asyncio
    async def test_safe_semantic_enrich_forwards_tenant_directly(
        self, ggsr_engine_parts
    ):
        """Exercise ``_safe_semantic_enrich`` directly, not only via the
        public ``get_code_context`` entry point, since it is the method
        the task names as owning the forwarding change."""
        vector_db, ggsr = ggsr_engine_parts
        engine = GraphGuidedRetrieval(ggsr=ggsr, vector_db=vector_db)
        tenant = _make_tenant(tenant_id="gw_sfs", index_prefix="gw_sfs_")

        hits, meta = await engine._safe_semantic_enrich(
            "setuprad",
            "code-with-context-v8-0-0",
            5,
            0.1,
            None,
            tenant,
        )

        assert hits  # the stub returned hits; no error path taken
        assert meta == {}
        assert vector_db.calls[0]["tenant"] is tenant

    @pytest.mark.asyncio
    async def test_safe_semantic_enrich_default_tenant_is_none(
        self, ggsr_engine_parts
    ):
        """Calling without a tenant argument keeps ``tenant=None`` --
        today's behaviour for every existing caller that predates this
        change."""
        vector_db, ggsr = ggsr_engine_parts
        engine = GraphGuidedRetrieval(ggsr=ggsr, vector_db=vector_db)

        await engine._safe_semantic_enrich(
            "setuprad", "code-with-context-v8-0-0", 5, 0.1, None
        )

        assert vector_db.calls[0]["tenant"] is None


class TestPhysicalNameDefaultFallback:
    """The R1.5 fallback for the latent physical-name default.

    ``DEFAULT_SEMANTIC_COLLECTION`` is a *physical* name
    (``mdc-code-context-mpnet768``), not a key of
    ``PRODUCTION_INDICES_BY_PROFILE``, so ``scope_of()`` returns ``None``
    and the Read_Router takes its R1.5 ``tenant`` fallback: one prefixed
    member, ``fallback_applied=True``, ``classification="tenant-fallback"``,
    and no exception. This is latent today because
    ``graph_rag.get_code_context`` always passes an explicit
    ``collection=CODE_COLLECTION``, but this test is the guard that keeps
    it latent instead of becoming a live outage if a caller ever stops
    passing ``collection=``.
    """

    def test_default_semantic_collection_is_a_physical_name(self):
        """Sanity check the premise: the constant is not a logical key."""
        from src.config.aws_config import PRODUCTION_INDICES_BY_PROFILE

        for mapping in PRODUCTION_INDICES_BY_PROFILE.values():
            assert DEFAULT_SEMANTIC_COLLECTION not in mapping

    @pytest.mark.asyncio
    async def test_physical_name_default_resolves_without_raising(
        self, ggsr_engine_parts
    ):
        vector_db, ggsr = ggsr_engine_parts
        engine = GraphGuidedRetrieval(ggsr=ggsr, vector_db=vector_db)
        tenant = _make_tenant()

        # No explicit collection= -> the constructor default
        # (DEFAULT_SEMANTIC_COLLECTION) is what reaches the adapter.
        result = await engine.get_code_context("setuprad", tenant=tenant)

        assert result.metadata.get("semantic_error") is None
        assert len(vector_db.calls) == 1
        assert vector_db.calls[0]["collection"] == DEFAULT_SEMANTIC_COLLECTION
        assert vector_db.calls[0]["tenant"] is tenant

    def test_read_router_fallback_for_physical_name_default(self):
        """Assert the Read_Router side of the same guarantee directly."""
        from src.data.read_router import (
            CLASSIFICATION_TENANT_FALLBACK,
            resolve_read_targets,
        )

        tenant = _make_tenant()
        resolved = resolve_read_targets(
            DEFAULT_SEMANTIC_COLLECTION, tenant, profile="titan1024"
        )

        assert resolved.fallback_applied is True
        assert len(resolved.targets) == 1
        assert resolved.targets[0].prefixed is True
        assert resolved.targets[0].physical == (
            tenant.index_prefix + DEFAULT_SEMANTIC_COLLECTION
        )

    def test_read_router_fallback_default_tenant_unprefixed(self):
        """Under the Default_Tenant the same fallback yields one
        unprefixed member -- no exception, no empty set."""
        from src.data.read_router import resolve_read_targets

        resolved = resolve_read_targets(
            DEFAULT_SEMANTIC_COLLECTION, None, profile="titan1024"
        )

        assert resolved.fallback_applied is True
        assert len(resolved.targets) == 1
        assert resolved.targets[0].prefixed is False
        assert resolved.targets[0].physical == DEFAULT_SEMANTIC_COLLECTION
