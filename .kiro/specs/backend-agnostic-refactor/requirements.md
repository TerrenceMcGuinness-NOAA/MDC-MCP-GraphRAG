# Requirements Document

## Introduction

The Python MCP server (`mcp_server_python/`) was designed with backend-agnostic protocols (`VectorDBProtocol`, `GraphDBProtocol`) but the wiring code accidentally bakes in AWS assumptions. Both AWS (Neptune + OpenSearch) and Parallel Works (Neo4j + ChromaDB) remain prototype deployments — neither has organizational lock-in, and meteorological development staff are still evaluating both. This refactor removes the AWS-specific leaks above the protocol layer so that a new backend can be added by registering a single builder file, without touching the selector, the gap detector, the manifest tools, or any of the 51 tool modules.

This spec does **not** implement the Neo4j or ChromaDB legacy adapters — those are deferred to a separate future spec. The deliverable here is the architectural cleanup that makes such adapters drop-in additions.

## Glossary

- **Backend**: A pair of concrete adapters (one `VectorDBProtocol`, one `GraphDBProtocol`) plus a builder factory that wires them up from `ServerConfig`.
- **Backend_Registry**: The dict in `src/data/backend_selector.py` mapping backend name strings (`"aws"`, `"legacy"`, `"mock"`) to `BackendBuilder` instances.
- **Backend_Builder**: A factory class that constructs `VectorDBProtocol` and `GraphDBProtocol` instances from a `ServerConfig`. One implementation per backend.
- **Logical_Collection_Name**: A backend-independent name for a vector index or collection (e.g. `global-workflow-docs-v8-0-0`). Tool modules and the manifest reference these.
- **Physical_Index_Name**: The backend-specific name an adapter uses internally (e.g. `mdc-workflow-docs-titan1024` for OpenSearch with Titan embeddings, `global-workflow-docs-v8-0-0` for ChromaDB).
- **HealthReport**: A typed dataclass returned by `health_check()` that uses logical collection names, enabling consumers to interpret health status uniformly across backends.
- **Embedding_Profile**: An adapter-specific embedding model identifier. The string `"default"` means "whatever this backend considers default."
- **Mock_Backend**: A third backend registered alongside `aws` and `legacy` that wires up `MockVectorDB` and `MockGraphDB` from `tests/conftest.py`. Demonstrates the registry pattern works.

## Requirements

### Requirement 1: Backend Registry Pattern

**User Story:** As a platform engineer, I want adding a new backend to be a single-file registration, so that the selector code does not need modification when we add a third or fourth backend.

#### Acceptance Criteria

1. THE Backend_Selector SHALL define a `BackendBuilder` abstract base class with a single `build(config: ServerConfig) -> tuple[VectorDBProtocol | None, GraphDBProtocol | None]` method.
2. THE Backend_Selector SHALL define a `Backend_Registry` dict mapping backend name strings to `BackendBuilder` instances.
3. THE Backend_Registry SHALL contain entries for `"aws"` (production AWS backend) at module load time.
4. WHEN `create_data_access(config)` is called, THE Backend_Selector SHALL look up `config.db_backend` in the Backend_Registry and call the registered builder's `build()` method.
5. IF `config.db_backend` is not present in the Backend_Registry, THEN THE Backend_Selector SHALL raise `UnsupportedBackendError` with a message listing all currently registered backends.
6. THE Backend_Registry SHALL support runtime registration via a `register_backend(name: str, builder: BackendBuilder)` function so test code can register the Mock_Backend without modifying the production module.

### Requirement 2: Logical Collection Name Resolution

**User Story:** As a tool module author, I want to reference collections by their logical names without knowing which backend is active, so that the same tool code works on any backend.

#### Acceptance Criteria

1. THE VectorDBProtocol SHALL define a `resolve_collection(logical_name: str) -> str` method that returns the backend's physical name for a given logical collection.
2. THE OpenSearchAdapter SHALL implement `resolve_collection` by consulting `PRODUCTION_INDICES_BY_PROFILE` from `aws_config.py`, returning the embedding-profile-specific index name (e.g., `mdc-workflow-docs-titan1024` for `global-workflow-docs-v8-0-0` under the `titan1024` profile).
3. THE GapDetector SHALL call `vector_db.resolve_collection(logical_name)` instead of importing `resolve_index` from `aws_config.py`.
4. THE Semantic_Search_Tool SHALL call `vector_db.resolve_collection(logical_name)` instead of importing `resolve_index` from `aws_config.py`.
5. WHEN the OpenSearchAdapter has no mapping for a logical name, THE OpenSearchAdapter SHALL return the logical name unchanged.

### Requirement 3: HealthReport Dataclass

**User Story:** As a consumer of `health_check()` results (gap detector, knowledge base status tool, MCP health check tool), I want a typed, backend-uniform shape, so that I do not need to know which backend produced the report.

#### Acceptance Criteria

1. THE module `src/data/protocols.py` SHALL define a `HealthReport` dataclass with the fields: `status` (Literal[`"healthy"`, `"degraded"`, `"unhealthy"`]), `connected` (bool), `collections` (dict mapping logical collection name to integer document count), and `metrics` (dict for backend-specific extras).
2. THE VectorDBProtocol.`health_check()` method SHALL return a `HealthReport` instead of an untyped dict.
3. THE GraphDBProtocol.`health_check()` method SHALL return a `HealthReport` (collections may be empty for graph-only backends; metrics carries node and relationship counts).
4. THE OpenSearchAdapter SHALL populate `HealthReport.collections` using logical collection names (the keys consumers expect), not physical index names.
5. THE NeptuneAdapter SHALL populate `HealthReport.metrics` with at minimum `nodes_total`, `relationships_total`, and per-label counts.
6. THE GapDetector SHALL consume `HealthReport.collections` directly without performing physical-to-logical name translation.

