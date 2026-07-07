# Design Document

## Overview

This feature adds Google's **`gemini-embedding-2`** — Google's first natively
multimodal embedding model — as a new `EmbeddingProvider`, and evaluates it
head-to-head against the incumbents `titan1024` (Bedrock) and `mpnet768`
(local). It is additive: two registry profiles, one `create_provider` dispatch
arm, a `GeminiProvider` class with **text and image** paths, and a new additive
CLI route for image ingestion. The text ingestion loop, the storage backends,
the collection namer, and the benchmark harness are otherwise untouched.

The provider calls the Google Generative Language `embedContent` REST endpoint
using only `urllib` from the standard library, so **no new dependency** is added
to the ingest box or the AgentCore image. Because `gemini-embedding-2`
auto-normalizes every dimension server-side, the provider does **no** client-side
normalization. Task control uses the model's text-prefix instructions
(document vs query), not the `taskType` enum.

Scope is **only** `gemini-embedding-2`; the older text-only `gemini-embedding-001`
is not implemented (it would add dual normalization and task-control paths for no
benefit). Image is the multimodal target this phase (the `*.png` use case);
audio / video / PDF share the same `inline_data` mechanism and are documented
follow-ons.

What changes:

- **Modified** `mcp_server_node/scripts/embedding_registry.py` and
  `mcp_server_python/src/data/embedding_registry.py` — register `gemini2_3072`
  and `gemini2_768` (`provider="gemini"`, `supports_multimodal=True`).
- **Modified** `mcp_server_node/scripts/embedding_provider.py` and
  `mcp_server_python/src/data/embedding_provider.py` — add `GeminiProvider`
  (text + image) and a `create_provider` dispatch arm for `"gemini"`.
- **Modified** a multimodal-capable ingester — add an additive `--images`
  media route (text `run()` unchanged).
- **New** unit tests (both copies) + a key-gated integration smoke test.
- **No change** to `BedrockProvider` / `LocalProvider`, the text `run()` loop,
  `aws_backend.py`, `collection_namer.py`, `benchmark_runner.py`,
  `pyproject.toml`, or `package.json`.

The code lands and unit-tests green **without** a key; the comparison ingest +
benchmark runs once `GEMINI_API_KEY` is provisioned (prerequisites tracked in
the wiki page and the SDD workflow).

## Architecture

```
   ingest_*_v8.py ──► BaseIngester.run()  ─────────────►  provider.embed([text])
                        (text path, unchanged)                     │
   ingest_*_v8.py ──► Media_Route (--images, NEW) ──►  provider.embed_image(bytes)
                        (image path, additive)                     │
                                                                   ▼
                                             ┌───────────────────────────────┐
                                             │   EmbeddingProvider (ABC)     │
                                             │   .embed(texts, is_query)     │
                                             │   .embed_image(bytes, mime)   │
                                             │   .dimensions                 │
                                             └──┬───────────┬───────────┬────┘
                                       create_provider(profile) → provider.provider
                                          │           │           │
                                   "bedrock"     "local"      "gemini"  ◄── NEW
                                          ▼           ▼           ▼
                                    ┌─────────┐ ┌─────────┐ ┌──────────────────┐
                                    │ Bedrock │ │ Local   │ │ Gemini (urllib)  │  ◄── NEW
                                    │ (boto3) │ │ (s-t)   │ │ text + image     │
                                    └────┬────┘ └────┬────┘ └────────┬─────────┘
                                         ▼           ▼               ▼
                                   Bedrock Rt   local mpnet   generativelanguage
                                                              .googleapis.com
                                                              :embedContent
                                         ▲
                                         │ ModelProfile resolved by --model
                    ┌────────────────────┴───────────────────────────────┐
                    │ EmbeddingModelRegistry                              │
                    │  mpnet768 (local) · titan1024 (bedrock, default)    │
                    │  nova256/512/1024/3072 (bedrock)                    │
                    │  gemini2_3072 · gemini2_768 (gemini, multimodal) ◄──NEW
                    └─────────────────────────────────────────────────────┘
```

## Verified API facts (`gemini-embedding-2`)

