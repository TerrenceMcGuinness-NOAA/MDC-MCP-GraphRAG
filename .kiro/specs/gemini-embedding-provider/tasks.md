# Implementation Plan: Gemini Embedding 2 Multimodal Provider (Phase 66)

## Overview

Add Google's **`gemini-embedding-2`** (natively multimodal) as a new
`EmbeddingProvider` and evaluate it head-to-head against `titan1024` (Bedrock)
and `mpnet768` (local). The provider calls the Google Generative Language
`embedContent` REST endpoint via stdlib `urllib` (zero new dependencies), does
**no** client-side normalization (the model auto-normalizes), uses text-prefix
task instructions (doc vs query), and supports **text and image** embedding.
Changes are additive and duplicated field-for-field across the Node.js
(`mcp_server_node/scripts/`) and Python (`mcp_server_python/src/data/`) copies.
The text ingestion loop is unchanged; image ingestion is a new additive
`--images` route. `gemini-embedding-001` is out of scope.

The code lands and unit-tests green **without** a live key; the comparison
ingest + benchmark runs once `GEMINI_API_KEY` is provisioned (external
prerequisite tracked in the sister SDD workflow, gated at the Task 4.2
checkpoint).

## Tasks

- [ ] 1. Register the `gemini-embedding-2` multimodal profiles
  - [ ] 1.1 Add `gemini2_3072` and `gemini2_768` to both registries
    - Append both to `_register_builtins` in `mcp_server_node/scripts/embedding_registry.py` AND `mcp_server_python/src/data/embedding_registry.py`, identical fields: `provider="gemini"`, `model_id="gemini-embedding-2"`, `supports_multimodal=True`, `supports_matryoshka=True`, `provider_params={output_dimensionality:<3072|768>}`
    - Leave the default profile `titan1024`; register no `gemini-embedding-001` profile
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

  - [ ]* 1.2 Unit test the profile lookups
    - Assert `get_profile("gemini2_3072"/"gemini2_768")` return the expected multimodal fields; assert the default is still `titan1024`
    - _Requirements: 1.4, 1.5_

- [ ] 2. Implement `GeminiProvider` (text + image)
  - [ ] 2.1 Scaffold provider + factory dispatch (Python copy)
    - In `mcp_server_python/src/data/embedding_provider.py`: `__init__` reads `GEMINI_API_KEY`/`GOOGLE_API_KEY` (raise `EmbeddingError` if neither; never at import), reads `output_dimensionality` / `doc_instruction` / `query_instruction` from `provider_params`; add the `dimensions` property; add `"GeminiProvider"` to `__all__`; add `create_provider` arm `provider == "gemini"`
    - _Requirements: 2.1, 2.2, 8.1, 8.2, 8.3, 3.6_

  - [ ] 2.2 Implement `_post` (retry) and `_embed_part` (parse, no-normalize, assert)
    - `_post(body)`: 4-attempt loop, `time.sleep` 1s/2s/4s, retry on HTTP 429/500/502/503/504, `x-goog-api-key` header, stdlib `urllib`; non-retryable 4xx raises immediately
    - `_embed_part(part)`: build `{"content":{"parts":[part]}, "output_dimensionality":out_dim}`, POST, parse `embedding.values`, assert length == `dimensions` (else `EmbeddingError`), return the vector **as-is** (no L2)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.2, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ] 2.3 Implement `embed(texts, is_query=False)` with doc/query instructions
    - Select `doc_instruction` (default) or `query_instruction` (`is_query=True`), format each text, call `_embed_part({"text": ...})`; do NOT send `taskType`
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ] 2.4 Implement `embed_image(image_bytes, mime_type)`
    - Validate `mime_type ∈ {image/png, image/jpeg}` (else `EmbeddingError`), base64-encode, call `_embed_part({"inline_data": {"mime_type":…, "data":…}})`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ] 2.5 Mirror `GeminiProvider` + dispatch into the Node.js copy
    - Same class in `mcp_server_node/scripts/embedding_provider.py`; `embed_image` implements the Node ABC's abstract method (no `NotImplementedError`); add the `create_provider` `"gemini"` arm; keep both copies in sync field-for-field
    - _Requirements: 2.2, 9.1, 9.2, 9.3_

  - [ ]* 2.6 Unit tests for the provider (Python)
    - Patch `urllib.request.urlopen`; assert: text body has task-formatted `content.parts[0].text` + `output_dimensionality` and the `x-goog-api-key` header; image body has an `inline_data` base64 part; non-PNG/JPEG mime raises; retry follows [1,2,4] on 429/5xx and no-retry on a 4xx; vectors returned as-is (no normalization); dimension mismatch raises; `embed` uses doc instruction by default and query instruction when `is_query=True`; construction without a key raises `EmbeddingError`
    - File: `mcp_server_python/tests/unit/test_gemini_provider.py`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

