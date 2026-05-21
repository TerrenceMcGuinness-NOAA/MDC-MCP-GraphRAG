# Design Document: Backend-Agnostic Refactor

## Overview

The Python MCP server's protocol layer (`VectorDBProtocol`, `GraphDBProtocol`) is well-designed and backend-agnostic. The wiring code above the protocols, however, accidentally bakes in AWS assumptions. This refactor introduces a backend registry pattern, moves backend-specific logic into adapters, and replaces the untyped health check dict with a typed `HealthReport` dataclass. The result: a new backend can be added by registering a single builder file. No tool module changes, no selector changes, no consumer changes.

## Architecture

### Before (current state)

```
ServerConfig (db_backend = "aws" | "legacy")
       │
       ▼
backend_selector.create_data_access()
       │
       ├─ if "legacy" → raise UnsupportedBackendError  ◄── HARD BLOCK
       └─ if "aws"    → build OpenSearch + Neptune
                ▲
                │ direct call
                │
config/aws_config.py.resolve_index() ◄── imported by gap_detector + semantic_search
```

### After (registry pattern)

```
ServerConfig (db_backend = explicit string, no default)
       │
       ▼
backend_selector.create_data_access()
       │
       ▼
BACKEND_REGISTRY[config.db_backend].build(config)
       │
       ├─ "aws"    → AwsBackendBuilder    → OpenSearchAdapter + NeptuneAdapter
       ├─ "mock"   → MockBackendBuilder   → MockVectorDB + MockGraphDB
       └─ "<new>"  → <NewBuilder>         → <NewVectorAdapter> + <NewGraphAdapter>

OpenSearchAdapter.resolve_collection(logical) → physical index name
                  health_check() → HealthReport (logical names)

GapDetector → consumes HealthReport directly, no aws_config import
SemanticSearch → calls vector_db.resolve_collection(), no aws_config import
```

## Components and Interfaces

### Component 1: `BackendBuilder` Abstract Base Class

**Location**: `mcp_server_python/src/data/backend_selector.py`

```python
from abc import ABC, abstractmethod
from src.config.environment import ServerConfig
from src.data.protocols import VectorDBProtocol, GraphDBProtocol


class BackendBuilder(ABC):
    """Factory that constructs adapter pair from ServerConfig.

    Implement one per backend. Register in BACKEND_REGISTRY.
    """

    @abstractmethod
    def build(
        self, config: ServerConfig
    ) -> tuple[VectorDBProtocol | None, GraphDBProtocol | None]:
        """Construct adapters from config.

        Either side may return None when its endpoint/configuration
        is missing — the selector handles graceful degrade.
        """
```

### Component 2: `BACKEND_REGISTRY` and `register_backend()`

**Location**: `mcp_server_python/src/data/backend_selector.py`

```python
BACKEND_REGISTRY: dict[str, BackendBuilder] = {}


def register_backend(name: str, builder: BackendBuilder) -> None:
    """Register a backend builder. Idempotent: re-registering replaces."""
    if not name:
        raise ValueError("backend name must be non-empty")
    BACKEND_REGISTRY[name] = builder


def list_registered_backends() -> list[str]:
    """Return sorted list of registered backend names — for error messages."""
    return sorted(BACKEND_REGISTRY)
```

The AWS backend registers itself at module load:

```python
class AwsBackendBuilder(BackendBuilder):
    def build(self, config):
        return _build_vector_db(config), _build_graph_db(config)


register_backend("aws", AwsBackendBuilder())
```

### Component 3: Updated `create_data_access()`

```python
async def create_data_access(
    config: ServerConfig,
    *,
    vector_db=None,  # test injection
    graph_db=None,
) -> UnifiedDataAccess:
    if vector_db is not None or graph_db is not None:
        # Test-injection path unchanged from before
        ...

    builder = BACKEND_REGISTRY.get(config.db_backend)
    if builder is None:
        raise UnsupportedBackendError(
            f"db_backend={config.db_backend!r} not registered. "
            f"Available: {list_registered_backends()}. "
            f"Hint: AWS users set DB_BACKEND=aws."
        )

    v, g = builder.build(config)
    facade = UnifiedDataAccess(
        vector_db=v, graph_db=g, backend=config.db_backend
    )
    await _connect_with_degrade(facade)
    return facade
```

### Component 4: `HealthReport` Dataclass

**Location**: `mcp_server_python/src/data/protocols.py`

```python
from dataclasses import dataclass, field
from typing import Any, Literal

HealthStatus = Literal["healthy", "degraded", "unhealthy"]


@dataclass
class HealthReport:
    """Backend-uniform health status.

    Adapters MUST populate `collections` using LOGICAL collection names
    so consumers (gap detector, knowledge base status tool) can interpret
    health uniformly across backends.
    """
    status: HealthStatus
    connected: bool
    collections: dict[str, int] = field(default_factory=dict)  # logical → count
    metrics: dict[str, Any] = field(default_factory=dict)       # backend-specific extras
    error: str | None = None
```

