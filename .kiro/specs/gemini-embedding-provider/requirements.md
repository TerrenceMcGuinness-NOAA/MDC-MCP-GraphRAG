# Requirements Document

## Introduction

This feature adds Google's **`gemini-embedding-2`** — Google's first natively
**multimodal** embedding model — as a new embedding provider in the abstraction
shared by the two MCP servers, and evaluates it head-to-head against the two
providers we run today: `titan1024` (Amazon Bedrock Titan Embed Text V2, the
AWS-native default) and `mpnet768` (local `all-mpnet-base-v2`, the COTS baseline).

`gemini-embedding-2` maps **text, images (PNG/JPEG), audio, video, and PDF into
one unified vector space**. This unlocks a capability neither incumbent has:
embedding image files (`*.png`) from the ingestion CLI and retrieving them with
a text query (cross-modal search). It provides an 8,192-token context window,
Matryoshka output dimensions (128–3072, default 3072), server-side
normalization at every dimension, and task control via text-prefix instructions.

The embedding layer already exposes a `ModelProfile` registry, an
`EmbeddingProvider` ABC with a `create_provider` factory, and `BedrockProvider`
/ `LocalProvider` implementations, duplicated field-for-field in
`mcp_server_node/scripts/` (ingestion) and `mcp_server_python/src/data/`
(runtime). Ingestion funnels through one backend-agnostic call site,
`ingestion_base.py::run()` → `self.provider.embed([chunk.text])`.

The goal is a `GeminiProvider` that calls the Google Generative Language
`embedContent` REST endpoint via the Python standard library (`urllib`) — adding
**zero** new runtime dependencies — with both a text path and an image path, and
a new additive CLI route for image ingestion. The provider is inert until a
`GEMINI_API_KEY` (or `GOOGLE_API_KEY`) is present, so the code can land and be
unit-tested before a key is provisioned.

**Scope decision:** this feature targets **only** `gemini-embedding-2`. The
older, text-only `gemini-embedding-001` is explicitly out of scope — the v2
model supersedes it, and carrying both added dual code paths (manual vs
auto normalization, `taskType` enum vs text-prefix task control) for no benefit.

Companion wiki page: `Gemini-Embedding-Provider-Evaluation-and-Key-Request`.
Sister SDD workflow: `sdd_framework/workflows/phase66_gemini_embedding_provider_evaluation.md`.

## Glossary

- **Embedding_Registry**: `ModelProfile` registry modules at
  `mcp_server_node/scripts/embedding_registry.py` and
  `mcp_server_python/src/data/embedding_registry.py`.
- **ModelProfile**: The immutable model descriptor: `short_name`, `provider`,
  `model_id`, `dimensions`, `supports_matryoshka`, `supports_multimodal`,
  `provider_params`.
- **Embedding_Provider**: The abstract embedding interface modules at
  `mcp_server_node/scripts/embedding_provider.py` and
  `mcp_server_python/src/data/embedding_provider.py`.
- **Gemini_Provider**: The concrete `EmbeddingProvider` this feature adds,
  calling the Google Generative Language REST API for `gemini-embedding-2`.
- **create_provider**: The factory mapping a `ModelProfile` to a provider by
  dispatching on `profile.provider`.
- **EmbeddingError**: The exception raised on embedding failure (existing shape).
- **gemini2_3072 / gemini2_768**: The `ModelProfile.short_name`s this feature
  registers — `provider="gemini"`, `model_id="gemini-embedding-2"`,
  `supports_multimodal=true`, dimensions 3072 / 768 respectively.
- **Ingestion_Base**: `mcp_server_node/scripts/ingestion_base.py`, whose `run()`
  embeds text chunks via `self.provider.embed`.
- **Media_Route**: The new additive image-ingestion path added to a
  multimodal-capable ingester (a `--images` CLI flag).
- **embedContent**: The Google Generative Language REST method
  (`POST /v1beta/models/{model}:embedContent`) that returns one embedding.
- **GEMINI_API_KEY**: Primary env var for the Google API key
  (`GOOGLE_API_KEY` accepted as fallback).

## Requirements

### Requirement 1: Register `gemini-embedding-2` multimodal profiles

**User Story:** As an embedding-pipeline maintainer, I want `gemini2_3072` and
`gemini2_768` multimodal profiles registered in both registries, so that
`--model gemini2_3072` (or `gemini2_768`) resolves to the Gemini provider in
either server.

