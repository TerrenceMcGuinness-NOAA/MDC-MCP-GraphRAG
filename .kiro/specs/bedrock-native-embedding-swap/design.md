# Design Document

## Overview

Phase C-2c replaces the `sentence-transformers/all-mpnet-base-v2`
query-embedding path in `mcp_server_python/src/data/opensearch_adapter.py`
with a Bedrock Titan Embed Text V2 path against the production
`mdc-{domain}-titan1024` indices.

Today every `search_documentation` call on the staging runtime
(`mdc_mcp_rag_server_python-v5K2F8BGrN` v5, image `python-all-tools-v3`)
fails with `No module named sentence_transformers`. The runtime image
intentionally excludes `torch` and `transformers`, but the OpenSearch
adapter still tries to lazy-import `SentenceTransformer` for query
embeddings. The Node.js side already implements the multi-model
`LocalProvider` / `BedrockProvider` + `ModelProfile` pattern in
`mcp_server_node/scripts/embedding_provider.py` and
`mcp_server_node/scripts/embedding_registry.py`. This phase ports that
abstraction to the Python runtime, makes Bedrock the default, and keeps
the legacy `mpnet768` path reachable as a clearly-erroring parity-debug
slot.

What changes:

- **New** `src/data/embedding_registry.py` — `ModelProfile` + 6 built-in
  profiles, ported from the Node.js singleton.
- **New** `src/data/embedding_provider.py` — `EmbeddingProvider` ABC,
  `BedrockProvider`, `LocalProvider`, `create_provider` factory,
  `EmbeddingError`. Bedrock is the focus; `LocalProvider` raises
  `EmbeddingError` at construction in this image.
- **Modified** `src/data/opensearch_adapter.py` — drop the
  `sentence_transformers` lazy import and the `_mpnet_model`
  module-level cache, replace `_generate_embedding` to delegate to the
  active provider via `asyncio.to_thread`, resolve the active profile
  in `__init__`.
- **Modified** `src/config/aws_config.py` — replace the static
  `PRODUCTION_INDICES` dict with a profile-aware
  `get_production_indices(profile_short_name)` function and extend
  `resolve_index` to be profile-aware.
- **Modified** `src/config/environment.py` — add `MCP_EMBEDDING_PROFILE`
  parsing, validation, and the `[WARN]` log line on `mpnet768`.
- **Modified** `pyproject.toml` — confirm `boto3` is present, do **not**
  add `sentence-transformers` / `torch` / `transformers`.
- **Modified** `tests/conftest.py` — fixture for a mocked
  `BedrockProvider`, replacing the old mpnet stubs.
- **New** `tests/integration/test_bedrock_embedding.py` — `RUN_INTEGRATION=1`
  gated smoke test that issues one real Bedrock call.

The deliverable is the `python-titan-v1` ECR image and a redeployed
staging runtime with `MCP_EMBEDDING_PROFILE=titan1024` set explicitly.

## Architecture

Targeting the `titan1024` indices via Bedrock-Runtime is a single-arrow
swap at the embedding step. The rest of the OpenSearchAdapter — the
hybrid BM25 + k-NN body, the SigV4 transport, the retry wrapper, the
hit formatter — stays intact.

```
              ┌─────────────────────────────────────────────────┐
              │  FastMCP tool handler (e.g. search_documentation)│
              └──────────────────────┬──────────────────────────┘
                                     │ await
                                     ▼
              ┌─────────────────────────────────────────────────┐
              │            OpenSearchAdapter                    │
              │  - resolve_index(collection, profile)           │
              │  - _generate_embedding(query_text)              │
              │  - _build_hybrid_query(...)                     │
              │  - _search_with_retry(index, body)              │
              └─────────────┬─────────────────┬─────────────────┘
                            │                 │ asyncio.to_thread
                            │                 ▼
                            │   ┌──────────────────────────────┐
                            │   │   EmbeddingProvider (ABC)    │
                            │   │   .embed(texts) -> vectors   │
                            │   │   .dimensions: int           │
                            │   └────┬───────────────────┬─────┘
                            │        │                   │
                            │   create_provider(profile)
                            │        │                   │
                            │        ▼                   ▼
                            │  ┌────────────┐    ┌──────────────┐
                            │  │ Bedrock-   │    │  Local-      │
                            │  │ Provider   │    │  Provider    │
                            │  │ (boto3)    │    │  (raises in  │
                            │  │            │    │   runtime    │
                            │  │            │    │   image)     │
                            │  └─────┬──────┘    └──────┬───────┘
                            │        │                   │
                            │        ▼                   ▼
                            │  ┌────────────┐    ┌─────────────────┐
                            │  │ Bedrock    │    │ sentence-       │
                            │  │ Runtime    │    │ transformers    │
                            │  │ (Titan /   │    │ (NOT shipped)   │
                            │  │  Nova)     │    │                 │
                            │  └────────────┘    └─────────────────┘
                            │
                            │           ┌──────────────────────────┐
                            └──────────►│ EmbeddingModelRegistry   │
                                        │  - mpnet768   (local)    │
                                        │  - titan1024  (bedrock)  │
                                        │  - nova256/512/1024/3072 │
                                        │  - default = titan1024   │
                                        └──────────────────────────┘
                                              ▲
                                              │ resolved at __init__
                                              │
                                ┌─────────────┴────────────────┐
                                │  MCP_EMBEDDING_PROFILE       │
                                │  parsed in environment.py    │
                                └──────────────────────────────┘
```

