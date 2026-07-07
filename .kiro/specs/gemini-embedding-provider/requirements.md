# Requirements Document

## Introduction

This feature adds a **Google Gemini** embedding provider
(`gemini-embedding-001`) as a first-class option in the embedding
abstraction shared by the two MCP servers, so it can be evaluated
head-to-head against the current providers:

- `titan1024` — Amazon Bedrock Titan Embed Text V2 (1024-dim, the
  AWS-native default).
- `mpnet768` — local `sentence-transformers/all-mpnet-base-v2`
  (768-dim, the COTS/local baseline).

The embedding layer already implements a `ModelProfile` registry, an
`EmbeddingProvider` ABC with a `create_provider` factory, and
`BedrockProvider` / `LocalProvider` concrete implementations, duplicated
field-for-field in `mcp_server_node/scripts/` (ingestion) and
`mcp_server_python/src/data/` (runtime). Ingestion funnels through a
single call site — `mcp_server_node/scripts/ingestion_base.py::run()` →
`self.provider.embed([chunk.text])[0]` — which is backend-agnostic
(`--backend aws|cots`) and provider-selected (`--model`). Adding a new
provider therefore requires no change to the ingestion loop.

The goal is a `GeminiProvider` that calls the Google Generative Language
`embedContent` REST endpoint via the Python standard library (`urllib`),
adding **zero** new runtime dependencies to the ingest box or the
AgentCore image. It mirrors the `BedrockProvider` retry/backoff contract,
L2-normalizes sub-3072-dimensional vectors for fair cosine/k-NN
comparison against the already-normalized Titan vectors, and is selected
by `--model gemini768`. The provider is inert until a `GEMINI_API_KEY`
(or `GOOGLE_API_KEY`) is present in the environment, so the code can land
and be unit-tested before a key is provisioned.

This work is the code half of the plan captured in the wiki page
`Gemini-Embedding-Provider-Evaluation-and-Key-Request` and its sister SDD
workflow `sdd_framework/workflows/phase66_gemini_embedding_provider_evaluation.md`.

## Glossary

- **Embedding_Registry**: The `ModelProfile` registry modules at
  `mcp_server_node/scripts/embedding_registry.py` and
  `mcp_server_python/src/data/embedding_registry.py`.
- **ModelProfile**: The immutable model descriptor. Fields: `short_name`,
  `provider`, `model_id`, `dimensions`, `supports_matryoshka`,
  `supports_multimodal`, `provider_params`.
- **Embedding_Provider**: The abstract embedding interface modules at
  `mcp_server_node/scripts/embedding_provider.py` and
  `mcp_server_python/src/data/embedding_provider.py`.
- **Gemini_Provider**: The concrete `EmbeddingProvider` implementation
  added by this feature that calls the Google Generative Language REST
  API via `urllib`.
- **create_provider**: The factory function that maps a `ModelProfile`
  to a concrete `EmbeddingProvider` by dispatching on `profile.provider`.
- **EmbeddingError**: The exception raised when embedding generation
  fails. Mirrors the existing Bedrock/Local shape.
- **gemini768**: The `ModelProfile.short_name` this feature registers —
  `provider="gemini"`, `model_id="gemini-embedding-001"`,
  `dimensions=768`.
- **Ingestion_Base**: `mcp_server_node/scripts/ingestion_base.py`, whose
  `run()` invokes `self.provider.embed([chunk.text])` for every chunk.
- **Benchmark_Runner**: `mcp_server_node/scripts/benchmark_runner.py`,
  which resolves a provider via `create_provider` and computes retrieval
  metrics for a collection.
- **GEMINI_API_KEY**: The primary environment variable holding the Google
  API key. `GOOGLE_API_KEY` is accepted as a fallback name.
- **embedContent**: The Google Generative Language REST method
  (`POST /v1beta/models/{model}:embedContent`) that returns a single
  embedding for a piece of content.

## Requirements

### Requirement 1: Register the `gemini768` profile in both registries

**User Story:** As an embedding-pipeline maintainer, I want a
`gemini768` `ModelProfile` registered in both the Node.js and Python
registries, so that `--model gemini768` resolves to the Gemini provider
in either server.

#### Acceptance Criteria

1. THE Embedding_Registry SHALL register a profile with `short_name`
   `"gemini768"`, `provider` `"gemini"`,
   `model_id` `"gemini-embedding-001"`, and `dimensions` `768`.
2. THE Embedding_Registry SHALL set the `gemini768` profile's
   `provider_params` to include `task_type="RETRIEVAL_DOCUMENT"`,
   `output_dimensionality=768`, and `normalize=true`.
3. WHEN `Embedding_Registry.get_profile("gemini768")` is called, THE
   Embedding_Registry SHALL return the `gemini768` `ModelProfile`.
