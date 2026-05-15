# Requirements Document

## Introduction

This feature replaces the legacy `sentence-transformers/all-mpnet-base-v2`
(mpnet768) query-embedding path in the Python MCP server's
`OpenSearchAdapter` (`mcp_server_python/src/data/opensearch_adapter.py`)
with a Bedrock Titan Embed Text V2 path against the production
`mdc-{domain}-titan1024` OpenSearch indices. Today the Python adapter
fails on every `search_documentation` call with
`No module named sentence_transformers` because the runtime image
intentionally excludes torch/transformers. The Node.js ingestion side
(`mcp_server_node/scripts/embedding_provider.py` +
`mcp_server_node/scripts/embedding_registry.py`) already implements
the multi-model `LocalProvider` / `BedrockProvider` + `ModelProfile`
pattern this work ports to the Python runtime.

The goal is a Bedrock-native query-embedding path via boto3 with no
sentence-transformers dependency in the runtime image, querying the
`titan1024` indices as the production target (richer corpus —
~120 000 docs vs ~85 000 on mpnet768) and matching the Phase 52
ingestion. The mpnet768 profile remains reachable via an
`MCP_EMBEDDING_PROFILE` environment variable for parity-debugging
against the legacy Node.js MCP, but its provider is intentionally
non-functional in the runtime image (the dependency is not shipped).

This is Phase C-2c in the Python MCP port roadmap and follows
Phase C-2b (data layer connected).

## Glossary

- **Embedding_Registry**: The `ModelProfile` registry module to be
  added at `mcp_server_python/src/data/embedding_registry.py`. Mirrors
  the Node.js singleton at `mcp_server_node/scripts/embedding_registry.py`.
- **ModelProfile**: An immutable descriptor for an embedding model.
  Fields: `short_name`, `provider`, `model_id`, `dimensions`,
  `supports_matryoshka`, `supports_multimodal`, `provider_params`.
- **Embedding_Provider**: The abstract embedding interface module to
  be added at `mcp_server_python/src/data/embedding_provider.py`.
- **Bedrock_Provider**: The concrete `EmbeddingProvider` implementation
  that calls AWS Bedrock via boto3.
- **Local_Provider**: The concrete `EmbeddingProvider` implementation
  that uses sentence-transformers. Present as a class definition for
  parity with the Node.js port, but its constructor surfaces an error
  in the Python runtime image because sentence-transformers is not
  installed.
- **OpenSearch_Adapter**: The Python `OpenSearchAdapter` class at
  `mcp_server_python/src/data/opensearch_adapter.py`.
- **AWS_Config**: The configuration module at
  `mcp_server_python/src/config/aws_config.py`, including the
  `PRODUCTION_INDICES` mapping and the `resolve_index` function.
- **MCP_Server_Runtime**: The Python MCP server process, i.e. the
  `mcp_server_python` runtime as deployed to the AgentCore Runtime
  `mdc_mcp_rag_server_python-v5K2F8BGrN`.
- **MCP_EMBEDDING_PROFILE**: The environment variable consulted at
  startup to select the active embedding `ModelProfile`. Accepted
  values: `titan1024` (default), `mpnet768`, `nova256`, `nova512`,
  `nova1024`, `nova3072`.
- **Profile_Aware_Index_Resolver**: The updated `AWS_Config.resolve_index`
  that maps a logical collection name to the OpenSearch index whose
  vector dimensionality matches the active `ModelProfile`.
- **Runtime_Container_Image**: The Docker image built from
  `mcp_server_python/Dockerfile` and tagged `python-titan-v1`.
- **Test_Suite**: The pytest suite under `mcp_server_python/tests/`.
- **EmbeddingError**: The exception class raised when embedding
  generation fails. Mirrors the Node.js shape.
- **ConfigError**: The configuration-validation exception raised at
  startup when an environment variable holds an invalid value.

## Requirements

### Requirement 1: Port the embedding model registry to the Python runtime

**User Story:** As a Python MCP server maintainer, I want a
`ModelProfile` registry in the Python runtime that mirrors the Node.js
registry, so that the Python port resolves embedding models through
the same abstraction.

#### Acceptance Criteria

1. THE Embedding_Registry SHALL expose a `ModelProfile` dataclass with
   fields `short_name`, `provider`, `model_id`, `dimensions`,
   `supports_matryoshka`, `supports_multimodal`, and `provider_params`.
