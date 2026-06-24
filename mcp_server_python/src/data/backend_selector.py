"""Backend selector — wires up adapters based on ``ServerConfig.db_backend``.

This is the module that :func:`src.mcp_server._create_data_access`
imports lazily. Returns a :pyclass:`UnifiedDataAccess` facade ready
for the tool layer.

Routing rules (Requirement 1.6, 1.8):

* ``db_backend == "aws"`` → :pyclass:`OpenSearchAdapter` +
  :pyclass:`NeptuneAdapter`. Both are connected eagerly so the
  ``mcp_health_check`` tool reports a real status from the first
  call. If either ``connect()`` raises, the selector logs the failure
  and returns the facade with that adapter slot set to ``None``,
  matching the graceful-degrade contract (R1.7).
* ``db_backend == "legacy"`` → not implemented here. The legacy
  Neo4j + ChromaDB path is the operator's responsibility on the
  on-prem deployment; on AgentCore we always use the AWS backends.
  Setting ``db_backend == "legacy"`` raises
  :pyexc:`UnsupportedBackendError` so the misconfiguration surfaces
  immediately rather than silently degrading.

The module is intentionally thin and dependency-injectable. Tests
can pass pre-built ``vector_db`` / ``graph_db`` arguments to
:func:`create_data_access` directly to bypass the AWS wiring.
"""

from __future__ import annotations

import logging
from typing import Any

from src.config.environment import ServerConfig
from src.data.protocols import GraphDBProtocol, VectorDBProtocol
from src.data.unified_data_access import UnifiedDataAccess

log = logging.getLogger(__name__)


class UnsupportedBackendError(RuntimeError):
    """Raised when ``ServerConfig.db_backend`` is not implemented here."""


async def create_data_access(
    config: ServerConfig,
    *,
    vector_db: VectorDBProtocol | None = None,
    graph_db: GraphDBProtocol | None = None,
) -> UnifiedDataAccess:
    """Build and connect a :pyclass:`UnifiedDataAccess` from ``config``.

    Parameters
    ----------
    config
        Server configuration loaded by
        :func:`src.config.environment.load_config`. The relevant
        fields are ``db_backend``, ``neptune_endpoint``,
        ``opensearch_endpoint``, and ``aws_region``.
    vector_db, graph_db
        Optional pre-built adapter instances. When supplied they
        bypass the config-driven construction entirely — used by
        tests that want to inject :pyclass:`MockVectorDB` /
        :pyclass:`MockGraphDB` from ``tests/conftest.py``.

    Returns
    -------
    UnifiedDataAccess
        Facade ready for tool-layer use. Always returns a non-None
        facade; individual adapter slots may be ``None`` when their
        connect call failed (degraded mode).
    """
    if config.db_backend not in ("aws", "legacy"):
        raise UnsupportedBackendError(
            f"DB_BACKEND={config.db_backend!r} is not a known value. "
            f'Valid values: "aws", "legacy".'
        )

    # If both adapters are pre-built, skip the AWS-wiring branch.
    if vector_db is not None or graph_db is not None:
        # Allow partial injection — fill the missing side from config
        # only if the caller explicitly passed `None` for it.
        v = vector_db if vector_db is not None else _build_vector_db(config)
        g = graph_db if graph_db is not None else _build_graph_db(config)
        facade = UnifiedDataAccess(
            vector_db=v, graph_db=g, backend=config.db_backend
        )
        await _connect_with_degrade(facade)
        return facade

    facade = UnifiedDataAccess(
        vector_db=_build_vector_db(config),
        graph_db=_build_graph_db(config),
        backend=config.db_backend,
    )
    await _connect_with_degrade(facade)
    return facade


# ── helpers ─────────────────────────────────────────────────────────────


def _build_vector_db(config: ServerConfig) -> VectorDBProtocol | None:
    """Construct an OpenSearchAdapter, ChromaDBAdapter, or return None on misconfig.

    Late-imports the adapter so test environments without
    ``opensearch-py`` installed can still exercise
    :func:`create_data_access` with injected mocks.
    """
    if config.db_backend == "legacy":
        try:
            from src.data.chromadb_adapter import ChromaDBAdapter
        except ImportError as exc:
            log.warning(
                "[WARN] ChromaDBAdapter unavailable (%s); "
                "vector_db will be disabled",
                exc,
            )
            return None
        return ChromaDBAdapter(host=config.chromadb_host, port=config.chromadb_port)

    if not config.opensearch_endpoint:
        log.warning(
            "[WARN] OPENSEARCH_ENDPOINT is empty; "
            "vector_db will be disabled"
        )
        return None
    try:
        from src.data.opensearch_adapter import OpenSearchAdapter
    except ImportError as exc:  # pragma: no cover - defensive
        log.warning(
            "[WARN] OpenSearchAdapter unavailable (%s); "
            "vector_db will be disabled",
            exc,
        )
        return None

    return OpenSearchAdapter(
        endpoint=config.opensearch_endpoint,
        region=config.aws_region,
    )


def _build_graph_db(config: ServerConfig) -> GraphDBProtocol | None:
    """Construct a NeptuneAdapter, Neo4jAdapter, or return None on misconfig."""
    if config.db_backend == "legacy":
        try:
            from src.data.neo4j_adapter import Neo4jAdapter
        except ImportError as exc:
            log.warning(
                "[WARN] Neo4jAdapter unavailable (%s); "
                "graph_db will be disabled",
                exc,
            )
            return None
        return Neo4jAdapter(
            uri=config.neo4j_uri,
            password=config.neo4j_password,
            user=config.neo4j_user,
        )

    if not config.neptune_endpoint:
        log.warning(
            "[WARN] NEPTUNE_ENDPOINT is empty; "
            "graph_db will be disabled"
        )
        return None
    try:
        from src.data.neptune_adapter import NeptuneAdapter
    except ImportError as exc:  # pragma: no cover - defensive
        log.warning(
            "[WARN] NeptuneAdapter unavailable (%s); "
            "graph_db will be disabled",
            exc,
        )
        return None

    return NeptuneAdapter(
        endpoint=config.neptune_endpoint,
        region=config.aws_region,
    )


async def _connect_with_degrade(facade: UnifiedDataAccess) -> None:
    """Eager-connect both adapters; null any that fail (R1.7).

    The Node.js ``HealthChecker`` only flips a side to ``unhealthy``
    when the adapter actively refuses; we do the same here by
    nulling the slot when the connect call raises. The tool layer
    then sees ``data.vector_db is None`` (or ``data.graph_db is
    None``) and surfaces ``[ERROR]`` markdown at call time —
    matching the documented degraded-mode contract.
    """
    if facade.vector_db is not None:
        try:
            await facade.vector_db.connect()
        except Exception as exc:
            log.warning(
                "[WARN] vector_db connect failed (%s); "
                "entering degraded mode for vector tools",
                exc,
            )
            # Best-effort close before nulling so we don't leak sockets.
            try:
                await facade.vector_db.close()
            except Exception:  # pragma: no cover - defensive
                pass
            facade.vector_db = None

    if facade.graph_db is not None:
        try:
            await facade.graph_db.connect()
        except Exception as exc:
            log.warning(
                "[WARN] graph_db connect failed (%s); "
                "entering degraded mode for graph tools",
                exc,
            )
            try:
                await facade.graph_db.close()
            except Exception:  # pragma: no cover - defensive
                pass
            facade.graph_db = None


__all__ = ["create_data_access", "UnsupportedBackendError"]
