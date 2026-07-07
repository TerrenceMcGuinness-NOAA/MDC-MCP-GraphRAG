# Implementation Plan: Gemini Embedding Provider (Phase 66)

## Overview

Add a `GeminiProvider` (`gemini-embedding-001`) to the embedding
abstraction so it can be evaluated head-to-head against `titan1024`
(Bedrock) and `mpnet768` (local). The provider calls the Google
Generative Language `embedContent` REST endpoint via stdlib `urllib`
(zero new dependencies), mirrors the `BedrockProvider` retry contract,
and L2-normalizes sub-3072-dim vectors. Changes are additive and
duplicated field-for-field in the Node.js (`mcp_server_node/scripts/`)
and Python (`mcp_server_python/src/data/`) copies. The ingestion loop,
storage backends, collection namer, and benchmark harness are untouched.

The code lands and unit-tests green **without** a live key; the
comparison ingest + benchmark runs once `GEMINI_API_KEY` is provisioned
(external prerequisite tracked in the sister SDD workflow).

## Tasks

- [ ] 1. Register the `gemini768` profile
  - [ ] 1.1 Add the `gemini768` `ModelProfile` to both registries
    - Append the profile (`provider="gemini"`, `model_id="gemini-embedding-001"`, `dimensions=768`, `provider_params={task_type:"RETRIEVAL_DOCUMENT", output_dimensionality:768, normalize:True}`) to `_register_builtins` in `mcp_server_node/scripts/embedding_registry.py` AND `mcp_server_python/src/data/embedding_registry.py`, identical field values
    - Leave the default profile as `titan1024`
    - _Requirements: 1.1, 1.2, 1.4, 1.5_

  - [ ]* 1.2 Unit test the profile lookup
    - Assert `get_profile("gemini768")` returns the profile with the expected fields; assert the default is still `titan1024`
    - _Requirements: 1.3, 1.5_

- [ ] 2. Add the `GeminiProvider` class + factory dispatch
  - [ ] 2.1 Implement `GeminiProvider` in the Python copy
    - Add `GeminiProvider(EmbeddingProvider)` to `mcp_server_python/src/data/embedding_provider.py`: `__init__` reads `GEMINI_API_KEY` / `GOOGLE_API_KEY` (raise `EmbeddingError` if neither set), pulls `task_type` / `output_dimensionality` / `normalize` from `provider_params` (normalize defaults to `out_dim != 3072`); `embed` maps `_embed_one`; `_embed_one` builds the `embedContent` body, POSTs via `urllib.request` with the `x-goog-api-key` header, parses `embedding.values`, normalizes, and asserts length; `dimensions` property; `_l2_normalize` static helper
    - Add `"GeminiProvider"` to `__all__`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 6.1, 6.2, 6.3_

  - [ ] 2.2 Implement the retry/backoff loop
    - 4-attempt loop with `time.sleep` of 1s/2s/4s before attempts 2/3/4; retry on HTTP 429/500/502/503/504; raise `EmbeddingError` (with `model_id` + last error) on exhaustion; do not retry other 4xx or a dimension mismatch
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 2.3 Mirror `GeminiProvider` into the Node.js copy
    - Add the same class to `mcp_server_node/scripts/embedding_provider.py`, plus an `embed_image` implementation that raises `NotImplementedError` (the Node ABC declares it abstract)
    - _Requirements: 3.*, 4.*, 5.*, 6.*, 7.1, 7.2, 7.3_

  - [ ] 2.4 Add the `create_provider` dispatch arm in both copies
    - `if profile.provider == "gemini": return GeminiProvider(profile)` in both `embedding_provider.py` files; leave `"bedrock"` / `"local"` dispatch unchanged
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 2.5 Unit tests: request shape + key header (Python)
    - Patch `urllib.request.urlopen`; assert the POST body has `content.parts[0].text`, `taskType="RETRIEVAL_DOCUMENT"`, `outputDimensionality=768`, and that the request carries the `x-goog-api-key` header (not in URL); assert the returned vector length is 768
    - File: `mcp_server_python/tests/unit/test_gemini_provider.py`
    - _Requirements: 8.1_

  - [ ]* 2.6 Unit tests: retry schedule + normalization + no-key + mismatch
    - With `time.sleep` patched, assert transient 429/5xx retries follow the [1.0, 2.0, 4.0] schedule and a non-retryable 4xx does not retry; assert `_l2_normalize` yields unit-length vectors and returns a zero vector unchanged; assert construction without a key raises `EmbeddingError` naming both env vars; assert a wrong-length response raises `EmbeddingError`
    - _Requirements: 8.2, 8.3, 8.4, 8.5_