`MCP_EMBEDDING_PROFILE` is parsed once in `environment.py`, the
`OpenSearchAdapter` constructor calls
`EmbeddingModelRegistry().get_profile(name)` and then
`create_provider(profile)`, and from that point on every query uses the
selected provider.

## Components and Interfaces

### NEW · `src/data/embedding_registry.py`

- **Purpose.** Single source of truth for embedding model descriptors.
  Mirrors `mcp_server_node/scripts/embedding_registry.py` field-for-field.
- **Public surface.**
  - `ModelProfile` (frozen dataclass) — `short_name`, `provider`,
    `model_id`, `dimensions`, `supports_matryoshka`,
    `supports_multimodal`, `provider_params`.
  - `EmbeddingModelRegistry` (singleton) — `get_profile`, `get_default`,
    `list_profiles`, `register`.
- **Key implementation notes.**
  - Six built-in profiles registered in `_register_builtins`:
    `mpnet768` (local), `titan1024` (bedrock; the new default),
    `nova256` / `nova512` / `nova1024` / `nova3072` (bedrock,
    multimodal Matryoshka). Field values match the Node.js port.
  - `get_profile` raises `KeyError` with the list of registered names
    on a miss (Requirement 1.5).
  - `get_default()` returns `titan1024` (Requirement 1.3).
- **Dependencies.** None — pure-Python dataclass + dict.

### NEW · `src/data/embedding_provider.py`

- **Purpose.** Provider-abstraction layer with a Bedrock-default factory.
- **Public surface.**
  - `EmbeddingError(RuntimeError)` — error class for failed embeds.
  - `EmbeddingProvider` (ABC) — `embed(texts)`, `dimensions` property.
  - `BedrockProvider(EmbeddingProvider)` — boto3-backed.
  - `LocalProvider(EmbeddingProvider)` — sentence-transformers backed;
    constructor raises `EmbeddingError` in the runtime image.
  - `create_provider(profile: ModelProfile) -> EmbeddingProvider`.
- **Key implementation notes.**
  - `BedrockProvider.__init__` lazy-imports `boto3`, builds a single
    process-scoped `bedrock-runtime` client bound to
    `os.getenv("AWS_REGION", "us-east-1")` (Requirements 3.7, 3.8).
  - `BedrockProvider.embed`:
    - Builds the request body per profile family
      (Titan: `{"inputText": text, **provider_params}`;
      Nova: the `nova-multimodal-embed-v1` schema with
      `taskType="SINGLE_EMBEDDING"`,
      `singleEmbeddingParams.embeddingDimension = profile.dimensions`,
      `singleEmbeddingParams.text.value = text` — Requirements 3.2, 3.3).
    - Calls `invoke_model(modelId, body=json.dumps(body),
      contentType="application/json", accept="application/json")` once
      per input string (Requirement 3.1).
    - Parses `embeddings[0].embedding` for Nova, `embedding` for Titan,
      and returns a list of float vectors of length
      `profile.dimensions` (Requirements 3.4, 3.5).
    - Wraps the call in a 4-attempt retry loop with sleeps of
      `1s, 2s, 4s` before attempts 2, 3, 4. Retries on
      `ClientError` whose `response["Error"]["Code"]` is in
      `{"ThrottlingException", "TooManyRequestsException",
      "ServiceUnavailableException", "InternalServerException"}` or
      whose HTTP status is 429 or 5xx (Requirements 4.1, 4.2).
    - On exhaustion or non-transient error, raises
      `EmbeddingError(f"Bedrock embed failed model={...} input_len=...:
      {exc}")` (Requirements 4.3, 4.4).
  - `LocalProvider.__init__`:
    - Tries `import sentence_transformers`.
    - On `ImportError`, emits one `[ERROR]` log line identifying the
      active profile (`mpnet768`) and raises
      `EmbeddingError("sentence-transformers is not installed in the
      runtime image; mpnet768 is parity-debug-only on this runtime")`
      (Requirements 9.1, 9.2).
    - The body of `embed` is preserved for parity with the Node.js
      port but is unreachable in the runtime image because the
      constructor errors first.
  - `create_provider` dispatches on `profile.provider`. Unknown
    provider raises `ValueError` (Requirement 2.5).
- **Dependencies.** `embedding_registry.ModelProfile`. `boto3` at
  call time (already a runtime dependency).

### MODIFIED · `src/data/opensearch_adapter.py`