2. THE Embedding_Registry SHALL register the six built-in profiles
   `mpnet768`, `titan1024`, `nova256`, `nova512`, `nova1024`, and
   `nova3072` with `model_id`, `provider`, `dimensions`, and
   `provider_params` values that match
   `mcp_server_node/scripts/embedding_registry.py`.
3. THE Embedding_Registry SHALL set `titan1024` as the default profile.
4. WHEN `Embedding_Registry.get_profile` is called with a registered
   `short_name`, THE Embedding_Registry SHALL return the corresponding
   `ModelProfile`.
5. IF `Embedding_Registry.get_profile` is called with an unregistered
   `short_name`, THEN THE Embedding_Registry SHALL raise `KeyError`
   with a message that lists the registered `short_name` values.
6. THE Embedding_Registry SHALL expose `list_profiles` returning the
   registered `short_name` values and `register` for adding additional
   profiles at runtime.

### Requirement 2: Embedding provider abstraction with a Bedrock-default factory

**User Story:** As an OpenSearchAdapter caller, I want a single
`EmbeddingProvider` interface and a factory that builds the right
provider for a `ModelProfile`, so that the adapter is decoupled from
any specific embedding implementation.

#### Acceptance Criteria

1. THE Embedding_Provider SHALL define an abstract `embed(texts)`
   method that accepts a list of strings and returns a list of
   float vectors.
2. THE Embedding_Provider SHALL expose a `dimensions` property that
   returns the active `ModelProfile.dimensions` value.
3. WHEN the factory `create_provider` is called with a `ModelProfile`
   whose `provider` field equals `"bedrock"`, THE Embedding_Provider
   SHALL return a `Bedrock_Provider` instance bound to that profile.
4. WHEN the factory `create_provider` is called with a `ModelProfile`
   whose `provider` field equals `"local"`, THE Embedding_Provider
   SHALL return a `Local_Provider` instance bound to that profile.
5. IF the factory `create_provider` is called with a `ModelProfile`
   whose `provider` field is neither `"bedrock"` nor `"local"`, THEN
   THE Embedding_Provider SHALL raise `ValueError`.

### Requirement 3: Bedrock-backed query embedding

**User Story:** As an OpenSearchAdapter caller, I want query-time
embeddings produced by Bedrock Titan Embed Text V2, so that searches
target the production `titan1024` indices.

#### Acceptance Criteria

1. WHEN `Bedrock_Provider.embed` is called with a non-empty list of
   strings, THE Bedrock_Provider SHALL invoke
   `bedrock-runtime.invoke_model` once per input string with the
   `modelId` from the active `ModelProfile.model_id`.
2. THE Bedrock_Provider SHALL build the request body for non-Nova
   profiles as a JSON object containing `inputText` set to the input
   string and the fields from `ModelProfile.provider_params` merged in.
3. THE Bedrock_Provider SHALL build the request body for Nova profiles
   using the `nova-multimodal-embed-v1` schema with
   `taskType="SINGLE_EMBEDDING"`,
   `singleEmbeddingParams.embeddingDimension` equal to
   `ModelProfile.dimensions`, and `singleEmbeddingParams.text.value`
   equal to the input string.
4. THE Bedrock_Provider SHALL parse the Bedrock response and return a
   list whose i-th element is the float vector for the i-th input
   string.
5. THE Bedrock_Provider SHALL return vectors whose length equals
   `ModelProfile.dimensions` for every accepted profile.
6. THE Bedrock_Provider SHALL authenticate via SigV4 using the boto3
   default credential provider chain.
7. THE Bedrock_Provider SHALL target the AWS region resolved from
   `AWS_REGION`, defaulting to `us-east-1` when the variable is unset.
8. THE Bedrock_Provider SHALL reuse a single process-scoped
   `bedrock-runtime` client across calls.

### Requirement 4: Retry and backoff for transient Bedrock errors

**User Story:** As an MCP operator, I want transient Bedrock errors
to be retried with backoff, so that single-flake errors do not surface
to MCP callers.

#### Acceptance Criteria

1. IF a `Bedrock_Provider.embed` call raises a transient error
   (HTTP 4xx with status 429, or any HTTP 5xx), THEN THE
   Bedrock_Provider SHALL retry the failed call up to 3 additional
   times.