4. THE `gemini768` profile SHALL be registered in BOTH
   `mcp_server_node/scripts/embedding_registry.py` AND
   `mcp_server_python/src/data/embedding_registry.py` with identical
   field values.
5. THE feature SHALL NOT change the registry's default profile
   (it remains `titan1024`).

### Requirement 2: Provider-factory dispatch for `"gemini"`

**User Story:** As an `EmbeddingProvider` caller, I want the
`create_provider` factory to build a `Gemini_Provider` for a
`provider="gemini"` profile, so that the rest of the pipeline stays
decoupled from the provider implementation.

#### Acceptance Criteria

1. WHEN `create_provider` is called with a `ModelProfile` whose
   `provider` field equals `"gemini"`, THE Embedding_Provider SHALL
   return a `Gemini_Provider` instance bound to that profile.
2. THE `create_provider` dispatch for `"gemini"` SHALL be added in BOTH
   the Node.js and Python `embedding_provider` modules.
3. THE feature SHALL NOT alter the existing dispatch for `"bedrock"`
   or `"local"`.

### Requirement 3: Gemini REST embedding via the standard library

**User Story:** As an ingestion caller, I want `Gemini_Provider.embed`
to produce embeddings from `gemini-embedding-001` over the REST API
using only the Python standard library, so that no new dependency is
added to the ingest box or the runtime image.

#### Acceptance Criteria

1. WHEN `Gemini_Provider.embed` is called with a non-empty list of
   strings, THE Gemini_Provider SHALL issue one `embedContent` HTTP
   POST per input string to
   `https://generativelanguage.googleapis.com/v1beta/models/{model_id}:embedContent`.
2. THE Gemini_Provider SHALL send the API key in the `x-goog-api-key`
   request header and SHALL NOT place the key in the request URL.
3. THE Gemini_Provider SHALL build the request body with
   `content.parts[0].text` set to the input string, `taskType` set to
   `provider_params.task_type`, and `outputDimensionality` set to
   `provider_params.output_dimensionality`.
4. THE Gemini_Provider SHALL parse `embedding.values` from the JSON
   response and return a list whose i-th element is the float vector
   for the i-th input string.
5. THE Gemini_Provider SHALL use only Python standard-library HTTP
   (`urllib.request`) and SHALL NOT import `google-genai`,
   `google-generativeai`, `requests`, or any other third-party HTTP or
   SDK package.
6. THE Gemini_Provider SHALL expose a `dimensions` property returning
   `ModelProfile.dimensions`.

### Requirement 4: L2 normalization for fair comparison

**User Story:** As an evaluator comparing Gemini against Titan, I want
sub-3072-dimensional Gemini vectors L2-normalized, so that cosine/k-NN
similarity is comparable to the already-normalized Titan vectors.

#### Acceptance Criteria

1. WHEN `provider_params.normalize` is true (its default for
   `output_dimensionality != 3072`), THE Gemini_Provider SHALL
   L2-normalize each returned vector to unit length.
2. WHEN a returned vector has zero magnitude, THE Gemini_Provider SHALL
   return the vector unchanged rather than divide by zero.
3. WHEN `provider_params.output_dimensionality` equals 3072, THE
   Gemini_Provider SHALL default `normalize` to false (the 3072-dim
   model output is already normalized), unless `normalize` is set
   explicitly in `provider_params`.

### Requirement 5: Retry and backoff for transient errors

**User Story:** As an operator running a full-corpus ingest, I want
transient Gemini errors retried with backoff, so that single-flake
errors and rate-limit blips do not abort the run.

#### Acceptance Criteria

1. IF a `Gemini_Provider.embed` HTTP call returns status 429, 500, 502,
   503, or 504, THEN THE Gemini_Provider SHALL retry the failed call up
   to 3 additional times.
2. THE Gemini_Provider SHALL space retries with exponential backoff at
   1 second, 2 seconds, and 4 seconds before attempts 2, 3, and 4.
3. IF all 4 attempts fail, THEN THE Gemini_Provider SHALL raise
   `EmbeddingError` whose message includes `model_id` and the last
   underlying error.
4. IF a `Gemini_Provider.embed` HTTP call returns a non-retryable status
   (any 4xx other than 429), THEN THE Gemini_Provider SHALL raise
   `EmbeddingError` without retrying.
5. IF the response vector length does not equal
   `ModelProfile.dimensions`, THEN THE Gemini_Provider SHALL raise
   `EmbeddingError` and SHALL NOT retry.

### Requirement 6: API key resolution and inert-without-key behavior

**User Story:** As a maintainer landing this code before a key is
provisioned, I want the provider to read the key from the environment
and fail with a clear error only when actually used, so that the code
can merge and be unit-tested without a live key.

#### Acceptance Criteria

1. WHEN `Gemini_Provider` is constructed, THE Gemini_Provider SHALL read
   the API key from `GEMINI_API_KEY`, falling back to `GOOGLE_API_KEY`.