- **Purpose.** Stop carrying the `sentence_transformers` default path,
  delegate query embeddings to the active `EmbeddingProvider`.
- **Public surface.** Unchanged: `connect`, `query`,
  `multi_collection_query`, `health_check`, `close`,
  `OpenSearchQueryError`. Constructor signature unchanged
  (`embedding_function` override remains supported).
- **Key implementation notes.**
  - Drop the lazy `from sentence_transformers import SentenceTransformer`
    inside `_default_mpnet_embedding`, drop `_default_mpnet_embedding`
    entirely, and drop the module-level `_MPNET` / `_mpnet_model()`
    cache (Requirements 6.1, 6.2, 6.3).
  - `__init__` resolves the active profile and provider once:
    ```python
    from src.data.embedding_registry import EmbeddingModelRegistry
    from src.data.embedding_provider import create_provider

    profile_name = os.getenv("MCP_EMBEDDING_PROFILE", "titan1024")
    self._profile = EmbeddingModelRegistry().get_profile(profile_name)
    self._provider = (
        None if embedding_function is not None
        else create_provider(self._profile)
    )
    ```
    `ConfigError` is raised earlier in `environment.py`; by the time
    `OpenSearchAdapter` runs, the profile name is known-valid.
    (Requirements 6.4, 6.5.)
  - `_generate_embedding` becomes:
    ```python
    async def _generate_embedding(self, query_text: str) -> list[float]:
        fn = self._embedding_function or self._provider.embed
        try:
            embeddings = await asyncio.to_thread(fn, [query_text])
        except EmbeddingError as exc:
            raise OpenSearchQueryError(str(exc), status=None) from exc
        return list(embeddings[0])
    ```
    Returning `embeddings[0]` matches Requirement 5.3, and the
    `EmbeddingError → OpenSearchQueryError(status=None)` translation
    matches Requirement 9.3.
  - `query` now passes the active profile's `short_name` through to
    `resolve_index` (see below).
- **Dependencies.** `src.data.embedding_provider`,
  `src.data.embedding_registry`, `src.config.aws_config.resolve_index`.

### MODIFIED · `src/config/aws_config.py`

- **Purpose.** Make the index resolver profile-aware so a `titan1024`
  query vector hits a `titan1024` index.
- **Public surface.**
  - **Removed** module-level `PRODUCTION_INDICES: dict[str, str]`.
  - **New** `PRODUCTION_INDICES_BY_PROFILE: dict[str, dict[str, str]]`
    keyed by profile `short_name`. Includes a `titan1024` map and an
    `mpnet768` map (parity-debug only).
  - **New** `get_production_indices(profile_short_name: str) ->
    dict[str, str]` returns the inner map for the given profile, or
    `{}` for profiles with no registered map (the Nova family for
    now).
  - **Changed** `resolve_index(collection: str, profile_short_name:
    str = "titan1024") -> str` consults the profile-specific map and
    falls back to the collection name unchanged when the collection
    is not in the map (Requirements 8.1 – 8.5).
- **Key implementation notes.**
  - `titan1024` map (Requirement 8.1):
    | logical collection | OpenSearch index |
    |---|---|
    | `code-with-context-v8-0-0` | `mdc-code-context-titan1024` |
    | `global-workflow-docs-v8-0-0` | `mdc-workflow-docs-titan1024` |
    | `jjobs-v8-0-0` | `mdc-jjobs-titan1024` |
    | `community-summaries` | `mdc-community-summaries-titan1024` |
    | `ee2-standards-v5-0-0-enhanced` | `mdc-ee2-standards-titan1024` |
  - `mpnet768` map (Requirement 8.2) preserves the prior values so the
    parity-debug path can still address those indices when the
    runtime image happens to have sentence-transformers (it does not,
    in this image — but the mapping must remain for completeness and
    for the upstream Node.js MCP that does ship the dependency).
  - Nova profiles return `{}` from `get_production_indices`, and
    `resolve_index` therefore returns the collection name unchanged
    (Requirement 8.3, 8.4) — those indices have not been created yet.
  - `resolve_index` is the only public hot-path call site, so existing
    callers with a single positional argument continue to work
    (default kwarg is `titan1024`).
- **Dependencies.** None.

### MODIFIED · `src/config/environment.py`

- **Purpose.** Surface `MCP_EMBEDDING_PROFILE` as a typed config field
  with validation and warn on `mpnet768`.
- **Public surface.**
  - `ServerConfig` gains an `embedding_profile: str = "titan1024"`
    field.
  - `load_config` parses the env var, validates against the registered
    profile names from `EmbeddingModelRegistry().list_profiles()`, and
    raises `ConfigError` listing the six accepted values on bad input
    (Requirements 7.1 – 7.3).
  - When the resolved profile is `mpnet768`, `load_config` (or the
    server `main`) emits a single `[WARN]` log line:
    `"[WARN] MCP_EMBEDDING_PROFILE=mpnet768 — legacy parity-debug
    fallback active; sentence-transformers is not installed in this
    image"` (Requirement 7.4).