2. THE Bedrock_Provider SHALL space retries with exponential backoff
   at 1 second, 2 seconds, and 4 seconds before attempts 2, 3, and 4
   respectively.
3. IF all 4 attempts fail, THEN THE Bedrock_Provider SHALL raise
   `EmbeddingError` whose message includes the active
   `ModelProfile.model_id` and the last underlying error.
4. IF a `Bedrock_Provider.embed` call raises a non-transient error
   (HTTP 4xx other than 429, validation errors, or any non-HTTP
   exception), THEN THE Bedrock_Provider SHALL raise `EmbeddingError`
   without retrying.

### Requirement 5: Async integration with the OpenSearchAdapter

**User Story:** As an OpenSearchAdapter caller awaited from FastMCP
handlers, I want Bedrock embedding calls executed off the event loop,
so that the adapter remains non-blocking.

#### Acceptance Criteria

1. WHEN `OpenSearch_Adapter._generate_embedding` is invoked and no
   explicit `embedding_function` was passed at construction time,
   THE OpenSearch_Adapter SHALL invoke the active provider's `embed`
   method via `asyncio.to_thread`.
2. WHEN `OpenSearch_Adapter._generate_embedding` is invoked and an
   explicit `embedding_function` was passed at construction time,
   THE OpenSearch_Adapter SHALL invoke that callable via
   `asyncio.to_thread`.
3. THE OpenSearch_Adapter SHALL return the first vector of the
   provider response from `_generate_embedding`.

### Requirement 6: Remove the sentence-transformers default path

**User Story:** As a Python MCP server maintainer, I want the
sentence-transformers default path removed from `OpenSearchAdapter`,
so that the runtime image no longer carries a dead dependency.

#### Acceptance Criteria

1. THE OpenSearch_Adapter SHALL NOT import the `sentence_transformers`
   package at module load time.
2. WHEN `MCP_EMBEDDING_PROFILE` is unset, set to `titan1024`, or set to
   any `nova` variant, THE OpenSearch_Adapter SHALL produce query
   embeddings without importing the `sentence_transformers` package
   for the lifetime of the process.
3. THE OpenSearch_Adapter SHALL remove the
   `_default_mpnet_embedding` method and the module-level
   `_mpnet_model` cache.
4. THE OpenSearch_Adapter SHALL resolve the active `ModelProfile` at
   construction time from `MCP_EMBEDDING_PROFILE` via
   `Embedding_Registry`.
5. THE OpenSearch_Adapter SHALL build the active `Embedding_Provider`
   at construction time via the `create_provider` factory.

### Requirement 7: MCP_EMBEDDING_PROFILE environment variable

**User Story:** As an operator running the staging runtime, I want a
single environment variable that selects the embedding profile, so
that I can swap between `titan1024` and `mpnet768` for parity-debugging
without code changes.

#### Acceptance Criteria

1. WHEN `MCP_EMBEDDING_PROFILE` is unset at startup, THE
   MCP_Server_Runtime SHALL select the `titan1024` profile.
2. WHEN `MCP_EMBEDDING_PROFILE` is set to one of `titan1024`,
   `mpnet768`, `nova256`, `nova512`, `nova1024`, or `nova3072` at
   startup, THE MCP_Server_Runtime SHALL select the matching profile.
3. IF `MCP_EMBEDDING_PROFILE` is set to any other value at startup,
   THEN THE MCP_Server_Runtime SHALL raise `ConfigError` whose
   message lists the six accepted values.
4. WHEN `MCP_EMBEDDING_PROFILE` resolves to `mpnet768` at startup,
   THE MCP_Server_Runtime SHALL emit a single `[WARN]` log line
   stating that the legacy parity-debug fallback is active and that
   sentence-transformers is not installed in the runtime image.

### Requirement 8: Profile-aware index resolver

**User Story:** As an OpenSearchAdapter caller, I want the index
resolver to route to the index whose vector dimensionality matches
the active embedding profile, so that the query vector and the
indexed vectors share a dimension.

#### Acceptance Criteria

