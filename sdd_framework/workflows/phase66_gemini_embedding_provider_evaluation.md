# Phase 66 — Gemini Embedding 2 Multimodal Provider Evaluation

**Version**: 2.0.0
**Created**: 2026-07-07
**Status**: planned (code implementable now; comparison blocked on API key)
**Estimated effort**: ~0.5–1 day to land code + unit tests; +1–2 hrs ingest/benchmark once the key lands
**Depends on**: `bedrock-native-embedding-swap` (the provider abstraction + registry pattern); the ingestion provider abstraction in `mcp_server_node/scripts/embedding_provider.py`
**Kiro spec**: `.kiro/specs/gemini-embedding-provider/`
**Wiki**: `Gemini-Embedding-Provider-Evaluation-and-Key-Request`
**Owner**: Terry McGuinness (OMD CAT)

---

## 1. Executive Summary

Add Google's **`gemini-embedding-2`** — Google's first natively **multimodal**
embedding model — as a new embedding provider for the MDC MCP-RAG knowledge
base, and evaluate it head-to-head against the two providers we run today:
**`titan1024`** (Amazon Bedrock Titan Embed Text V2, the AWS-native default) and
**`mpnet768`** (local `all-mpnet-base-v2`, the COTS baseline).

`gemini-embedding-2` maps **text, images (PNG/JPEG), audio, video, and PDF into
one unified vector space**, unlocking a capability neither incumbent has:
embedding image files (`*.png`) from the ingestion CLI and retrieving them with
a text query (cross-modal search). It also brings an 8,192-token context window,
Matryoshka dims (128–3072, default 3072), server-side normalization, and
text-prefix task control.

The embedding layer already exposes a clean `ModelProfile` registry +
`EmbeddingProvider` ABC + `create_provider` factory (duplicated in the Node
ingestion scripts and the Python runtime), and ingestion funnels through one
backend-agnostic call site (`ingestion_base.py::run()` → `provider.embed`).
Adding this provider is additive: `gemini2_3072`/`gemini2_768` registry
profiles, a `create_provider` dispatch arm, a `GeminiProvider` class with **text
and image** paths (stdlib `urllib`; zero new dependencies), and a new additive
`--images` ingestion route.

The code lands and unit-tests green **without** a live key. The comparison
ingest + benchmark is gated on a provisioned `GEMINI_API_KEY` (surface choice,
paid tier, egress allowlist — see the wiki page).

> **Scope decision (v2.0.0):** centered exclusively on `gemini-embedding-2`. The
> earlier text-only `gemini-embedding-001` is dropped — v2 supersedes it
> (multimodal, longer context, server-side normalization), so carrying both
> added dual code paths for no benefit.

## 2. Scope

### 2.1 In Scope

- `gemini2_3072` / `gemini2_768` multimodal `ModelProfile`s in BOTH
  `embedding_registry.py` copies (`provider="gemini"`,
  `model_id="gemini-embedding-2"`, `supports_multimodal=True`).
- `GeminiProvider` in BOTH `embedding_provider.py` copies: stdlib `urllib` REST
  `embedContent`; `x-goog-api-key` header auth; text path with doc/query
  task-prefix instructions; image path (`embed_image`, `inline_data` base64,
  PNG/JPEG); 4-attempt 1s/2s/4s retry on 429/5xx; **no** client-side
  normalization (model auto-normalizes). Node copy's `embed_image` satisfies the
  ABC's abstract method.
- `create_provider` dispatch arm for `"gemini"` in both copies.
- Additive `--images` ingestion route into a unified `gemini2_*` collection.
- Mocked-HTTP unit tests + a key-gated integration smoke test.
- (Post-key) ingest text + images and benchmark P@5 / MRR against `titan1024`
  (and `mpnet768`), plus a cross-modal (text→image) smoke.
- CHANGELOG entry + phase report cross-referencing the wiki + Kiro spec.

### 2.2 Out of Scope

- `gemini-embedding-001` (text-only) and any `taskType`-enum task control.
- Client-side L2 normalization (v2 auto-normalizes).
- Audio / video / PDF ingestion (same `inline_data` mechanism; follow-ons).
- Any change to `BedrockProvider` / `LocalProvider`, the text `run()` loop, the
  backends, or the collection namer.
- Re-ingesting/deleting/altering the existing `titan1024` / `mpnet768`
  collections.
- Adding a Google SDK or any third-party HTTP library — stdlib only.
- Committing or hardcoding any API key value.