2. IF neither `GEMINI_API_KEY` nor `GOOGLE_API_KEY` is set when
   `Gemini_Provider` is constructed, THEN THE Gemini_Provider SHALL
   raise `EmbeddingError` whose message names both accepted variables.
3. THE Gemini_Provider SHALL NOT read the key at module import time
   (only at construction), so importing the module without a key
   succeeds.

### Requirement 7: Node ABC parity — `embed_image`

**User Story:** As a maintainer of the Node.js ingestion provider, I
want `Gemini_Provider` to satisfy the Node `EmbeddingProvider` ABC,
so that the module imports cleanly.

#### Acceptance Criteria

1. THE Node.js `Gemini_Provider` SHALL implement the abstract
   `embed_image` method required by the Node.js `EmbeddingProvider` ABC.
2. WHEN `embed_image` is called, THE Node.js `Gemini_Provider` SHALL
   raise `NotImplementedError` stating that image embedding is not
   supported.
3. THE Python `Gemini_Provider` SHALL match the Python
   `EmbeddingProvider` ABC (which has no `embed_image`) and SHALL NOT
   add an image method.

### Requirement 8: Unit and integration tests

**User Story:** As a maintainer, I want unit tests for the Gemini
provider and a key-gated integration smoke test, so that regressions
are caught before a full ingest.

#### Acceptance Criteria

1. THE test suite SHALL include unit tests that mock the HTTP layer and
   assert the `embedContent` request body shape (content text,
   `taskType`, `outputDimensionality`) and that the key is sent via the
   `x-goog-api-key` header.
2. THE test suite SHALL include unit tests verifying the retry schedule
   (1s / 2s / 4s) on transient 429 and 5xx responses and no-retry on a
   non-retryable 4xx.
3. THE test suite SHALL include a unit test verifying L2 normalization
   produces unit-length vectors and that a zero vector is returned
   unchanged.
4. THE test suite SHALL include a unit test verifying that constructing
   `Gemini_Provider` without a key raises `EmbeddingError`.
5. THE test suite SHALL include a unit test verifying a dimension
   mismatch raises `EmbeddingError`.
6. THE test suite SHALL include an integration test gated on
   `GEMINI_API_KEY` being set (skipped otherwise) that issues one real
   `embed(["hello world"])` call against `gemini768` and asserts the
   returned vector has length 768 and unit L2 norm.

### Requirement 9: Comparison ingest and benchmark (operational)

**User Story:** As an evaluator, I want a repeatable procedure to ingest
a `gemini768` collection and benchmark it against `titan1024`, so that
the head-to-head result is measured, not asserted.

#### Acceptance Criteria

1. WHEN `ingest_documentation_v8.py --model gemini768` is run with a
   valid `GEMINI_API_KEY` present, THE Ingestion_Base SHALL produce a
   `gemini768`-suffixed collection via the existing `CollectionNamer`
   without any change to `run()`.
2. THE Benchmark_Runner SHALL resolve the `gemini768` provider via
   `create_provider` and compute P@5 and MRR for the `gemini768`
   collection against the same query set used for the `titan1024`
   baseline.
3. THE evaluation SHALL record P@5 and MRR for `gemini768` and
   `titan1024` side-by-side in the phase report.

### Requirement 10: Documentation

**User Story:** As a maintainer reading project history, I want the
provider addition recorded in CHANGELOG and cross-referenced with the
wiki and SDD workflow, so that the evaluation trail is auditable.

#### Acceptance Criteria

1. THE CHANGELOG.md SHALL include a new dated entry summarizing the
   Gemini provider addition, the files touched, and the test-count
   delta.
2. THE phase report SHALL cross-reference the wiki page
   `Gemini-Embedding-Provider-Evaluation-and-Key-Request` and the SDD
   workflow `phase66_gemini_embedding_provider_evaluation.md`.

### Requirement 11: Out-of-scope constraints

**User Story:** As a reviewer, I want the non-goals codified as
constraints, so the implementation stays bounded to the comparison.

#### Acceptance Criteria

1. THE feature SHALL NOT modify the existing `BedrockProvider` or
   `LocalProvider` implementations.
2. THE feature SHALL NOT re-ingest, delete, or alter the existing
   `titan1024` or `mpnet768` OpenSearch collections.
3. THE feature SHALL NOT change the ingestion loop in
   `ingestion_base.py::run()`.
4. THE feature SHALL NOT add a Google SDK or any third-party HTTP
   library to `pyproject.toml` or `package.json`.
5. THE feature SHALL NOT change the query-side `task_type`
   (`RETRIEVAL_QUERY`) wiring in this phase; the doc/query split is a
   documented follow-up if the comparison is favorable.
6. THE feature SHALL NOT commit or hardcode any API key value; the key
   is provided only via the environment.