1. WHEN the active profile is `titan1024`, THE
   Profile_Aware_Index_Resolver SHALL map the five known logical
   collections (`code-with-context-v8-0-0`,
   `global-workflow-docs-v8-0-0`, `jjobs-v8-0-0`,
   `community-summaries`, `ee2-standards-v5-0-0-enhanced`) to their
   `mdc-{domain}-titan1024` index names.
2. WHEN the active profile is `mpnet768`, THE
   Profile_Aware_Index_Resolver SHALL map the five known logical
   collections to their `mdc-{domain}-mpnet768` index names.
3. WHERE the active profile is one of `nova256`, `nova512`,
   `nova1024`, or `nova3072`, THE Profile_Aware_Index_Resolver SHALL
   map the five known logical collections to their
   `mdc-{domain}-{profile}` index names if such an index mapping
   has been registered, and otherwise SHALL return the collection
   name unchanged.
4. WHERE a logical collection is not in the known set, THE
   Profile_Aware_Index_Resolver SHALL return the collection name
   unchanged.
5. THE AWS_Config module SHALL replace the static `PRODUCTION_INDICES`
   constant with a `get_production_indices(profile_short_name)`
   function (or equivalent profile-keyed structure) so that callers
   read the correct index map for the active profile.

### Requirement 9: mpnet768 fallback raises a clear error in the runtime image

**User Story:** As an operator who flips `MCP_EMBEDDING_PROFILE` to
`mpnet768` on the staging runtime for parity-debugging, I want the
runtime to surface a clear error rather than crash, so that I know
the legacy path is intentionally not shipped.

#### Acceptance Criteria

1. WHEN the active profile is `mpnet768` and a search-tool handler
   triggers `OpenSearch_Adapter._generate_embedding`,
   THE Local_Provider SHALL raise `EmbeddingError` whose message
   states that `sentence-transformers` is not installed in the
   runtime image.
2. WHEN `Local_Provider.__init__` runs and the `sentence_transformers`
   import fails, THE Local_Provider SHALL emit one `[ERROR]` log line
   identifying `mpnet768` as the active profile before raising
   `EmbeddingError`.
3. THE OpenSearch_Adapter SHALL translate `EmbeddingError` from
   `_generate_embedding` into `OpenSearchQueryError` with `status=None`
   so MCP tool handlers surface a structured error.

### Requirement 10: Runtime container image dependencies

**User Story:** As a Python MCP server maintainer, I want the runtime
image to drop the heavyweight ML dependencies, so that the deployed
image is materially smaller and faster to pull.

#### Acceptance Criteria

1. THE Runtime_Container_Image SHALL include the `boto3` package.
2. THE Runtime_Container_Image SHALL exclude the `sentence-transformers`
   package and SHALL exclude any package that transitively depends on
   `sentence-transformers`.
3. THE Runtime_Container_Image SHALL exclude the `torch` package and
   SHALL exclude any package that transitively depends on `torch`.
4. THE Runtime_Container_Image SHALL exclude the `transformers` package
   and SHALL exclude any package that transitively depends on
   `transformers`.
5. THE compressed manifest size of the new `python-titan-v1` image in
   ECR SHALL be smaller than the compressed manifest size of the
   prior `python-all-tools-v3` image, with the delta recorded in the
   phase report.

### Requirement 11: Unit and integration tests

**User Story:** As a Python MCP server maintainer, I want unit tests
for the new embedding provider and a gated integration smoke test, so
that regressions are caught before deploy.

#### Acceptance Criteria

1. THE Test_Suite SHALL include unit tests for `Embedding_Registry`
   covering profile lookup hits, profile lookup misses, the default
   profile, and `list_profiles`.
2. THE Test_Suite SHALL include unit tests for `Bedrock_Provider`
   that mock the `bedrock-runtime` client and verify request body
   shape for at least one Titan profile and one Nova profile.
3. THE Test_Suite SHALL include unit tests for `Bedrock_Provider`
   that mock the `bedrock-runtime` client and verify the retry
   schedule (1s / 2s / 4s) on transient HTTP 429 and HTTP 5xx
   responses.
4. THE Test_Suite SHALL include unit tests for `Local_Provider` that
   verify `EmbeddingError` is raised at construction time when
   `sentence_transformers` is not importable.
5. THE Test_Suite SHALL include unit tests for the
   Profile_Aware_Index_Resolver that verify titan-routing, mpnet-routing,
   and unknown-collection passthrough.