#### Acceptance Criteria

1. THE Embedding_Registry SHALL register a `gemini2_3072` profile with
   `provider="gemini"`, `model_id="gemini-embedding-2"`, `dimensions=3072`,
   `supports_multimodal=true`, `supports_matryoshka=true`, and
   `provider_params` including `output_dimensionality=3072`.
2. THE Embedding_Registry SHALL register a `gemini2_768` profile identical to
   `gemini2_3072` except `dimensions=768` and `output_dimensionality=768`.
3. THE `gemini2_3072` / `gemini2_768` profiles SHALL be registered in BOTH
   registry copies with identical field values.
4. WHEN `Embedding_Registry.get_profile` is called with `"gemini2_3072"` or
   `"gemini2_768"`, THE Embedding_Registry SHALL return the corresponding
   `ModelProfile`.
5. THE feature SHALL NOT change the registry's default profile (it remains
   `titan1024`) and SHALL NOT register any `gemini-embedding-001` profile.

### Requirement 2: Provider-factory dispatch for `"gemini"`

**User Story:** As an `EmbeddingProvider` caller, I want `create_provider` to
build a `Gemini_Provider` for a `provider="gemini"` profile, so that the rest
of the pipeline stays decoupled from the implementation.

#### Acceptance Criteria

1. WHEN `create_provider` is called with a `ModelProfile` whose `provider`
   equals `"gemini"`, THE Embedding_Provider SHALL return a `Gemini_Provider`
   bound to that profile.
2. THE `create_provider` dispatch for `"gemini"` SHALL be added in BOTH the
   Node.js and Python `embedding_provider` modules.
3. THE feature SHALL NOT alter the existing dispatch for `"bedrock"` or `"local"`.

### Requirement 3: Text embedding via the standard library

**User Story:** As an ingestion caller, I want `Gemini_Provider.embed` to
produce text embeddings from `gemini-embedding-2` over REST using only the
standard library, so that no new dependency is added.

#### Acceptance Criteria

1. WHEN `Gemini_Provider.embed` is called with a non-empty list of strings, THE
   Gemini_Provider SHALL issue one `embedContent` HTTP POST per string to
   `https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent`.
2. THE Gemini_Provider SHALL send the API key in the `x-goog-api-key` header and
   SHALL NOT place the key in the request URL.
3. THE Gemini_Provider SHALL build the request body with `content.parts[0].text`
   set to the task-formatted input string (Requirement 6) and
   `output_dimensionality` set to `provider_params.output_dimensionality`.
4. THE Gemini_Provider SHALL parse `embedding.values` from the JSON response and
   return a list whose i-th element is the vector for the i-th input string.
5. THE Gemini_Provider SHALL use only Python standard-library HTTP
   (`urllib.request`) and SHALL NOT import `google-genai`,
   `google-generativeai`, `requests`, or any other third-party HTTP/SDK package.
6. THE Gemini_Provider SHALL expose a `dimensions` property returning
   `ModelProfile.dimensions`.

### Requirement 4: Image embedding via `embed_image`

**User Story:** As an ingestion caller, I want `embed_image` to embed a PNG/JPEG
into the same vector space as text, so that images can be indexed and
cross-modally retrieved.

#### Acceptance Criteria

1. WHEN `embed_image(image_bytes, mime_type)` is called, THE Gemini_Provider
   SHALL POST an `embedContent` request whose `content.parts[0]` is an
   `inline_data` part with `mime_type` set to the argument and `data` set to the
   base64 encoding of `image_bytes`, and `output_dimensionality` set to the
   profile value.
2. THE Gemini_Provider SHALL parse `embedding.values` and return one float
   vector whose length equals `ModelProfile.dimensions`.
3. IF `mime_type` is not `image/png` or `image/jpeg`, THEN THE Gemini_Provider
   SHALL raise `EmbeddingError` without issuing the request.
4. THE `embed_image` path SHALL reuse the retry/backoff schedule (Requirement 7)
   and the `x-goog-api-key` header auth (Requirement 3.2).

### Requirement 5: No client-side normalization

**User Story:** As a provider maintainer, I want the provider to return
`gemini-embedding-2` vectors as-is, because the model auto-normalizes every
dimension, so that we avoid a redundant, misleading double-normalization.

#### Acceptance Criteria

1. THE Gemini_Provider SHALL return the vector from `embedding.values` without
   applying client-side L2 normalization.