## 3. Acceptance Criteria

| # | Probe | Pass condition | Tag |
|---|-------|----------------|-----|
| 1 | Profiles | `get_profile("gemini2_3072"/"gemini2_768")` return multimodal profiles in both copies; default still `titan1024` | validate |
| 2 | Factory | `create_provider(gemini2_*)` returns a `GeminiProvider`; `bedrock`/`local` unchanged | validate |
| 3 | Text request | Mocked HTTP shows task-formatted `content.parts[0].text` + `output_dimensionality`; key in `x-goog-api-key` header (not URL) | validate |
| 4 | Image request | `embed_image` posts an `inline_data` base64 part (PNG/JPEG); non-PNG/JPEG mime raises `EmbeddingError` | validate |
| 5 | No double-normalize | Vectors returned as-is (no client-side L2) | validate |
| 6 | Doc vs query | `embed` uses the doc instruction by default, the query instruction when `is_query=True`; no `taskType` sent | validate |
| 7 | Retry | Transient 429/5xx retried 1s/2s/4s; non-retryable 4xx and dim-mismatch raise without retry | validate |
| 8 | Inert-without-key | Module imports without a key; construction without a key raises `EmbeddingError` naming both env vars | validate |
| 9 | Unit suite green | New + existing provider/registry unit tests pass with NO `GEMINI_API_KEY` set | validate |
| 10 | (Key-gated) Text ingest | `--model gemini2_3072` produces a `gemini2_3072`-suffixed collection, no `run()` change | ingest |
| 11 | (Key-gated) Image ingest | `--images "<glob>/*.png"` routes to `embed_image` and upserts `modality="image"` into the same collection | ingest |
| 12 | (Key-gated) Benchmark + cross-modal | P@5 / MRR for `gemini2_3072` vs `titan1024`; a text query retrieves an image document | validate |

## 4. Implementation Plan

### Step 1: Register the `gemini2_*` profiles
**Tag**: implement
**Target**: `mcp_server_node/scripts/embedding_registry.py`, `mcp_server_python/src/data/embedding_registry.py`

Append `gemini2_3072` / `gemini2_768` to `_register_builtins` in both copies,
identical fields. Default stays `titan1024`; no `gemini-embedding-001` profile.

### Step 2: Implement `GeminiProvider` (Python) — text + image
**Tag**: implement
**Target**: `mcp_server_python/src/data/embedding_provider.py`

`_post` retry loop + `_embed_part` (parse `embedding.values`, assert dims, no
normalization); `embed(texts, is_query)` with doc/query instructions;
`embed_image` (mime validate + `inline_data` base64); key from
`GEMINI_API_KEY`/`GOOGLE_API_KEY`; add to `__all__`; `create_provider` arm.

### Step 3: Mirror into the Node copy
**Tag**: implement
**Target**: `mcp_server_node/scripts/embedding_provider.py`

Same class; `embed_image` satisfies the Node ABC's abstract method; add the
`create_provider` `"gemini"` arm; keep both copies in sync.

### Step 4: Unit tests
**Tag**: validate
**Target**: `mcp_server_python/tests/unit/test_gemini_provider.py`

Mock `urllib.request.urlopen`; cover text/image request shape + key header,
retry schedule, no-normalize, dim mismatch, doc/query selection, mime
validation, no-key. Confirm green with no key set.

### Step 5: Image-ingestion route
**Tag**: implement
**Target**: a multimodal-capable ingester

Add an additive `--images <path-or-glob>` flag; route image files →
`embed_image` → `upsert_document` with `modality="image"` metadata into the
`gemini2_*` collection; enforce ≤6 images/request + PNG/JPEG; text `run()`
unchanged.

### Step 6: Checkpoint — pause for key provisioning
**Tag**: validate

Code landed + unit-green. The comparison (Steps 7–9) is blocked on the external
`GEMINI_API_KEY`. Confirm with the user before proceeding.

### Step 7: Ingest text + images (key-gated)
**Tag**: ingest
**Target**: `gemini2_3072` OpenSearch collection

`export GEMINI_API_KEY=…; ingest_documentation_v8.py --model gemini2_3072
--backend aws` for text, then `--images "<glob>/*.png"` for images (same
collection).

### Step 8: Benchmark + cross-modal smoke (key-gated)
**Tag**: validate
**Target**: `benchmark_runner.py`