Source: Google Gemini API embeddings docs
(https://ai.google.dev/gemini-api/docs/embeddings), verified 2026-07-07.

| Property | Value |
|---|---|
| Model ID | `gemini-embedding-2` (GA) / `gemini-embedding-2-preview` |
| Endpoint | `POST …/v1beta/models/gemini-embedding-2:embedContent` |
| Auth | API key in the `x-goog-api-key` header |
| Modalities | text, image (PNG/JPEG ≤6/req), audio (MP3/WAV ≤180s), video (MP4/MOV ≤120s, ≤32 frames), PDF (≤6 pages) → one unified space |
| Max input | 8,192 tokens |
| Output dims | 128–3072; default 3072; recommended 768/1536/3072 (Matryoshka) |
| Normalization | auto-normalized at every dimension (no client-side L2) |
| Task control | text prefix — docs `title: {t} | text: {c}`, queries `task: search result | query: {q}` |

Request bodies (REST / stdlib `urllib`, snake_case):
```json
// text
{"content": {"parts": [{"text": "title: none | text: <chunk>"}]},
 "output_dimensionality": 3072}
// image
{"content": {"parts": [{"inline_data": {"mime_type": "image/png",
                                         "data": "<base64>"}}]},
 "output_dimensionality": 3072}
```
Response: `{"embedding": {"values": [ ... ]}}` (already unit-normalized).

## Components and Interfaces

### MODIFIED · `embedding_registry.py` (both copies)

Append two profiles to `_register_builtins`:
```python
ModelProfile(short_name="gemini2_3072", provider="gemini",
             model_id="gemini-embedding-2", dimensions=3072,
             supports_multimodal=True, supports_matryoshka=True,
             provider_params={"output_dimensionality": 3072})
ModelProfile(short_name="gemini2_768", provider="gemini",
             model_id="gemini-embedding-2", dimensions=768,
             supports_multimodal=True, supports_matryoshka=True,
             provider_params={"output_dimensionality": 768})
```
Default stays `titan1024` (Req 1.5). No `gemini-embedding-001` profile.

### MODIFIED · `embedding_provider.py` (both copies)

- **`GeminiProvider(EmbeddingProvider)`** — public surface:
  - `embed(texts, is_query=False) -> list[list[float]]` (Req 3, 6)
  - `embed_image(image_bytes, mime_type="image/png") -> list[float]` (Req 4, 9)
  - `dimensions` property (Req 3.6)
- **`create_provider`** gains `if profile.provider == "gemini": return GeminiProvider(profile)` (Req 2).
- **Key implementation notes:**
  - `__init__` reads `GEMINI_API_KEY` / `GOOGLE_API_KEY` (raise `EmbeddingError`
    if neither; never at import) (Req 8); reads `output_dimensionality`,
    `doc_instruction`, `query_instruction` from `provider_params`.
  - `embed(texts, is_query)` selects the doc or query instruction, formats each
    text, and calls a shared `_embed_part({"text": ...})`.
  - `embed_image` validates `mime_type ∈ {image/png, image/jpeg}` (else
    `EmbeddingError`), base64-encodes, and calls `_embed_part({"inline_data": ...})`.
  - `_embed_part(part)` builds `{"content": {"parts": [part]},
    "output_dimensionality": out_dim}`, POSTs via `_post`, parses
    `embedding.values`, asserts length == `dimensions`, returns the vector
    **as-is** (no normalization — Req 5).
  - `_post(body)` is the shared 4-attempt retry loop (1s/2s/4s on 429/5xx;
    non-retryable 4xx and dim-mismatch raise immediately — Req 7), header auth.
  - Stdlib only: `urllib.request`, `urllib.error`, `json`, `base64`, `time`,
    `os` (Req 3.5).
  - Node copy: `embed_image` satisfies the ABC's abstract method (no
    `NotImplementedError` — we are multimodal) (Req 9.1).

### MODIFIED · multimodal ingester (Media_Route)

- Add an `--images <path-or-glob>` CLI flag (Req 10.1). The existing text
  `run()` path is unchanged; this is a parallel additive route.
- For each matched image file with a multimodal profile active: read bytes,
  infer mime from extension (`.png`→`image/png`, `.jpg`/`.jpeg`→`image/jpeg`),
  call `provider.embed_image(bytes, mime)`, and `upsert_document` with the file
  path as source id + `modality="image"` metadata into the `gemini2_*`
  collection (Req 10.2, 10.5). Enforce ≤6 images/request batching and PNG/JPEG
  only (Req 10.4). If the active profile is not multimodal, fail with a clear
  error naming `gemini2_3072` (Req 10.3).

### NEW · tests

- **Python** `mcp_server_python/tests/unit/test_gemini_provider.py` (mocked
  `urllib.request.urlopen`) + `tests/integration/test_gemini_embedding.py`
  (key-gated). **Node** mirror under the existing provider test layout.

## Data Models