2. THE Gemini_Provider SHALL NOT contain a `gemini-embedding-001`-style manual
   normalization branch.

### Requirement 6: Asymmetric retrieval formatting (task instructions)

**User Story:** As an evaluator, I want document and query embeddings formatted
with the model's task-instruction prefixes, so that retrieval quality matches
`gemini-embedding-2`'s intended usage.

#### Acceptance Criteria

1. WHEN `Gemini_Provider.embed` is called for documents (the default,
   `is_query=false`), THE Gemini_Provider SHALL format each input with the
   document instruction `title: {title} | text: {content}` (default title
   `none`), configurable via `provider_params.doc_instruction`.
2. WHEN `Gemini_Provider.embed` is called for queries (`is_query=true`), THE
   Gemini_Provider SHALL format each input with the query instruction
   `task: search result | query: {content}`, configurable via
   `provider_params.query_instruction`.
3. THE Ingestion_Base SHALL embed documents (`is_query=false`); the default
   `embed(texts)` call SHALL preserve backward compatibility (documents).
4. THE Gemini_Provider SHALL NOT send a `taskType` field (that mechanism is
   `gemini-embedding-001`-only and out of scope).

### Requirement 7: Retry and backoff for transient errors

**User Story:** As an operator running a full-corpus ingest, I want transient
Gemini errors retried with backoff, so that flakes and rate-limit blips do not
abort the run.

#### Acceptance Criteria

1. IF an `embedContent` HTTP call returns status 429, 500, 502, 503, or 504,
   THEN THE Gemini_Provider SHALL retry the failed call up to 3 additional times.
2. THE Gemini_Provider SHALL space retries with exponential backoff at 1s, 2s,
   and 4s before attempts 2, 3, and 4.
3. IF all 4 attempts fail, THEN THE Gemini_Provider SHALL raise `EmbeddingError`
   whose message includes the last underlying error.
4. IF an `embedContent` HTTP call returns a non-retryable status (any 4xx other
   than 429), THEN THE Gemini_Provider SHALL raise `EmbeddingError` without
   retrying.
5. IF the response vector length does not equal `ModelProfile.dimensions`, THEN
   THE Gemini_Provider SHALL raise `EmbeddingError` and SHALL NOT retry.

### Requirement 8: API key resolution and inert-without-key behavior

**User Story:** As a maintainer landing this code before a key is provisioned, I
want the provider to read the key from the environment and fail clearly only
when used, so the code can merge and be unit-tested without a live key.

#### Acceptance Criteria

1. WHEN `Gemini_Provider` is constructed, THE Gemini_Provider SHALL read the API
   key from `GEMINI_API_KEY`, falling back to `GOOGLE_API_KEY`.
2. IF neither variable is set at construction, THEN THE Gemini_Provider SHALL
   raise `EmbeddingError` naming both accepted variables.
3. THE Gemini_Provider SHALL NOT read the key at module import time (only at
   construction), so importing the module without a key succeeds.

### Requirement 9: `embed_image` ABC parity across both copies

**User Story:** As a maintainer of the two provider copies, I want `embed_image`
present in both, so the Node ABC is satisfied and the Python runtime can also
embed images.

#### Acceptance Criteria

1. THE Node.js `Gemini_Provider` SHALL implement the abstract `embed_image`
   method declared by the Node.js `EmbeddingProvider` ABC.
2. THE Python `Gemini_Provider` SHALL also expose `embed_image` (an additive
   method; the Python ABC does not declare it) so the multimodal path is
   available in both copies.
3. THE two `Gemini_Provider` copies SHALL be kept in sync field-for-field.

### Requirement 10: Image-file ingestion route (`*.png` on the CLI)

**User Story:** As an operator, I want to pass image files on the ingestion
command line, so a multimodal collection holds both text and image vectors for
cross-modal search.

#### Acceptance Criteria

1. THE Media_Route SHALL accept image-file inputs via a CLI flag (e.g.
   `--images <path-or-glob>`) on a multimodal-capable ingester.
2. WHEN the ingester processes an image file with a multimodal profile active,
   THE ingester SHALL read the file bytes, call
   `provider.embed_image(bytes, mime_type)`, and `upsert_document` the vector
   with the file path as the source id and a `modality="image"` metadata field.
3. WHERE the active profile is not multimodal, IF image inputs are supplied THEN
   THE ingester SHALL fail with a clear error naming a multimodal profile
   (e.g. `gemini2_3072`).