- [ ] 3. Integration smoke test (key-gated)
  - [ ]* 3.1 Add `tests/integration/test_gemini_embedding.py`
    - Skip when `GEMINI_API_KEY` is unset; otherwise build the `gemini768` profile, construct a real `GeminiProvider`, run `embed(["hello world"])`, assert the vector has length 768 and unit L2 norm (within tolerance)
    - _Requirements: 8.6_

- [ ] 4. Pre-provision validation
  - [ ] 4.1 Run the unit suite without a key
    - Confirm the new unit tests pass and the existing provider/registry tests remain green with no `GEMINI_API_KEY` in the environment (proves the code is inert-without-key)
    - _Requirements: 6.3, 8.1–8.5_

  - [ ] 4.2 Checkpoint — code landed and unit-green; pause for key provisioning
    - The comparison ingest/benchmark (Task 5) is blocked on the external `GEMINI_API_KEY`. Confirm with the user before proceeding once the key is available.

- [ ] 5. Comparison ingest + benchmark (requires provisioned key)
  - [ ] 5.1 Ingest the `gemini768` collection
    - With `GEMINI_API_KEY` exported, run `ingest_documentation_v8.py --model gemini768 --backend aws --delay <sized-to-RPM>`; confirm a `gemini768`-suffixed collection is created via `CollectionNamer` with no change to `run()`
    - _Requirements: 9.1_
    - _Tag: ingest_

  - [ ] 5.2 Benchmark `gemini768` vs `titan1024`
    - Run `benchmark_runner.py` against the `gemini768` collection and the `titan1024` baseline on the same query set; capture P@5 and MRR for both
    - _Requirements: 9.2, 9.3_
    - _Tag: validate_

- [ ] 6. Documentation
  - [ ] 6.1 Add the CHANGELOG entry
    - Append a dated entry summarizing the Gemini provider addition, files touched (both registry + provider copies, tests), and the unit-test-count delta
    - _Requirements: 10.1_

  - [ ] 6.2 Write the phase report
    - Create `docs/reports/<date>-phase66-gemini-embedding-provider.md`: implementation summary, unit results, and (post-key) the P@5 / MRR side-by-side; cross-reference the wiki page and the SDD workflow
    - _Requirements: 10.2, 9.3_

- [ ] 7. Final checkpoint and commit
  - [ ] 7.1 Checkpoint — unit-green (and, if key available, benchmark captured)
    - Confirm Task 4.1 green and Tasks 6.1 / 6.2 written; ask the user before committing
  - [ ] 7.2 Single commit (no push)
    - Stage the two registry edits, the two provider edits, the unit + integration tests, the phase report, and the CHANGELOG entry; commit referencing Phase 66 / this spec; do not push (operator handles the batch push)
    - _Requirements: 10.1_

## Notes

- Sub-tasks marked `*` are test-only and can be skipped to ship faster;
  core implementation, evaluation, and documentation sub-tasks are
  unmarked.
- Tasks 1–4 need no live key. Task 5 is blocked on the external
  `GEMINI_API_KEY` (surface choice, paid tier, egress) — tracked in the
  wiki page and SDD workflow, gated behind the Task 4.2 checkpoint.
- The provider is stdlib-only; do NOT add `google-genai`,
  `google-generativeai`, or `requests` to `pyproject.toml` / `package.json`.
- Keep the two `embedding_provider.py` / `embedding_registry.py` copies
  in sync field-for-field (Node ingestion vs Python runtime).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4"] },
    { "id": 4, "tasks": ["2.5", "2.6", "3.1"] },
    { "id": 5, "tasks": ["4.1"] },
    { "id": 6, "tasks": ["4.2"] },
    { "id": 7, "tasks": ["5.1"] },
    { "id": 8, "tasks": ["5.2"] },
    { "id": 9, "tasks": ["6.1", "6.2"] },
    { "id": 10, "tasks": ["7.2"] }
  ]
}
```