```python
class GeminiProvider(EmbeddingProvider):
    _MAX_RETRIES = 3
    _BACKOFF_S = (1.0, 2.0, 4.0)
    _RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
    _IMAGE_MIME = frozenset({"image/png", "image/jpeg"})
    _ENDPOINT = ("https://generativelanguage.googleapis.com"
                 "/v1beta/models/{model}:embedContent")

    _profile: ModelProfile
    _key: str                # GEMINI_API_KEY | GOOGLE_API_KEY
    _url: str
    _out_dim: int            # provider_params.output_dimensionality
    _doc_instruction: str    # default "title: none | text: {text}"
    _query_instruction: str  # default "task: search result | query: {text}"

    def __init__(self, profile: ModelProfile) -> None: ...
    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]: ...
    def embed_image(self, image_bytes: bytes, mime_type: str = "image/png") -> list[float]: ...
    @property
    def dimensions(self) -> int: ...
    def _embed_part(self, part: dict) -> list[float]: ...
    def _post(self, body: dict) -> dict: ...
```

## Sequence Diagrams

### Text document embed (ingestion)
```
BaseIngester.run     GeminiProvider          generativelanguage…:embedContent
      │ embed([chunk])      │                          │
      ├────────────────────►│ _embed_part({text:       │
      │                     │   "title: none | text:…"})│
      │                     │ POST (x-goog-api-key)     │
      │                     ├──────────────────────────►│
      │                     │ {"embedding":{"values"}}  │
      │                     │◄──────────────────────────┤
      │                     │ assert len==dims; return as-is (no norm)
      │  vector             │                          │
      │◄────────────────────┤                          │
      │ upsert_document(…, embedding=vector, …)         │
```

### Image embed (Media_Route)
```
Media_Route          GeminiProvider          generativelanguage…:embedContent
      │ embed_image(bytes,"image/png")        │
      ├────────────────────►│ validate mime; base64     │
      │                     │ _embed_part({inline_data:  │
      │                     │   {mime_type,data}})       │
      │                     ├──────────────────────────►│
      │                     │ {"embedding":{"values"}}  │
      │                     │◄──────────────────────────┤
      │  vector             │                          │
      │◄────────────────────┤                          │
      │ upsert_document(path, vector, {modality:"image"})│
```

### Cross-modal query (runtime / benchmark)
```
query "atmospheric forecast diagram"
   → GeminiProvider.embed([q], is_query=True)   # "task: search result | query: q"
   → k-NN over gemini2_3072 collection (text + image vectors, one space)
   → returns image documents (modality=image) alongside text hits
```

## Error Handling

| Condition | Source | Retry | Final raised type |
|---|---|---|---|
| HTTP 429 / 500 / 502 / 503 / 504 | `_post` | up to 3 (1s/2s/4s) | after exhaustion: `EmbeddingError(last error)` (Req 7.1–7.3) |
| HTTP 4xx ≠ 429 | `_post` | none | `EmbeddingError` on first attempt (Req 7.4) |
| Response vector length ≠ `dimensions` | `_embed_part` | none | `EmbeddingError` (Req 7.5) |
| `mime_type` not PNG/JPEG | `embed_image` | none | `EmbeddingError` (Req 4.3) |
| Neither key env var set | `__init__` | none | `EmbeddingError` naming both vars (Req 8.2) |
| Image inputs on a non-multimodal profile | Media_Route | none | clear error naming `gemini2_3072` (Req 10.3) |

Retry sleeps are wall-clock `time.sleep` inside the provider (the Node ingestion
pipeline calls `embed`/`embed_image` synchronously).

## Execution / Evaluation Plan

Code lands and unit-tests green without a key. The evaluation runs once
`GEMINI_API_KEY` is provisioned (prerequisites — key surface, paid tier, egress
allowlist for `generativelanguage.googleapis.com:443` — tracked in the wiki page
and the SDD workflow).

1. **Land code + unit tests** (no key needed): profiles, `GeminiProvider`
   (text + image), factory dispatch, Media_Route, unit tests.
2. **Provision key** (external; blocks 3–5).
3. **Ingest text**: `ingest_documentation_v8.py --model gemini2_3072 --backend aws`.
4. **Ingest images**: same ingester with `--images "<glob>/*.png"` → image
   vectors with `modality="image"` in the same collection.
5. **Benchmark + cross-modal smoke**: `benchmark_runner.py` for `gemini2_3072`
   vs `titan1024` (and `mpnet768`) — P@5 / MRR; plus a text-query→image-hit
   check. Record in the phase report.

## Testing Strategy

Mock-based unit tests (patch `urllib.request.urlopen`) cover request/response
shape (text and image), the `x-goog-api-key` header, the retry schedule,
no-client-normalization, dimension mismatch, doc-vs-query instruction selection,
mime validation, and the no-key error. One `GEMINI_API_KEY`-gated integration
test issues a real text embed and a real image embed. Property-based testing is
not applicable — the embedding step is a side-effect call to an external
service, the body/response shape is a fixed contract, and the retry schedule is
a timing contract — all better covered by targeted mocked unit tests (mirrors
the `bedrock-native-embedding-swap` rationale).