4. THE Media_Route SHALL enforce the documented per-request limits (≤6 images
   per request; PNG/JPEG only).
5. THE Media_Route SHALL write text and image vectors into the same `gemini2_*`
   collection so a text query can retrieve image documents.
6. THE text-embedding path SHALL NOT change the ingestion loop in
   `ingestion_base.py::run()`; the Media_Route SHALL be additive.

### Requirement 11: Unit and integration tests

**User Story:** As a maintainer, I want unit tests for the provider and a
key-gated integration smoke test, so regressions are caught before a full ingest.

#### Acceptance Criteria

1. THE test suite SHALL include unit tests (mocked HTTP) asserting the text
   `embedContent` body shape (task-formatted text, `output_dimensionality`) and
   the `x-goog-api-key` header.
2. THE test suite SHALL include unit tests (mocked HTTP) asserting the image
   request has an `inline_data` part (base64 + `mime_type`) and that a
   non-PNG/JPEG mime raises `EmbeddingError`.
3. THE test suite SHALL include a unit test asserting the retry schedule
   (1s / 2s / 4s) on transient 429 / 5xx and no-retry on a non-retryable 4xx.
4. THE test suite SHALL include a unit test asserting the provider returns
   vectors as-is (no client-side normalization) and that a dimension mismatch
   raises `EmbeddingError`.
5. THE test suite SHALL include a unit test asserting `embed` uses the document
   instruction by default and the query instruction when `is_query=true`.
6. THE test suite SHALL include a unit test asserting construction without a key
   raises `EmbeddingError`.
7. THE test suite SHALL include an integration test gated on `GEMINI_API_KEY`
   (skipped otherwise) that issues one real text `embed(["hello world"])` and
   one real `embed_image` call against `gemini2_768`, asserting each returned
   vector has length 768.

### Requirement 12: Comparison ingest and benchmark (operational)

**User Story:** As an evaluator, I want a repeatable procedure to ingest a
`gemini2_3072` collection (text + images) and benchmark it against the
incumbents, so the head-to-head is measured, not asserted.

#### Acceptance Criteria

1. WHEN `ingest_documentation_v8.py --model gemini2_3072` runs with a valid
   `GEMINI_API_KEY`, THE Ingestion_Base SHALL produce a `gemini2_3072`-suffixed
   collection via the existing `CollectionNamer` with no change to `run()`.
2. WHEN the Media_Route runs with `--images <glob>`, THE ingester SHALL add
   image vectors (`modality="image"`) to that same collection.
3. THE Benchmark_Runner SHALL compute P@5 and MRR for `gemini2_3072` against the
   `titan1024` baseline (and `mpnet768`) on the same query set.
4. THE evaluation SHALL record P@5 / MRR side-by-side and a cross-modal smoke
   result (text query → image hit) in the phase report.

### Requirement 13: Documentation

**User Story:** As a maintainer reading project history, I want the provider
addition recorded in CHANGELOG and cross-referenced with the wiki and SDD
workflow, so the evaluation trail is auditable.

#### Acceptance Criteria

1. THE CHANGELOG.md SHALL include a dated entry summarizing the
   `gemini-embedding-2` provider addition, the files touched, and the test-count
   delta.
2. THE phase report SHALL cross-reference the wiki page
   `Gemini-Embedding-Provider-Evaluation-and-Key-Request` and the SDD workflow
   `phase66_gemini_embedding_provider_evaluation.md`.

### Requirement 14: Out-of-scope constraints

**User Story:** As a reviewer, I want the non-goals codified as constraints, so
the implementation stays bounded.

#### Acceptance Criteria

1. THE feature SHALL NOT modify the existing `BedrockProvider` or
   `LocalProvider` implementations.
2. THE feature SHALL NOT re-ingest, delete, or alter the existing `titan1024` or
   `mpnet768` OpenSearch collections.
3. THE feature SHALL NOT add a Google SDK or any third-party HTTP library to
   `pyproject.toml` or `package.json`.
4. THE feature SHALL NOT implement `gemini-embedding-001` support or any
   `taskType`-enum task control.
5. THE feature SHALL NOT implement audio, video, or PDF ingestion in this phase
   (natural follow-ons via the same `inline_data` mechanism).
6. THE feature SHALL NOT commit or hardcode any API key value; the key is
   provided only via the environment.