6. THE Test_Suite SHALL replace any unit test that previously stubbed
   the mpnet path in `OpenSearch_Adapter` with an equivalent test
   that stubs the `Bedrock_Provider`.
7. THE Test_Suite SHALL include an integration test gated on
   `RUN_INTEGRATION=1` that issues one real `Bedrock_Provider.embed`
   call for the input string `"hello world"` against the `titan1024`
   profile and asserts the returned vector has length 1024.
8. WHEN the unit Test_Suite runs (without `RUN_INTEGRATION=1`),
   THE Test_Suite SHALL pass all 716 tests from the Phase C-2b
   baseline plus the new tests added by this feature.

### Requirement 12: Live validation against the staging runtime

**User Story:** As an MCP operator, I want a recorded set of post-deploy
checks that prove the swap works end-to-end, so that we can sign off
Phase C-2c.

#### Acceptance Criteria

1. WHEN `search_documentation` is invoked on the deployed runtime
   with the query `"data assimilation cycling"`, THE MCP_Server_Runtime
   SHALL return at least one hit.
2. WHEN `mcp_health_check({deep:true})` is invoked on the deployed
   runtime, THE MCP_Server_Runtime SHALL report Vector status `healthy`
   and Vector index doc-count totals consistent with the `titan1024`
   indices (greater than 100 000 total documents).
3. WHEN `get_knowledge_base_status` is invoked on the deployed runtime,
   THE MCP_Server_Runtime SHALL report vector status `healthy` and
   SHALL NOT report the `Unhealthy / sentence_transformers missing`
   state observed before this swap.
4. THE Integration_Test_Suite SHALL record p50 and p95 Bedrock
   query-embedding latency and report both values in the phase report.

### Requirement 13: Deploy artifacts and rollback targets

**User Story:** As an MCP operator, I want a clean ECR tag for the new
image and the prior tag preserved as a rollback target, so that I can
revert without rebuilding.

#### Acceptance Criteria

1. THE Runtime_Container_Image SHALL be pushed to ECR under the tag
   `python-titan-v1`.
2. THE prior ECR tag `python-all-tools-v3` SHALL remain present in
   ECR after the deploy.
3. THE staging runtime `mdc_mcp_rag_server_python-v5K2F8BGrN` SHALL
   be redeployed with the `python-titan-v1` image.
4. THE staging runtime SHALL retain the existing environment-variable
   set from Phase C-2b and SHALL additionally accept the optional
   `MCP_EMBEDDING_PROFILE` variable.

### Requirement 14: Documentation and changelog updates

**User Story:** As a Python MCP server maintainer reading the project
history, I want the swap recorded in CHANGELOG, the steering log, and
a phase report, so that the cutover trail is auditable.

#### Acceptance Criteria

1. THE CHANGELOG.md SHALL include a new `[8.22.3]` section that
   summarizes the embedding-swap scope, the new and modified files,
   the test-count delta, the deploy artifacts (image SHA, ECR
   manifest digest, ECR tag), the live validation outcomes, and the
   image-size delta.
2. THE phase report at
   `docs/reports/2026-05-14-phase-c2c-bedrock-embedding-swap.md`
   SHALL document the root cause, the implementation, the test
   results, the deploy outcome, the latency measurements, and any
   parity deltas observed against the `mpnet768` indices.
3. THE steering document at `.kiro/steering/06-python-port-progress.md`
   SHALL be updated with a `Phase C-2c` section that lists the
   runtime version, the new image tag, and a link to the phase report.

### Requirement 15: Out-of-scope items remain untouched

**User Story:** As a reviewer, I want the explicit non-goals codified
as constraints, so that the implementation stays bounded.

#### Acceptance Criteria

1. THE feature SHALL NOT re-ingest data into any OpenSearch index.
2. THE feature SHALL NOT modify any code in `mcp_server_node/`.
3. THE feature SHALL NOT delete or otherwise alter the existing
   `mdc-{domain}-mpnet768` indices in OpenSearch.
4. THE feature SHALL NOT add `sentence-transformers`, `torch`, or
   `transformers` to the runtime container image dependencies.
5. THE feature SHALL NOT modify
   `mcp_server_node/scripts/embedding_provider.py` or
   `mcp_server_node/scripts/embedding_registry.py`.
