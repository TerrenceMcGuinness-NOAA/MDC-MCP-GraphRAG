# Phase 66 — Gemini Embedding Provider Evaluation (`gemini-embedding-001`)

**Version**: 1.0.0
**Created**: 2026-07-07
**Status**: planned (code implementable now; comparison blocked on API key)
**Estimated effort**: ~0.5 day to land code + unit tests; +1–2 hrs ingest/benchmark once the key lands
**Depends on**: `bedrock-native-embedding-swap` (Phase C-2c — provider abstraction + registry pattern); the ingestion provider abstraction in `mcp_server_node/scripts/embedding_provider.py`
**Kiro spec**: `.kiro/specs/gemini-embedding-provider/`
**Wiki**: `Gemini-Embedding-Provider-Evaluation-and-Key-Request`
**Owner**: Terry McGuinness (OMD CAT)

---

## 1. Executive Summary

We want to evaluate Google's **`gemini-embedding-001`** (current MTEB
retrieval leader; configurable 768/1536/3072 dims, ~2048-token input) as
a candidate "better sentence transformer" for the MDC MCP-RAG knowledge
base, measured head-to-head against the two providers we run today:
**`titan1024`** (Amazon Bedrock Titan Embed Text V2, the AWS-native
default) and **`mpnet768`** (local `all-mpnet-base-v2`, the COTS
baseline).

The embedding layer already exposes a clean `ModelProfile` registry +
`EmbeddingProvider` ABC + `create_provider` factory, duplicated in the
Node.js ingestion scripts and the Python runtime. Ingestion funnels
through one backend-agnostic call site
(`ingestion_base.py::run()` → `provider.embed`). Adding a provider is
therefore additive: a `gemini768` registry profile, a `create_provider`
dispatch arm, and a `GeminiProvider` class that calls the Google
`embedContent` REST endpoint via **stdlib `urllib`** — zero new
dependencies on the ingest box or the AgentCore image.

The code lands and unit-tests green **without** a live key. The actual
comparison ingest + benchmark is gated on a provisioned `GEMINI_API_KEY`
(surface choice, paid tier, egress allowlist — see the wiki page).

## 2. Scope

### 2.1 In Scope

- `gemini768` `ModelProfile` in BOTH `embedding_registry.py` copies
  (`provider="gemini"`, `model_id="gemini-embedding-001"`,
  `dimensions=768`, `provider_params={task_type:"RETRIEVAL_DOCUMENT",
  output_dimensionality:768, normalize:True}`).
- `GeminiProvider` in BOTH `embedding_provider.py` copies: `urllib` REST
  `embedContent`, `x-goog-api-key` header auth, `BedrockProvider`-style
  4-attempt retry (1s/2s/4s on 429/5xx), L2-normalization for sub-3072
  dims, key from `GEMINI_API_KEY` / `GOOGLE_API_KEY`. Node copy adds an
  `embed_image` → `NotImplementedError` stub for ABC parity.
- `create_provider` dispatch arm for `"gemini"` in both copies.
- Mocked-HTTP unit tests + a key-gated integration smoke test.
- (Post-key) ingest a `gemini768` collection via the unchanged pipeline
  and benchmark P@5 / MRR against the `titan1024` baseline.
- CHANGELOG entry + phase report cross-referencing the wiki + this spec.

### 2.2 Out of Scope

- Any change to `BedrockProvider` / `LocalProvider`.
- Re-ingesting, deleting, or altering the existing `titan1024` /
  `mpnet768` collections.
- Any change to `ingestion_base.py::run()`, the backends, or the
  collection namer.
- Adding a Google SDK or any third-party HTTP library
  (`google-genai`, `requests`, …) — stdlib only.
- Query-side `RETRIEVAL_QUERY` task-type wiring — a documented follow-up
  if the comparison is favorable.
- Committing or hardcoding any API key value.

## 3. Acceptance Criteria

| # | Probe | Pass condition | Tag |
|---|-------|----------------|-----|
| 1 | Registry | `get_profile("gemini768")` returns the profile in both copies; default still `titan1024` | validate |
| 2 | Factory | `create_provider(gemini768)` returns a `GeminiProvider`; `bedrock`/`local` unchanged | validate |
| 3 | Request shape | Mocked HTTP shows body `{content.parts[0].text, taskType, outputDimensionality}` and key in `x-goog-api-key` header (not URL) | validate |
| 4 | Retry | Transient 429/5xx retried on 1s/2s/4s; non-retryable 4xx and dim-mismatch raise `EmbeddingError` without retry | validate |
| 5 | Normalization | sub-3072 vectors L2-normalized to unit length; zero vector returned unchanged | validate |
| 6 | Inert-without-key | Module imports without a key; construction without a key raises `EmbeddingError` naming both env vars | validate |
| 7 | Unit suite green | New + existing provider/registry unit tests pass with NO `GEMINI_API_KEY` set | validate |
| 8 | (Key-gated) Ingest | `ingest_documentation_v8.py --model gemini768` produces a `gemini768`-suffixed collection, no `run()` change | ingest |
| 9 | (Key-gated) Benchmark | `benchmark_runner.py` records P@5 / MRR for `gemini768` vs `titan1024` on the same query set | validate |

## 4. Implementation Plan

### Step 1: Register the `gemini768` profile
**Tag**: implement
**Target**: `mcp_server_node/scripts/embedding_registry.py`, `mcp_server_python/src/data/embedding_registry.py`

Append the `gemini768` `ModelProfile` to `_register_builtins` in both
copies, identical fields. Leave the default as `titan1024`.

### Step 2: Implement `GeminiProvider` (Python) + retry
**Tag**: implement
**Target**: `mcp_server_python/src/data/embedding_provider.py`