P@5 / MRR for `gemini2_3072` vs `titan1024` (and `mpnet768`); text-query→image-hit check.

### Step 9: Report
**Tag**: document
**Target**: `docs/reports/<date>-phase66-gemini-embedding-2-provider.md`, `CHANGELOG.md`

Phase report + CHANGELOG entry; cross-reference the wiki page and Kiro spec.

## 5. Design & Architecture

### 5.1 Why `gemini-embedding-2` only
v2 is multimodal, has an 8,192-token context, and auto-normalizes at every
dimension. Supporting the older text-only `gemini-embedding-001` alongside it
would require dual normalization (manual for 001) and dual task control
(`taskType` enum for 001 vs text prefix for 2) for no benefit — so 001 is
dropped.

### 5.2 Why stdlib `urllib`
Using `urllib` instead of the `google-genai` SDK avoids adding a dependency to
the ingest box and the AgentCore image — a real constraint in a locked-down
environment. Same rationale as the Bedrock provider (which uses the already
present `boto3`).

### 5.3 No client-side normalization
`gemini-embedding-2` normalizes every dimension server-side (including truncated
768/1536), so the provider returns vectors as-is. Re-normalizing would be a
redundant no-op and misleading.

### 5.4 Asymmetric task instructions
v2 uses text-prefix instructions: documents `title: {t} | text: {c}`, queries
`task: search result | query: {q}`. The provider supports both via
`embed(..., is_query=)`; ingestion embeds documents.

### 5.5 Image ingestion is additive
The text `run()` loop is unchanged. Image ingestion is a parallel `--images`
route that calls `embed_image` and writes `modality="image"` vectors into the
same `gemini2_*` collection, so text and image share one space (cross-modal
retrieval).

## 6. Artifacts Produced

| Artifact | Path | Purpose |
|---|---|---|
| Registry edit (×2) | `*/embedding_registry.py` | `gemini2_3072` / `gemini2_768` profiles |
| Provider + factory (×2) | `*/embedding_provider.py` | `GeminiProvider` (text+image) + `"gemini"` dispatch |
| Ingester media route | a multimodal ingester | `--images` → `embed_image` → upsert |
| Unit tests | `mcp_server_python/tests/unit/test_gemini_provider.py` | request/retry/no-normalize/doc-query/mime/no-key |
| Integration test | `mcp_server_python/tests/integration/test_gemini_embedding.py` | key-gated real text + image call |
| Phase report | `docs/reports/<date>-phase66-gemini-embedding-2-provider.md` | results + P@5/MRR + cross-modal |
| CHANGELOG entry | `CHANGELOG.md` | records the provider addition |
| Kiro spec | `.kiro/specs/gemini-embedding-provider/` | requirements/design/tasks |

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Key not yet provisioned | Code is inert-without-key; Steps 1–5 land + unit-test with no key; Step 6 checkpoint gates the ingest |
| Free-tier rate limits throttle a full ingest | Request paid tier (wiki); size `--delay` to granted RPM; retry loop absorbs 429s |
| Egress blocked to `generativelanguage.googleapis.com` | Confirm outbound allowlist (wiki key-request checklist) before Step 7 |
| Accidentally re-normalizing v2 output | Provider returns values as-is; unit test asserts no client-side L2 (AC 5) |
| Image path exceeds per-request limits | Enforce ≤6 images/request, PNG/JPEG only (AC 4, 11) |
| Media route alters the text `run()` path | Keep the route additive (new flag/method); text `run()` untouched |
| Two provider copies drift | Keep Node + Python `embedding_provider`/`embedding_registry` in sync field-for-field |
| Data-egress governance (public corpus + image bytes to Google) | Public GW code/docs; route through data-handling sign-off; paid/Vertex avoids training-data use (wiki compliance notes) |

## 8. SDD Session Note

The hosted AgentCore Python runtime does **not** bind-mount
`sdd_framework/workflows/`, so `list_sdd_workflows` / `get_sdd_workflow` over
`agentcore-mcp-rag` cannot enumerate this file, and the stateful session
lifecycle (`record_sdd_step` / `get_sdd_session`) does not persist across the
stateless runtime's calls. The session-tracking tools that ARE single-call
(`get_sdd_framework_status`, `validate_sdd_compliance`, `start_sdd_session`)
work. Session continuity requires the filesystem-backed local/COTS Node server.
This file is the on-disk source of truth for the COTS/local tooling and the
Kiro spec sister.