- **Key implementation notes.**
  - The `[WARN]` line is emitted at most once per process. Log emission
    happens after the parse step so a `ConfigError` short-circuits the
    process before any warn fires.
  - Default is `titan1024` to match Requirement 7.1 and the registry
    default.
- **Dependencies.** `src.data.embedding_registry`.

### MODIFIED · `pyproject.toml`

- **Purpose.** Confirm runtime deps shape; verify no transitive pull of
  `torch` / `transformers`.
- **Changes.** No additions. Confirm `boto3` is already in
  `[project].dependencies` from Phase B2 (`OpenSearchAdapter` already
  uses SigV4). Verify the lock file does not transitively pull
  `sentence-transformers`, `torch`, or `transformers` (Requirement 10).
- **Dependencies.** N/A.

### MODIFIED · `tests/conftest.py`

- **Purpose.** Replace the existing mpnet stubs with a mocked
  `BedrockProvider` fixture that the unit suite uses to exercise
  `OpenSearchAdapter` without hitting AWS.
- **Public surface.**
  - `mock_bedrock_provider` fixture — yields a `BedrockProvider` whose
    `embed(texts)` returns `[[0.0] * profile.dimensions for _ in texts]`.
  - `bedrock_provider_factory` fixture — patches
    `src.data.embedding_provider.create_provider` so the adapter
    constructor pulls the mock provider for any profile.
- **Key implementation notes.**
  - Existing fixtures that injected
    `embedding_function=lambda xs: [[0.0]*768 for _ in xs]` into
    `OpenSearchAdapter` are renamed/retargeted; their semantics carry
    over but the dimension is now derived from the active profile so
    the same fixture works for `titan1024` (1024-dim) tests.
- **Dependencies.** `pytest`, `unittest.mock`.

### NEW · `tests/integration/test_bedrock_embedding.py`

- **Purpose.** One real Bedrock call, gated on `RUN_INTEGRATION=1`,
  records p50/p95 latency for the phase report.
- **Public surface.** A single `pytest.mark.integration`-marked
  `test_titan1024_embed_hello_world` test plus a small latency-stats
  helper.
- **Key implementation notes.**
  - Skips when `os.getenv("RUN_INTEGRATION") != "1"`.
  - Builds the `titan1024` profile, creates a real `BedrockProvider`,
    runs `provider.embed(["hello world"])` 5 times, asserts each
    returned vector has length 1024, computes p50/p95 from
    `time.perf_counter` deltas, and prints the stats.
  - Uses the deployment AWS region (`us-east-1`).
- **Dependencies.** `boto3` credentials in the local environment.

## Data Models

```python
# src/data/embedding_registry.py

@dataclass(frozen=True)
class ModelProfile:
    short_name: str                          # e.g. "titan1024"
    provider: str                            # "local" | "bedrock"
    model_id: str                            # HF name or Bedrock model ID
    dimensions: int                          # vector length
    supports_matryoshka: bool = False
    supports_multimodal: bool = False
    provider_params: dict[str, Any] = field(default_factory=dict)


class EmbeddingModelRegistry:
    _instance: EmbeddingModelRegistry | None
    _profiles: dict[str, ModelProfile]
    _default: str  # = "titan1024"

    def __new__(cls) -> EmbeddingModelRegistry: ...
    def get_profile(self, short_name: str) -> ModelProfile: ...
    def get_default(self) -> ModelProfile: ...
    def list_profiles(self) -> list[str]: ...
    def register(self, profile: ModelProfile) -> None: ...
```

```python
# src/data/embedding_provider.py

class EmbeddingError(RuntimeError):
    """Raised when embedding generation fails."""


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...


class BedrockProvider(EmbeddingProvider):
    _profile: ModelProfile
    _client: Any  # botocore bedrock-runtime client

    # tunables (mirrored from Node.js):
    _MAX_RETRIES: int = 3
    _BACKOFF_S: tuple[float, float, float] = (1.0, 2.0, 4.0)
    _RETRYABLE_CODES: frozenset[str] = frozenset({
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "InternalServerException",
    })
    _RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __init__(self, profile: ModelProfile) -> None: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimensions(self) -> int: ...


class LocalProvider(EmbeddingProvider):
    _profile: ModelProfile

    def __init__(self, profile: ModelProfile) -> None:
        # Always raises EmbeddingError in the runtime image because
        # `sentence_transformers` is not installed.
        ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimensions(self) -> int: ...


def create_provider(profile: ModelProfile) -> EmbeddingProvider: ...
```

## Sequence Diagrams

### Successful query flow (`titan1024`)