`urllib` REST `embedContent`; header auth; parse `embedding.values`;
L2-normalize sub-3072; 4-attempt retry (1s/2s/4s on 429/5xx); key from
`GEMINI_API_KEY`/`GOOGLE_API_KEY`; dimension assertion. Add to `__all__`.

### Step 3: Mirror into the Node copy + factory dispatch
**Tag**: implement
**Target**: `mcp_server_node/scripts/embedding_provider.py`

Same class plus `embed_image` → `NotImplementedError` (Node ABC). Add
the `create_provider` `"gemini"` arm in both copies.

### Step 4: Unit tests
**Tag**: validate
**Target**: `mcp_server_python/tests/unit/test_gemini_provider.py`

Mock `urllib.request.urlopen`; cover request shape + key header, retry
schedule, normalization, no-key, dimension mismatch. Confirm green with
no key set.

### Step 5: Integration smoke test (key-gated)
**Tag**: validate
**Target**: `mcp_server_python/tests/integration/test_gemini_embedding.py`

Skip unless `GEMINI_API_KEY` set; one real `embed(["hello world"])`,
assert length 768 + unit norm.

### Step 6: Checkpoint — pause for key provisioning
**Tag**: validate

Code landed + unit-green. The comparison (Steps 7–8) is blocked on the
external `GEMINI_API_KEY`. Confirm with the user before proceeding.

### Step 7: Comparison ingest
**Tag**: ingest
**Target**: `gemini768` OpenSearch collection

`export GEMINI_API_KEY=…; ingest_documentation_v8.py --model gemini768
--backend aws --delay <sized-to-RPM>`. Produces the `gemini768`
collection via `CollectionNamer`.

### Step 8: Benchmark + report
**Tag**: document
**Target**: `docs/reports/<date>-phase66-gemini-embedding-provider.md`, `CHANGELOG.md`

Run `benchmark_runner.py` for `gemini768` vs `titan1024`; record P@5 /
MRR side-by-side; write the phase report + CHANGELOG entry; cross-ref
the wiki page and the Kiro spec.

## 5. Design & Architecture

### 5.1 Why additive, and why stdlib `urllib`
The provider abstraction already dispatches on `profile.provider`;
Gemini is a new leaf next to `bedrock`/`local`. Using stdlib `urllib`
instead of the `google-genai` SDK avoids adding a dependency to the
ingest box and the AgentCore image — a real constraint in a locked-down
environment. The SDK path is a documented alternative if batching or
auth features are later needed.

### 5.2 Why L2-normalize sub-3072 vectors
`gemini-embedding-001` returns un-normalized vectors for any
`output_dimensionality` other than 3072. Titan v2 vectors are already
normalized, and OpenSearch k-NN cosine comparisons assume comparable
magnitude, so normalizing the 768-dim Gemini output keeps the head-to-head
fair.

### 5.3 Why inert-without-key
Reading the key only at construction (never at import) lets the code
merge and unit-test before the NOAA/Google key is provisioned, decoupling
the code change from the external procurement step.

### 5.4 Doc vs query task type
Ingestion uses `RETRIEVAL_DOCUMENT`. Correct retrieval also wants
`RETRIEVAL_QUERY` on the query side, but the query path is not wired in
this phase — kept as a follow-up so the first comparison is a clean,
minimal change.

## 6. Artifacts Produced

| Artifact | Path | Purpose |
|---|---|---|
| Registry edit (×2) | `*/embedding_registry.py` | `gemini768` profile |
| Provider + factory (×2) | `*/embedding_provider.py` | `GeminiProvider` + `"gemini"` dispatch |
| Unit tests | `mcp_server_python/tests/unit/test_gemini_provider.py` | request/retry/normalize/no-key/mismatch |
| Integration test | `mcp_server_python/tests/integration/test_gemini_embedding.py` | key-gated real call |
| Phase report | `docs/reports/<date>-phase66-gemini-embedding-provider.md` | results + P@5/MRR |
| CHANGELOG entry | `CHANGELOG.md` | records the provider addition |
| Kiro spec | `.kiro/specs/gemini-embedding-provider/` | requirements/design/tasks |

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Key not yet provisioned | Code is inert-without-key; Steps 1–5 land + unit-test with no key. Step 6 checkpoint gates the ingest. |
| Free-tier rate limits throttle a full ingest | Request paid tier (wiki); size `--delay` to the granted RPM; retry loop absorbs 429s. |
| Egress blocked to `generativelanguage.googleapis.com` | Confirm outbound allowlist (wiki key-request checklist) before Step 7. |
| Chunks exceed the ~2048-token input cap | MPNet-sized chunks are safe; verify chunk sizes before the full run. |
| Unfair comparison from un-normalized vectors | L2-normalize sub-3072 output (Step 2 / AC 5). |
| Two provider copies drift | Keep Node + Python `embedding_provider`/`embedding_registry` in sync field-for-field (spec constraint). |
| Data-egress governance (public corpus to Google) | Corpus is public GW code/docs; still route through data-handling sign-off; paid/Vertex avoids training-data use (wiki compliance notes). |

## 8. SDD Session Note

The hosted AgentCore Python runtime does **not** bind-mount
`sdd_framework/workflows/`, so `list_sdd_workflows` / `get_sdd_workflow`
over `agentcore-mcp-rag` cannot enumerate this file. The session-tracking
tools (`start_sdd_session`, `record_sdd_step`, `get_sdd_session`,
`complete_sdd_session`, `validate_sdd_compliance`) operate on runtime
session state independently and were used to validate this phase's
authoring. This file remains the on-disk source of truth for the
COTS/local tooling and the Kiro spec sister.