### Requirement 4: Generic Embedding Profile Defaults

**User Story:** As a deployment operator, I want each backend to define its own default embedding profile, so that the same Python image works on AWS or Parallel Works without a profile configuration change.

#### Acceptance Criteria

1. THE ServerConfig SHALL change the default value of `embedding_profile` from `"titan1024"` to `"default"`.
2. WHEN the OpenSearchAdapter receives `embedding_profile == "default"`, THE OpenSearchAdapter SHALL resolve it to `"titan1024"` (the AWS production profile).
3. WHEN a future ChromaDBLegacyAdapter receives `embedding_profile == "default"`, THE ChromaDBLegacyAdapter SHALL resolve it to `"mpnet768"` (the Parallel Works production profile).
4. WHEN the operator explicitly sets `MCP_EMBEDDING_PROFILE` to a non-default value, THE adapter SHALL honor that value instead of its default.
5. IF the explicitly-set embedding profile is not registered in the embedding registry, THEN the existing `ConfigError` validation SHALL still fire as before.

### Requirement 5: Explicit Backend Selection

**User Story:** As a deployment operator, I want backend selection to be explicit rather than defaulting to AWS, so that deployment intent is unambiguous and I do not accidentally route to the wrong backend.

#### Acceptance Criteria

1. THE ServerConfig SHALL change the default value of `db_backend` from `"aws"` to an empty string.
2. IF `DB_BACKEND` is unset or empty when `load_config()` is called, THEN `load_config()` SHALL raise `ConfigError` with a message listing the available backend names from the Backend_Registry.
3. THE error message in criterion 2 SHALL include guidance that `DB_BACKEND=aws` selects the AWS backend (Neptune + OpenSearch) and that future backends can be selected by their registered names.
4. WHEN `DB_BACKEND=aws` is explicitly set, THE current behavior of `load_config()` SHALL be preserved exactly.
5. WHEN `DB_BACKEND=mock` is set in test environments, THE Backend_Registry SHALL route to the Mock_Backend builder.

### Requirement 6: Mock Backend as Reference Implementation

**User Story:** As a test author, I want the existing `MockVectorDB` and `MockGraphDB` registered as a third backend, so that the registry pattern is exercised in tests and serves as a template for future backends.

#### Acceptance Criteria

1. THE `tests/conftest.py` SHALL register a `"mock"` backend in the Backend_Registry via `register_backend()`.
2. THE Mock_Backend builder SHALL construct `MockVectorDB` and `MockGraphDB` instances from `ServerConfig` ignoring all endpoint and region fields.
3. WHEN any existing test sets `DB_BACKEND=mock` and calls `load_config()`, THE test SHALL receive a `ServerConfig` whose `db_backend` is `"mock"` and `create_data_access()` SHALL return a `UnifiedDataAccess` wrapping the mock adapters.
4. THE registration of the Mock_Backend SHALL happen at conftest module load so all tests that use the `data_access` fixture see it without explicit setup.
5. THE Mock_Backend SHALL exercise the `resolve_collection` method by storing a mapping of logical to physical names that mirrors the OpenSearchAdapter shape (for cross-backend test parity).

### Requirement 7: Tool Module Independence

**User Story:** As a tool module author, I want tool code to depend only on the protocols and never on adapter-specific details, so that tools work on any backend without modification.

#### Acceptance Criteria

1. NO file in `mcp_server_python/src/tools/` SHALL import from `src/config/aws_config.py` after this refactor.
2. NO file in `mcp_server_python/src/tools/` SHALL reference the strings `"titan1024"`, `"mdc-workflow-docs"`, `"opensearch"`, `"neptune"`, or any other AWS-specific identifier as a hardcoded value.
3. WHEN a tool needs the physical index name for a logical collection, THE tool SHALL call `data.vector_db.resolve_collection(logical_name)`.
4. WHEN a tool inspects a health check result, THE tool SHALL access `HealthReport.collections` and `HealthReport.metrics` rather than reaching into adapter-specific keys.
5. THE 51 existing tools SHALL produce identical output strings before and after this refactor when running against the AWS backend, verified by the existing test suite.

### Requirement 8: Test Suite Continuity

**User Story:** As a developer, I want all 752 existing unit tests to continue to pass after this refactor, so that the refactor is verified non-regressive.

#### Acceptance Criteria

1. THE complete unit test suite (`pytest tests/unit/`) SHALL pass with zero failures after the refactor.
2. WHEN any test fixture currently constructs a `UnifiedDataAccess` directly with mock adapters, THE fixture SHALL continue to work without modification.
3. WHEN any test currently sets `DB_BACKEND=aws` in env, THE test SHALL continue to pass.
4. THE refactor SHALL add at least one new test verifying that registering a custom backend via `register_backend()` works end-to-end (config load → backend lookup → adapter construction → query).
5. THE refactor SHALL add at least one new test verifying that `DB_BACKEND` unset raises `ConfigError`.

### Requirement 9: Documentation

**User Story:** As a future contributor, I want clear documentation of the registry pattern, so that I can add a new backend without reverse-engineering the design.

#### Acceptance Criteria

1. THE module docstring of `src/data/backend_selector.py` SHALL describe the registry pattern, including how to register a new backend.
2. THE module docstring of `src/data/protocols.py` SHALL describe the `HealthReport` shape and the `resolve_collection` contract.
3. THE refactor SHALL produce a single-paragraph addition to `.kiro/steering/01-architecture-context.md` summarizing the backend-agnostic design.
4. THE refactor SHALL include an inline code example in `backend_selector.py` showing how to register a hypothetical `"chromadb"` backend.