```
search_documentation     OpenSearchAdapter        BedrockProvider           Bedrock-Runtime          OpenSearch
        │                       │                       │                          │                      │
        │ query(...)            │                       │                          │                      │
        ├──────────────────────►│                       │                          │                      │
        │                       │ resolve_index(coll,   │                          │                      │
        │                       │   "titan1024")        │                          │                      │
        │                       │ → mdc-…-titan1024     │                          │                      │
        │                       │                       │                          │                      │
        │                       │ _generate_embedding   │                          │                      │
        │                       │ asyncio.to_thread     │                          │                      │
        │                       │   provider.embed([q]) │                          │                      │
        │                       ├──────────────────────►│                          │                      │
        │                       │                       │ invoke_model(            │                      │
        │                       │                       │   modelId=titan-v2,      │                      │
        │                       │                       │   body={inputText, …})   │                      │
        │                       │                       ├─────────────────────────►│                      │
        │                       │                       │  embedding[1024 floats]  │                      │
        │                       │                       │◄─────────────────────────┤                      │
        │                       │ vector[1024]          │                          │                      │
        │                       │◄──────────────────────┤                          │                      │
        │                       │ _build_hybrid_query   │                          │                      │
        │                       │ _search_with_retry    │                          │                      │
        │                       ├──────────────────────────────────────────────────────────────────►│
        │                       │                                                          hits     │
        │                       │◄────────────────────────────────────────────────────────────────────┤
        │                       │ _format_hits(...)     │                          │                      │
        │ list[DocumentResult]  │                       │                          │                      │
        │◄──────────────────────┤                       │                          │                      │
```

### `mpnet768` parity-debug flow (intentional clean error)

```
search_documentation     OpenSearchAdapter      LocalProvider          tool handler
        │                       │                     │                       │
        │ (process startup)     │                     │                       │
        │ env: MCP_EMBEDDING_PROFILE=mpnet768         │                       │
        │ environment.py emits [WARN] log line        │                       │
        │                       │                     │                       │
        │                       │ __init__:           │                       │
        │                       │ create_provider(    │                       │
        │                       │   mpnet768 profile) │                       │
        │                       ├────────────────────►│                       │
        │                       │                     │ import               │
        │                       │                     │ sentence_transformers│
        │                       │                     │ → ImportError        │
        │                       │                     │ log.error(…)         │
        │                       │   EmbeddingError    │                       │
        │                       │◄────────────────────┤                       │
        │ (later) query(...)    │                     │                       │
        ├──────────────────────►│                     │                       │
        │                       │ _generate_embedding │                       │
        │                       │ catches EmbeddingError                      │
        │                       │ raises OpenSearchQueryError(status=None)    │
        │                       ├────────────────────────────────────────────►│
        │                       │                     │                       │
        │ structured MCP error  │                     │                       │
        │◄──────────────────────┴─────────────────────┴───────────────────────┘
```

(Whether `LocalProvider.__init__` runs at adapter-construction time or
lazily on first `query` is a small implementation choice; the design
schedules it at construction so the error surfaces during health-check
rather than on the first user request. `OpenSearchAdapter.__init__`
catches `EmbeddingError` raised by `create_provider`, stores it on the
instance, and re-raises it as `OpenSearchQueryError` from
`_generate_embedding` — see the second arrow above.)

## Error Handling

(Error classes, when raised, retry behavior — explicitly references
Requirement 4.)

The retry policy mirrors the Node.js `BedrockProvider` behavior, scoped
to Bedrock-Runtime errors only. OpenSearch retries are unchanged from
Phase B2 (`_search_with_retry` already handles 429/5xx with the same
1s/2s/4s schedule).

| Error class | Source | When raised | Retry behavior | Final raised type |
|---|---|---|---|---|
| `botocore.exceptions.ClientError` with code `ThrottlingException` / `TooManyRequestsException` / `ServiceUnavailableException` / `InternalServerException` | `bedrock-runtime.invoke_model` | Bedrock returns 429 or 5xx | Up to 3 retries, sleeps 1s / 2s / 4s before attempts 2, 3, 4 (Req 4.1, 4.2) | After exhaustion: `EmbeddingError(f"Bedrock embed failed model={profile.model_id} input_len={len(text)}: {exc}")` (Req 4.3) |
| `ClientError` with any other code (e.g. `ValidationException`, `AccessDeniedException`) | `bedrock-runtime.invoke_model` | Bedrock returns 4xx ≠ 429 | No retry | `EmbeddingError(...)` raised on first attempt (Req 4.4) |
| Other `Exception` (network, JSON parse, unexpected response shape) | `boto3.invoke_model` / `json.loads` | Transport failure or schema break | No retry | `EmbeddingError(...)` (Req 4.4) |
| `ImportError` for `sentence_transformers` | `LocalProvider.__init__` | `mpnet768` selected, dep not installed | No retry | `EmbeddingError("sentence-transformers is not installed …")` after one `[ERROR]` log line (Req 9.1, 9.2) |
| `EmbeddingError` reaching `OpenSearchAdapter` | adapter `_generate_embedding` | Provider raised one of the above | N/A | `OpenSearchQueryError(message, status=None)` so MCP tool handlers surface a structured error (Req 9.3) |
| `KeyError` from `EmbeddingModelRegistry.get_profile` | adapter `__init__` | `MCP_EMBEDDING_PROFILE` unknown — should not happen because `environment.py` validates first | N/A | propagates as `KeyError` (defense-in-depth; user-facing path is `ConfigError` from `environment.py`, Req 7.3) |