### Component 5: Protocol Additions

**Location**: `mcp_server_python/src/data/protocols.py`

Add to `VectorDBProtocol`:

```python
def resolve_collection(self, logical_name: str) -> str:
    """Translate a logical collection name to this backend's physical name.

    Implementations MUST return the input unchanged when no mapping exists.
    """
    ...

async def health_check(self, *, deep: bool = False) -> HealthReport:
    """Return a HealthReport describing adapter health."""
    ...
```

Same `health_check` signature on `GraphDBProtocol`.

### Component 6: OpenSearchAdapter Updates

**Location**: `mcp_server_python/src/data/opensearch_adapter.py`

```python
def resolve_collection(self, logical_name: str) -> str:
    """Map logical collection → physical OpenSearch index name."""
    from src.config.aws_config import resolve_index
    return resolve_index(logical_name, self._profile.short_name)


async def health_check(self, *, deep: bool = False) -> HealthReport:
    # Existing logic, but populate HealthReport with LOGICAL names
    raw = await self._raw_health_check(deep=deep)

    # Build reverse map: physical index name → logical collection
    from src.config.aws_config import PRODUCTION_INDICES_BY_PROFILE
    profile_map = PRODUCTION_INDICES_BY_PROFILE.get(self._profile.short_name, {})
    reverse = {phys: logical for logical, phys in profile_map.items()}

    collections: dict[str, int] = {}
    for phys_name, count in raw.get("indices_detail", {}).items():
        logical = reverse.get(phys_name, phys_name)  # passthrough for unmapped
        collections[logical] = count

    return HealthReport(
        status=raw["status"],
        connected=raw["connected"],
        collections=collections,
        metrics={
            "endpoint": self._endpoint,
            "cluster_status": raw.get("cluster_status"),
            "queries_executed": self._metrics["queries_executed"],
        },
    )
```

### Component 7: GapDetector Cleanup

**Location**: `mcp_server_python/src/manifest/gap_detector.py`

Remove the `from src.config.aws_config import resolve_index` import. Replace `_lookup_actual_count()` with a direct lookup against `HealthReport.collections`:

```python
async def _get_actual_counts(self, vector_db) -> dict[str, int] | None:
    try:
        report = await vector_db.health_check(deep=True)
    except Exception as exc:
        log.warning("health_check failed: %s", exc)
        return None

    return dict(report.collections)  # already keyed by logical name


def _lookup_actual_count(
    self, collection: str, entries, actual_counts: dict[str, int]
) -> int:
    return actual_counts.get(collection, 0)  # direct lookup, no resolve_index
```

### Component 8: Semantic Search Tool Cleanup

**Location**: `mcp_server_python/src/tools/semantic_search.py`

Same pattern — remove `aws_config` import, use `vector_db.resolve_collection()` where physical names were needed.

### Component 9: Mock Backend Registration

**Location**: `mcp_server_python/tests/conftest.py`

```python
from src.data.backend_selector import BackendBuilder, register_backend


class MockBackendBuilder(BackendBuilder):
    """Test-only backend wiring up MockVectorDB + MockGraphDB."""

    def build(self, config):
        from tests.conftest import MockVectorDB, MockGraphDB
        return MockVectorDB(), MockGraphDB()


# Register at conftest load so all tests see "mock" as a valid backend
register_backend("mock", MockBackendBuilder())
```

### Component 10: ServerConfig Default Changes

**Location**: `mcp_server_python/src/config/environment.py`

```python
@dataclass(frozen=True)
class ServerConfig:
    db_backend: str = ""              # NO default — must be explicit
    embedding_profile: str = "default"  # backends resolve "default" themselves
    # ... rest unchanged ...


def load_config(env=None, *, enabled_modules=None) -> ServerConfig:
    source = env if env is not None else os.environ
    backend = (source.get("DB_BACKEND") or "").strip().lower()

    if not backend:
        from src.data.backend_selector import list_registered_backends
        raise ConfigError(
            f"DB_BACKEND must be set explicitly. "
            f"Available backends: {list_registered_backends()}. "
            f"Hint: set DB_BACKEND=aws for the AWS backend "
            f"(Neptune + OpenSearch)."
        )

    # Rest of validation unchanged
```

## Data Models

