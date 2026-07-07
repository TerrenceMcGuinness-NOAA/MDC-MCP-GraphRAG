# Design Document

## Overview

This feature adds a `GeminiProvider` to the embedding abstraction so
`gemini-embedding-001` can be evaluated head-to-head against `titan1024`
(Bedrock) and `mpnet768` (local). It is a small, additive change: one new
provider class (duplicated in the Node.js and Python copies), one new
registry profile, and one new `create_provider` dispatch arm. The
ingestion loop, the storage backends, the collection namer, and the
benchmark harness are untouched — they already route through the provider
abstraction.

The provider talks to the Google Generative Language `embedContent` REST
endpoint using only `urllib` from the standard library, so **no new
dependency** is added to the ingest box or the AgentCore image. It mirrors
the `BedrockProvider` retry/backoff contract (4 attempts, 1s/2s/4s), and
L2-normalizes sub-3072-dim vectors so cosine/k-NN comparisons against the
already-normalized Titan vectors are apples-to-apples.

What changes:

- **Modified** `mcp_server_node/scripts/embedding_registry.py` and
  `mcp_server_python/src/data/embedding_registry.py` — register the
  `gemini768` profile (`provider="gemini"`).
- **Modified** `mcp_server_node/scripts/embedding_provider.py` and
  `mcp_server_python/src/data/embedding_provider.py` — add
  `GeminiProvider` and a `create_provider` dispatch arm for `"gemini"`.
  The Node copy also implements the ABC's abstract `embed_image`
  (raises `NotImplementedError`).
- **New** `mcp_server_node/tests/…` / `mcp_server_python/tests/unit/…`
  — mocked-HTTP unit tests plus a key-gated integration smoke test.
- **No change** to `ingestion_base.py`, `aws_backend.py`,
  `collection_namer.py`, `benchmark_runner.py`, `pyproject.toml`, or
  `package.json`.

The deliverable is code that lands and unit-tests green **without** a
live key; the head-to-head ingest + benchmark runs once a
`GEMINI_API_KEY` is provisioned (tracked in the sister SDD workflow).

## Architecture

Adding a provider is a single new leaf under the existing factory. The
ingestion call site (`ingestion_base.py::run()` → `provider.embed`) and
the storage routing (`--backend aws|cots`) are unchanged.

```
        ingest_*_v8.py  →  BaseIngester.run()
                              │  self.provider.embed([chunk.text])[0]
                              ▼
                 ┌─────────────────────────────┐
                 │   EmbeddingProvider (ABC)   │
                 │   .embed(texts) -> vectors  │
                 │   .dimensions: int          │
                 └───┬───────────┬──────────┬──┘
                     │           │          │
              create_provider(profile)  ← dispatch on profile.provider
                     │           │          │
        "bedrock"    │  "local"  │  "gemini"│  ◄── NEW
                     ▼           ▼          ▼
             ┌──────────┐ ┌──────────┐ ┌──────────────┐
             │ Bedrock  │ │ Local    │ │ Gemini       │  ◄── NEW
             │ Provider │ │ Provider │ │ Provider     │
             │ (boto3)  │ │ (s-t)    │ │ (urllib REST)│
             └────┬─────┘ └────┬─────┘ └──────┬───────┘
                  ▼            ▼              ▼
            Bedrock Runtime  local model   generativelanguage
            (Titan/Nova)     (mpnet)        .googleapis.com
                                            :embedContent
                     ▲
                     │ ModelProfile resolved by --model
        ┌────────────┴───────────────────────────────┐
        │ EmbeddingModelRegistry                      │
        │  mpnet768 (local) · titan1024 (bedrock)     │
        │  nova256/512/1024/3072 (bedrock)            │
        │  gemini768 (gemini)   ◄── NEW               │
        │  default = titan1024 (unchanged)            │
        └─────────────────────────────────────────────┘
```

## Components and Interfaces

### MODIFIED · `embedding_registry.py` (both copies)

- **Purpose.** Add the `gemini768` descriptor so `--model gemini768`
  resolves to the Gemini provider.
- **Change.** Append one `ModelProfile` to `_register_builtins`:
  ```python
  ModelProfile(
      short_name="gemini768",
      provider="gemini",
      model_id="gemini-embedding-001",
      dimensions=768,
      provider_params={
          "task_type": "RETRIEVAL_DOCUMENT",
          "output_dimensionality": 768,
          "normalize": True,
      },
  )
  ```
- **Constraint.** Default profile stays `titan1024` (Req 1.5). Field
  values identical in both copies (Req 1.4).

### MODIFIED · `embedding_provider.py` (both copies)

- **Purpose.** Add the `GeminiProvider` concrete class and the
  `create_provider` dispatch arm.
- **Public surface.**
  - `GeminiProvider(EmbeddingProvider)` — `embed(texts)`, `dimensions`.
    (Node copy also: `embed_image(image_bytes)` → `NotImplementedError`.)
  - `create_provider` gains `if profile.provider == "gemini": return GeminiProvider(profile)`.
- **Key implementation notes.**
  - `__init__` reads `GEMINI_API_KEY` (fallback `GOOGLE_API_KEY`), raises
    `EmbeddingError` if neither is set (Req 6). Reads `task_type`,
    `output_dimensionality`, `normalize` from `provider_params`;
    `normalize` defaults to `output_dimensionality != 3072` (Req 4.3).
  - `embed(texts)` maps `_embed_one` over `texts` (ingestion always
    passes a single-element list, so batch size is 1 in practice).
  - `_embed_one(text)`:
    - Builds body `{"content": {"parts": [{"text": text}]},
      "taskType": <task_type>, "outputDimensionality": <out_dim>}`.
    - POSTs to `.../models/{model_id}:embedContent` with headers
      `Content-Type: application/json` and `x-goog-api-key: <key>`
      (Req 3.1–3.3).
    - Parses `data["embedding"]["values"]`; L2-normalizes when
      `normalize` (Req 4.1–4.2); asserts length == `dimensions`
      else raises `EmbeddingError` (Req 5.5).
    - 4-attempt retry loop: retry on HTTP 429/500/502/503/504 with
      sleeps 1s/2s/4s; non-retryable 4xx and dimension mismatch raise
      immediately (Req 5).
  - Stdlib only: `urllib.request`, `urllib.error`, `json`, `math`,
    `time`, `os` (Req 3.5).