The retry sleeps are wall-clock `time.sleep` inside the threadpool
worker, not `await asyncio.sleep`, because `BedrockProvider.embed` is a
sync function called via `asyncio.to_thread`. This keeps the event loop
free for other handlers while a single embed retries.

## Deployment Plan

1. **Build.** From `mcp_server_python/`:
   ```bash
   docker build --platform linux/arm64 \
     -t 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-titan-v1 \
     -f Dockerfile .
   ```
2. **Capture image-size delta** (Requirement 10.5):
   ```bash
   docker image inspect mdc-mcp-rag:python-titan-v1 --format '{{.Size}}'
   docker image inspect mdc-mcp-rag:python-all-tools-v3 --format '{{.Size}}'
   # After push:
   aws ecr describe-images --region us-east-1 \
     --repository-name mdc-mcp-rag \
     --image-ids imageTag=python-titan-v1 imageTag=python-all-tools-v3
   ```
   Record both uncompressed (local) and compressed-manifest (ECR) sizes
   in the phase report.
3. **Push.**
   ```bash
   aws ecr get-login-password --region us-east-1 \
     | docker login --username AWS --password-stdin \
         903050880929.dkr.ecr.us-east-1.amazonaws.com
   docker push \
     903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-titan-v1
   ```
4. **Update runtime** (preserves the existing Phase C-2b env vars and
   adds `MCP_EMBEDDING_PROFILE` explicitly):
   ```bash
   aws bedrock-agentcore-control update-agent-runtime \
     --region us-east-1 \
     --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN \
     --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-titan-v1"}}' \
     --role-arn arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role \
     --network-configuration '{"networkMode":"VPC","networkModeConfig":{"subnets":["subnet-0e13af6b3a9a6416f","subnet-04447750c61bd7e06"],"securityGroups":["sg-096489a0876cc78c1"]}}' \
     --protocol-configuration '{"serverProtocol":"MCP"}' \
     --lifecycle-configuration '{"idleRuntimeSessionTimeout":900,"maxLifetime":28800}' \
     --environment-variables '{
        "DB_BACKEND":"aws",
        "NEPTUNE_ENDPOINT":"https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182",
        "OPENSEARCH_ENDPOINT":"https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com",
        "AWS_REGION":"us-east-1",
        "MCP_STATELESS_HTTP":"true",
        "MCP_WORKFLOW_ROOT":"/app/supported_repos/global-workflow",
        "MCP_EMBEDDING_PROFILE":"titan1024"
      }'
   ```
   `MCP_EMBEDDING_PROFILE=titan1024` is set explicitly even though it is
   the default, to make the active configuration auditable from the
   AgentCore console.
5. **Live validation** (Requirement 12):
   - `get_server_info({})` — confirm 51/51 tools, 9/9 modules.
   - `mcp_health_check({deep:true})` — Vector status `healthy`, doc-count
     totals > 100 000.
   - `search_documentation({query:"data assimilation cycling"})` —
     ≥ 1 hit.
   - `get_knowledge_base_status({})` — vector status `healthy`, no
     `sentence_transformers missing` line.
6. **Rollback** is a single command back to the prior image:
   ```bash
   aws bedrock-agentcore-control update-agent-runtime \
     --region us-east-1 \
     --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN \
     --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-all-tools-v3"}}' \
     --role-arn arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role \
     --network-configuration '{...same as above...}' \
     --protocol-configuration '{"serverProtocol":"MCP"}' \
     --lifecycle-configuration '{...same as above...}'
   ```
   `python-all-tools-v3` remains in ECR per Requirement 13.2.

## Testing Strategy

This phase swaps one network-bound embedding implementation for another
and adds a small profile-routing layer. The interesting behavior is
discrete (does the right boto3 call get made? does the right index get
hit?) and is best verified by mock-based unit tests plus one real
integration call. **Property-based testing is not applicable** here:
the embedding step is a side-effect-only call to an external service,
the profile / index resolver is a small fixed mapping with no
parametric input space, and the retry schedule is a specific timing
contract rather than a universal property.

### Unit tests (Requirement 11.1 – 11.6, 11.8)

Suite count baseline post-Phase C-2b is **716** tests at
`mcp_server_python/tests/`. The Phase C-2c additions:

| Test file | Coverage |
|---|---|
| `tests/unit/test_embedding_registry.py` | profile lookup hits, lookup miss raises `KeyError` with full list, `get_default()` is `titan1024`, `list_profiles()` returns 6 names, `register()` adds a custom profile (Req 11.1). |
| `tests/unit/test_bedrock_provider.py` | `embed` returns vectors of `profile.dimensions` length for `titan1024` and `nova1024`; request body for Titan has `inputText` + merged `provider_params`; request body for Nova has the `nova-multimodal-embed-v1` schema with the right `embeddingDimension`; `boto3.client("bedrock-runtime", region_name=...)` honored `AWS_REGION` (Req 11.2). |
| `tests/unit/test_bedrock_provider_retry.py` | `boto3.invoke_model` mock raises `ThrottlingException` thrice then succeeds — total elapsed (with `time.sleep` mocked to capture call args) is `1s + 2s + 4s` matching the schedule; HTTP 500 retried; HTTP 503 retried; HTTP 400 `ValidationException` not retried; after 4 failures a single `EmbeddingError` carrying the model id + last error surface (Req 11.3). |
| `tests/unit/test_local_provider.py` | with `sentence_transformers` masked from `sys.modules`, `LocalProvider(mpnet768_profile)` raises `EmbeddingError` whose message contains `sentence-transformers is not installed`; one `[ERROR]` log line emitted (Req 11.4). |
| `tests/unit/test_aws_config_resolver.py` | `resolve_index(coll, "titan1024")` for each of the 5 known collections returns the `mdc-…-titan1024` index; same for `mpnet768` returns the `mdc-…-mpnet768` index; unknown collection passes through unchanged for both profiles; nova profile returns collection unchanged (Req 11.5). |
| `tests/unit/test_opensearch_adapter_embedding.py` | rewrites prior mpnet stubs (Req 11.6). Uses the `mock_bedrock_provider` fixture; asserts `_generate_embedding` returns the first vector from `provider.embed`; asserts `EmbeddingError` from the provider becomes `OpenSearchQueryError(status=None)`; asserts `MCP_EMBEDDING_PROFILE=titan1024` selects a `BedrockProvider`; asserts `MCP_EMBEDDING_PROFILE=mpnet768` triggers `LocalProvider` whose construction error propagates as `OpenSearchQueryError`. |
| `tests/unit/test_environment_embedding_profile.py` | unset → `titan1024`; `titan1024`/`nova256`/`nova512`/`nova1024`/`nova3072`/`mpnet768` accepted; bogus value raises `ConfigError` whose message lists the six accepted values; `mpnet768` triggers exactly one `[WARN]` log line (Req 7.x). |

The full suite must pass at **716 + N** where N is the new tests
landed by this phase (Req 11.8 — note: 716 is the post-C-2b baseline,
not 688; the C-2b additions bumped the count).

### Integration test (Requirement 11.7, 12.4)

`tests/integration/test_bedrock_embedding.py` is gated on
`RUN_INTEGRATION=1`. It:

- Builds the `titan1024` profile from the registry.
- Constructs a real `BedrockProvider` (real boto3, real credentials).
- Runs `provider.embed(["hello world"])` 5 times, asserts each vector
  has length 1024.
- Computes p50 and p95 from `time.perf_counter` deltas across the 5
  runs and prints them. The phase report quotes both values
  (Requirement 12.4).
- Skips entirely without `RUN_INTEGRATION=1`, so the default unit-suite
  run never reaches Bedrock.

### Live validation (Requirement 12)

Run from the operator workstation against the deployed staging runtime
post-update. The 4 calls listed in the Deployment Plan above. Outputs
captured in
`docs/reports/2026-05-14-phase-c2c-bedrock-embedding-swap.md`.

## Migration Path

- **No re-ingest.** This phase does not touch any OpenSearch index
  contents (Requirement 15.1).
- **`mpnet768` indices stay** in OpenSearch (Requirement 15.3) and
  remain reachable via `MCP_EMBEDDING_PROFILE=mpnet768`. In the
  current `python-titan-v1` runtime image, that path raises a clean
  `OpenSearchQueryError` with the `sentence-transformers not
  installed` message — the indices are addressable, but the runtime
  cannot generate query vectors for them. A future image could ship
  `sentence-transformers` if a real parity-debug from Python is ever
  needed; today the parity comparison happens against the Node.js MCP
  which does ship the dependency.
- **`titan1024` indices are the production target** going forward
  (the Phase 52 ingestion already populated them with ~120 000
  documents). All `search_documentation` traffic on the staging
  runtime now hits this corpus.
- **Operators flipping profiles** for parity-debug should expect:
  - `titan1024` (default): healthy.
  - `nova256` / `nova512` / `nova1024` / `nova3072`: provider works
    against Bedrock, but `resolve_index` returns the collection name
    unchanged because no `mdc-…-nova{N}` indices exist yet — searches
    will 404 against OpenSearch. Reserved for the next ingestion
    phase.
  - `mpnet768`: clean `EmbeddingError → OpenSearchQueryError` chain,
    surfaced via the structured MCP error path.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bedrock query embedding adds a network round trip vs the prior in-process MPNet model | High | Single-digit-to-~100ms latency increase per query | Capture p50/p95 in the integration test (Req 12.4); document in the phase report; consider a per-session embedding cache as future work, keyed by query string + profile. |