The single new data model is `HealthReport` (described in Component 4). All other types are existing.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `DB_BACKEND` unset | `ConfigError` listing registered backends |
| `DB_BACKEND` set to unregistered name | `UnsupportedBackendError` listing registered backends |
| Backend builder raises during `build()` | Propagates as configuration error (not graceful degrade — the operator misconfigured) |
| Adapter `connect()` raises | Existing graceful-degrade behavior preserved (`_connect_with_degrade` nulls the slot) |
| `resolve_collection()` called with unknown name | Adapter returns input unchanged (passthrough) |
| `health_check()` returns empty `collections` despite `status=healthy` | Existing warning log fires; gap detector renders the "actual counts unavailable" notice from the search-deduplication spec |

## Testing Strategy

### Existing tests (must continue to pass)

All 752 unit tests pass after the refactor. The key risk areas:

- `tests/unit/test_data_layer.py` — registry pattern + connect_with_degrade
- `tests/unit/test_mcp_server.py` — boot flow with backend selection
- `tests/unit/test_semantic_search_tools.py` — gap detector + list_all_sources
- `tests/parity/*` — schema parity (no changes expected)

### New tests (added by this refactor)

1. **Backend registry round-trip**: register a custom `"foo"` backend with a stub builder, verify `create_data_access(config_with_db_backend_foo)` calls the stub.
2. **Unknown backend error message**: set `DB_BACKEND=unknown`, verify error message contains "aws" and "mock".
3. **Empty `DB_BACKEND` raises ConfigError**: verify error message lists registered backends.
4. **HealthReport.collections uses logical names**: query OpenSearchAdapter health (with mock client), verify keys are `global-workflow-docs-v8-0-0` etc, not `mdc-workflow-docs-titan1024`.
5. **`resolve_collection` passthrough**: pass an unmapped logical name, verify it comes back unchanged.

## Correctness Properties

### Property 1: Registry Pattern Idempotency

*For any* sequence of `register_backend(name, builder)` calls, the final state of `BACKEND_REGISTRY[name]` SHALL equal the most recently registered builder for that name.

**Validates**: Requirements 1.6, 6.1

### Property 2: No AWS Imports in Tool Modules

*For any* file in `mcp_server_python/src/tools/`, the file SHALL NOT import from `mcp_server_python/src/config/aws_config.py`. (Verified via static check / grep in CI.)

**Validates**: Requirements 7.1, 7.2

### Property 3: HealthReport Logical Names

*For any* call to `OpenSearchAdapter.health_check(deep=True)` against a configured cluster, every key in `HealthReport.collections` SHALL be a logical collection name (e.g., `global-workflow-docs-v8-0-0`) that appears in `PRODUCTION_INDICES_BY_PROFILE[profile_short_name]`, OR a passthrough string when the underlying physical index has no logical mapping.

**Validates**: Requirements 3.4, 3.6

### Property 4: Tool Output Stability

*For any* tool invocation that succeeds against the AWS backend before the refactor, the same tool invocation SHALL produce byte-identical markdown output after the refactor.

**Validates**: Requirements 7.5, 8.1

### Property 5: Explicit Backend Selection

*For any* invocation of `load_config()` with `DB_BACKEND` unset or empty, the function SHALL raise `ConfigError` and SHALL NOT return a `ServerConfig`.

**Validates**: Requirement 5.2

## Files Modified

**Modified**:
- `mcp_server_python/src/data/backend_selector.py` (registry pattern, +50/-20 lines)
- `mcp_server_python/src/data/protocols.py` (add `HealthReport`, `resolve_collection`, +30 lines)
- `mcp_server_python/src/data/opensearch_adapter.py` (`resolve_collection`, refactor `health_check` to return `HealthReport`, +20/-15 lines)
- `mcp_server_python/src/data/neptune_adapter.py` (return `HealthReport` from `health_check`, +10/-5 lines)
- `mcp_server_python/src/config/environment.py` (no default for `db_backend`, embedding default = "default", +10/-5 lines)
- `mcp_server_python/src/manifest/gap_detector.py` (consume `HealthReport.collections` directly, -15 lines)
- `mcp_server_python/src/tools/semantic_search.py` (use `vector_db.resolve_collection`, -10 lines)
- `mcp_server_python/tests/conftest.py` (register `"mock"` backend, +20 lines)
- `.kiro/steering/01-architecture-context.md` (one-paragraph design summary, +10 lines)

**Created**:
- `mcp_server_python/tests/unit/test_backend_registry.py` (new tests, ~80 lines)

**Deleted**: None.

## Out of Scope

Explicitly NOT covered by this spec:
- Implementing `Neo4jLegacyAdapter` or `ChromaDBLegacyAdapter` (separate future spec)
- Migrating data between backends
- Changes to the Node.js MCP server
- Performance optimizations
- New embedding profile additions

A future spec `legacy-backend-adapters` will implement the actual Neo4j and ChromaDB adapters, drop them into the registry via `register_backend("legacy", LegacyBackendBuilder())`, and verify operation against a Parallel Works deployment.