- **Constraint.** No edits to `BedrockProvider` / `LocalProvider`
  (Req 11.1); no new imports of SDK/`requests` (Req 11.4).

### NEW · tests

- **Node.js** (`mcp_server_node/`): mocked-HTTP unit tests + a
  `GEMINI_API_KEY`-gated integration test, following the existing
  provider test layout.
- **Python** (`mcp_server_python/tests/unit/test_gemini_provider.py`
  + `tests/integration/test_gemini_embedding.py`): request-shape,
  retry-schedule, normalization, no-key, dimension-mismatch, and the
  gated real-call test (Req 8).

## Data Models

```python
# embedding_provider.py  (Python copy shown; Node copy mirrors it,
# plus an embed_image stub for the Node ABC)

class GeminiProvider(EmbeddingProvider):
    _MAX_RETRIES: int = 3
    _BACKOFF_S: tuple[float, float, float] = (1.0, 2.0, 4.0)
    _RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    _ENDPOINT: str = (
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
    )

    _profile: ModelProfile
    _key: str            # from GEMINI_API_KEY | GOOGLE_API_KEY
    _url: str
    _task_type: str      # provider_params.task_type
    _out_dim: int        # provider_params.output_dimensionality
    _normalize: bool     # provider_params.normalize (default: out_dim != 3072)

    def __init__(self, profile: ModelProfile) -> None: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimensions(self) -> int: ...
    def _embed_one(self, text: str) -> list[float]: ...
    @staticmethod
    def _l2_normalize(vec: list[float]) -> list[float]: ...
```

## Sequence Diagrams

### Successful embed (`gemini768`, document side)

```
BaseIngester.run     GeminiProvider          generativelanguage.googleapis.com
      │                    │                              │
      │ embed([chunk])     │                              │
      ├───────────────────►│ _embed_one(text)             │
      │                    │ POST :embedContent           │
      │                    │  hdr x-goog-api-key          │
      │                    │  body {content, taskType,    │
      │                    │        outputDimensionality} │
      │                    ├─────────────────────────────►│
      │                    │  {"embedding":{"values":[…]}}│
      │                    │◄─────────────────────────────┤
      │                    │ L2-normalize (out_dim<3072)  │
      │                    │ assert len == 768            │
      │  vector[768]       │                              │
      │◄───────────────────┤                              │
      │ upsert_document(…, embedding=vector, …)           │
```

### No key present (inert)

```
create_provider(gemini768)  →  GeminiProvider.__init__
      reads GEMINI_API_KEY / GOOGLE_API_KEY → both unset
      raises EmbeddingError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set …")
      (module import itself never reads the key — Req 6.3)
```

## Error Handling

| Condition | Source | Retry | Final raised type |
|---|---|---|---|
| HTTP 429 / 500 / 502 / 503 / 504 | `urlopen` | up to 3 (1s/2s/4s) | after exhaustion: `EmbeddingError(model_id + last error)` (Req 5.1–5.3) |
| HTTP 4xx ≠ 429 | `urlopen` | none | `EmbeddingError` on first attempt (Req 5.4) |
| Response vector length ≠ `dimensions` | `_embed_one` | none | `EmbeddingError` (Req 5.5) |
| Neither key env var set | `__init__` | none | `EmbeddingError` naming both vars (Req 6.2) |
| `embed_image` called (Node) | Node `GeminiProvider` | none | `NotImplementedError` (Req 7.2) |

Retry sleeps are wall-clock `time.sleep` inside the provider (the Node
ingestion pipeline calls `embed` synchronously; the Python runtime would
call it via `asyncio.to_thread` if ever wired to the query path — out of
scope here).

## Execution / Evaluation Plan

This is a code-plus-evaluation feature. The code lands and unit-tests
green without a key. The evaluation runs once `GEMINI_API_KEY` is
provisioned (prerequisites — key surface, paid tier, egress allowlist for
`generativelanguage.googleapis.com:443` — are tracked in the wiki page
and the SDD workflow, not in code).

1. **Land code + unit tests** (no key needed).
2. **Provision key** (external; blocks steps 3–4).
3. **Ingest**:
   ```bash
   export GEMINI_API_KEY=…
   python3.12 mcp_server_node/scripts/ingest_documentation_v8.py \
       --model gemini768 --backend aws --delay 0.2
   ```
   Produces a `gemini768`-suffixed collection via `CollectionNamer`
   (Req 9.1).
4. **Benchmark**: run `benchmark_runner.py` for `gemini768` vs the
   `titan1024` baseline on the same query set; record P@5 / MRR
   side-by-side in the phase report (Req 9.2, 9.3).

## Testing Strategy

Mock-based unit tests (patch `urllib.request.urlopen`) plus one
key-gated integration call. Property-based testing is not applicable:
the embedding step is a side-effect call to an external service, the
body/response shape is a fixed contract, the retry schedule is a
specific timing contract, and normalization is a simple numeric
transform — all better covered by targeted mocked unit tests. This
mirrors the `bedrock-native-embedding-swap` testing rationale.