| `titan1024` and `mpnet768` have different relevance characteristics | Medium | Top-N hit lists may shift vs the Node.js MCP baseline | Surface in the parity assessment; defer RRF fusion-weight tuning to a follow-up phase. The hybrid `bool.should` BM25+kNN body in `_build_hybrid_query` is unchanged here, so any shift is purely from the dense-vector side. |
| Bedrock throttling at high QPS in staging | Low (staging) | Spurious `EmbeddingError`s | The 1s/2s/4s retry schedule absorbs single-flake throttles; sustained throttling is out-of-scope and tracked for future work (per-account rate limits, request batching). |
| Container dependency drift — a transitive dep pulls `torch` back in | Low | Image bloat returns | Verify `pyproject.toml` runtime deps with `pip install --dry-run -r ...` and `pip-audit` / `pip list` against the built image; assert `sentence-transformers`, `torch`, `transformers` are absent (Req 10.2 – 10.4). |
| `MCP_EMBEDDING_PROFILE` set on production by mistake | Low | Selects a non-default model on a non-staging runtime | Production cutover (Phase D) gates on the `mdc_mcp_rag_server-TMXDllG2Wi` runtime, which is operator-managed; `MCP_EMBEDDING_PROFILE` is opt-in and defaulted to `titan1024` so the safe behavior is the absence of the env var. |

## Traceability Matrix

| Requirement | Satisfied by |
|---|---|
| **R1** ModelProfile registry | NEW `src/data/embedding_registry.py` (Components); `ModelProfile` + `EmbeddingModelRegistry` types (Data Models); `tests/unit/test_embedding_registry.py` (Test Strategy). |
| **R2** EmbeddingProvider abstraction + factory | NEW `src/data/embedding_provider.py` — `EmbeddingProvider` ABC, `create_provider` (Components, Data Models). |
| **R3** Bedrock-backed query embedding | `BedrockProvider.__init__` / `embed` notes (Components); request-body shape rules in Data Models; sequence diagram §"Successful query flow"; `tests/unit/test_bedrock_provider.py`. |
| **R4** Retry and backoff for transient Bedrock errors | `BedrockProvider` retry constants + behavior (Components and Interfaces, Data Models); Error Handling table (full row); `tests/unit/test_bedrock_provider_retry.py`. |
| **R5** Async integration with `OpenSearchAdapter` | MODIFIED `src/data/opensearch_adapter.py` (`_generate_embedding` rewrite); sequence diagram §"Successful query flow"; `tests/unit/test_opensearch_adapter_embedding.py`. |
| **R6** Remove sentence-transformers default path | MODIFIED `src/data/opensearch_adapter.py` notes (drop import / `_default_mpnet_embedding` / `_mpnet_model`); MODIFIED `pyproject.toml` (no add); Risks row "Container dependency drift". |
| **R7** `MCP_EMBEDDING_PROFILE` env var | MODIFIED `src/config/environment.py` (Components); `tests/unit/test_environment_embedding_profile.py`; `[WARN]` log line in the same module. |
| **R8** Profile-aware index resolver | MODIFIED `src/config/aws_config.py` — `PRODUCTION_INDICES_BY_PROFILE`, `get_production_indices`, profile-aware `resolve_index` (Components); `tests/unit/test_aws_config_resolver.py`. |
| **R9** `mpnet768` fallback raises clear error | `LocalProvider.__init__` notes (Components); sequence diagram §"`mpnet768` parity-debug flow"; Error Handling table rows for `ImportError` and `EmbeddingError → OpenSearchQueryError`; `tests/unit/test_local_provider.py`. |
| **R10** Runtime container image dependencies | MODIFIED `pyproject.toml` (Components); Risks row "Container dependency drift"; Deployment Plan §"Capture image-size delta". |
| **R11** Unit and integration tests | Test Strategy §"Unit tests" full table + §"Integration test"; Phase C-2b baseline of 716 tests called out in §"Unit tests" preface. |
| **R12** Live validation against staging runtime | Deployment Plan §"Live validation" (4 calls listed) + integration p50/p95 capture in Test Strategy §"Integration test". |
| **R13** Deploy artifacts and rollback targets | Deployment Plan §"Build" / §"Push" / §"Update runtime" / §"Rollback"; `python-all-tools-v3` named as preserved rollback target. |
| **R14** Documentation and changelog updates | Phase report path + `[8.22.3]` CHANGELOG section + steering update — operationalized in Deployment Plan §"Live validation" deliverables and post-deploy notes (the markdown updates land alongside the deploy commit; no design surface beyond filename references). |
| **R15** Out-of-scope items remain untouched | Migration Path §"No re-ingest" + Components (no edits to `mcp_server_node/`, no edits to `mdc-…-mpnet768` indices, no add of `sentence-transformers` / `torch` / `transformers`). |