- [ ] 3. Image-ingestion route (`*.png` on the CLI)
  - [ ] 3.1 Add the additive `--images` media route
    - Add an `--images <path-or-glob>` flag to a multimodal-capable ingester; leave the text `run()` path unchanged (additive)
    - _Requirements: 10.1, 10.6_

  - [ ] 3.2 Route image files → `embed_image` → upsert
    - For each matched file with a multimodal profile active: read bytes, infer mime from extension, call `provider.embed_image(bytes, mime)`, `upsert_document` with the file path as source id + `modality="image"` metadata into the `gemini2_*` collection; enforce ≤6 images/request and PNG/JPEG-only; fail clearly (naming `gemini2_3072`) if the active profile is not multimodal
    - _Requirements: 10.2, 10.3, 10.4, 10.5_

  - [ ]* 3.3 Unit test the routing with a mocked provider
    - Assert image files route to `embed_image`, metadata carries `modality="image"`, non-multimodal profile errors clearly, and >6-per-request is batched/limited
    - _Requirements: 10.2, 10.3, 10.4_

- [ ] 4. Pre-provision validation
  - [ ] 4.1 Run the unit suite without a key
    - Confirm the new unit tests pass and existing provider/registry tests remain green with no `GEMINI_API_KEY` set (proves inert-without-key)
    - _Requirements: 8.3, 11.1–11.6_

  - [ ] 4.2 Checkpoint — code landed + unit-green; pause for key provisioning
    - The comparison ingest/benchmark (Task 5) is blocked on the external `GEMINI_API_KEY`; confirm with the user before proceeding once the key is available

- [ ] 5. Comparison ingest + benchmark (requires provisioned key)
  - [ ] 5.1 Ingest the text corpus
    - `export GEMINI_API_KEY=…; ingest_documentation_v8.py --model gemini2_3072 --backend aws --delay <sized-to-RPM>`; confirm a `gemini2_3072`-suffixed collection is created via `CollectionNamer` with no `run()` change
    - _Requirements: 12.1_
    - _Tag: ingest_

  - [ ] 5.2 Ingest images via the media route
    - Same ingester with `--images "<glob>/*.png"`; confirm image vectors (`modality="image"`) land in the same collection
    - _Requirements: 12.2_
    - _Tag: ingest_

  - [ ] 5.3 Benchmark + cross-modal smoke
    - `benchmark_runner.py` for `gemini2_3072` vs `titan1024` (and `mpnet768`) — P@5 / MRR on the same query set; plus a text-query→image-hit check
    - _Requirements: 12.3, 12.4_
    - _Tag: validate_

- [ ] 6. Documentation
  - [ ] 6.1 Add the CHANGELOG entry
    - Dated entry: `gemini-embedding-2` provider addition, files touched (both registry + provider copies, ingester route, tests), unit-test-count delta
    - _Requirements: 13.1_

  - [ ] 6.2 Write the phase report
    - `docs/reports/<date>-phase66-gemini-embedding-2-provider.md`: implementation summary, unit results, and (post-key) P@5 / MRR side-by-side + cross-modal result; cross-reference the wiki page and the SDD workflow
    - _Requirements: 13.2, 12.4_

- [ ] 7. Final checkpoint and commit
  - [ ] 7.1 Checkpoint — unit-green (and, if key available, benchmark captured)
    - Confirm Task 4.1 green and Tasks 6.1 / 6.2 written; ask the user before committing
  - [ ] 7.2 Single commit (no push)
    - Stage the two registry edits, the two provider edits, the ingester media route, the unit + integration tests, the phase report, and the CHANGELOG entry; commit referencing Phase 66; do not push (operator handles the batch push)
    - _Requirements: 13.1_

## Notes

- Sub-tasks marked `*` are test-only and can be skipped to ship faster; core
  implementation, evaluation, and documentation sub-tasks are unmarked.
- Tasks 1–4 need no live key. Task 5 is blocked on the external `GEMINI_API_KEY`
  (surface choice, paid tier, egress) — tracked in the wiki page and SDD
  workflow, gated behind the Task 4.2 checkpoint.
- The provider is stdlib-only; do NOT add `google-genai`,
  `google-generativeai`, or `requests` to `pyproject.toml` / `package.json`.
- Keep the two `embedding_provider.py` / `embedding_registry.py` copies in sync
  field-for-field (Node ingestion vs Python runtime).
- `gemini-embedding-2` auto-normalizes — the provider must NOT re-normalize.
- Audio / video / PDF are out of scope for this phase (same `inline_data`
  mechanism; natural follow-ons).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4"] },
    { "id": 4, "tasks": ["2.5", "3.1"] },
    { "id": 5, "tasks": ["2.6", "3.2"] },
    { "id": 6, "tasks": ["3.3", "4.1"] },
    { "id": 7, "tasks": ["4.2"] },
    { "id": 8, "tasks": ["5.1"] },
    { "id": 9, "tasks": ["5.2"] },
    { "id": 10, "tasks": ["5.3"] },
    { "id": 11, "tasks": ["6.1", "6.2"] },
    { "id": 12, "tasks": ["7.2"] }
  ]
}
```
