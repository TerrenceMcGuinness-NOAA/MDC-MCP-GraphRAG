# Implementation Plan: Bedrock-Native Embedding Swap (Phase C-2c)

## Overview

Replace the legacy `sentence-transformers/all-mpnet-base-v2` query-embedding path in the Python MCP server's `OpenSearchAdapter` with a Bedrock Titan Embed Text V2 path against the production `mdc-{domain}-titan1024` indices. Port the Node.js `ModelProfile` / `EmbeddingProvider` / `EmbeddingModelRegistry` abstractions to `mcp_server_python/`, make Bedrock the default, keep `mpnet768` reachable as an intentional parity-debug error path, and ship the new image as `python-titan-v1`. The implementation language is Python throughout. Property-based testing is not applicable for this phase (per the design's Testing Strategy section); the test plan is mock-based unit tests plus one `RUN_INTEGRATION=1`-gated Bedrock smoke test.

All paths below are relative to `mcp_server_python/` unless noted.

## Tasks

- [ ] 1. Embedding model registry
  - [ ] 1.1 Implement `src/data/embedding_registry.py`
    - Define a frozen `ModelProfile` dataclass with `short_name`, `provider`, `model_id`, `dimensions`, `supports_matryoshka`, `supports_multimodal`, `provider_params`
    - Implement `EmbeddingModelRegistry` as a singleton with `_register_builtins` registering all six profiles (`mpnet768`, `titan1024`, `nova256`, `nova512`, `nova1024`, `nova3072`) with `model_id` / `provider` / `dimensions` / `provider_params` values copied verbatim from `mcp_server_node/scripts/embedding_registry.py`
    - Set `titan1024` as `_default`; expose `get_profile`, `get_default`, `list_profiles`, `register`; raise `KeyError` listing all registered names on miss
    - _Requirements: 1.1, 1.2, 1.3, 1.6_

  - [ ]* 1.2 Write unit tests for the registry
    - Cover profile-lookup hits for all six built-ins, miss raises `KeyError` whose message contains every registered short_name, `get_default()` returns the `titan1024` profile, `list_profiles()` returns the six names, and `register()` round-trips a custom profile
    - File: `tests/unit/test_embedding_registry.py`
    - _Requirements: 1.4, 1.5, 11.1_

- [ ] 2. Embedding provider abstraction
  - [ ] 2.1 Scaffold `src/data/embedding_provider.py`
    - Define `EmbeddingError(RuntimeError)`, the `EmbeddingProvider` ABC with abstract `embed(texts) -> list[list[float]]` and `dimensions` property, empty `BedrockProvider` / `LocalProvider` shells, and `create_provider(profile)` dispatching on `profile.provider` (`"bedrock"` → `BedrockProvider`, `"local"` → `LocalProvider`, anything else → `ValueError`)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ] 2.2 Implement `BedrockProvider` request body and response parsing
    - In `__init__`, lazy-import `boto3` and build a single process-scoped `bedrock-runtime` client bound to `os.getenv("AWS_REGION", "us-east-1")`
    - Build the request body per family (Titan: `{"inputText": text, **provider_params}`; Nova: `nova-multimodal-embed-v1` schema with `taskType="SINGLE_EMBEDDING"`, `singleEmbeddingParams.embeddingDimension = profile.dimensions`, `singleEmbeddingParams.text.value = text`)
    - Call `invoke_model` once per input string with `contentType` and `accept` set to `application/json`; parse `embedding` for Titan and `embeddings[0].embedding` for Nova; assert the returned vector length equals `profile.dimensions`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [ ] 2.3 Implement `BedrockProvider` retry/backoff
    - Wrap the `invoke_model` call in a 4-attempt loop with sleeps of 1s, 2s, 4s before attempts 2, 3, 4 using `time.sleep` (sync, called from `asyncio.to_thread` in the adapter)
    - Retry on `ClientError` whose code is in `{ThrottlingException, TooManyRequestsException, ServiceUnavailableException, InternalServerException}` or whose HTTP status is 429 / 500 / 502 / 503 / 504; do not retry any other error
    - On retry exhaustion or non-transient failure, raise `EmbeddingError(f"Bedrock embed failed model={profile.model_id} input_len={len(text)}: {exc}")`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ] 2.4 Implement `LocalProvider` import-fail behavior
    - In `__init__`, attempt `import sentence_transformers`; on `ImportError`, emit one `[ERROR]` log line identifying the active profile (`mpnet768`) and raise `EmbeddingError("sentence-transformers is not installed in the runtime image; mpnet768 is parity-debug-only on this runtime")`
    - Keep an `embed` body present for parity with the Node.js port even though the constructor errors first in this image
    - _Requirements: 9.1, 9.2_

  - [ ]* 2.5 Unit tests for `BedrockProvider` request body shape
    - Mock `bedrock-runtime`; assert the Titan body for `titan1024` contains `inputText` and merged `provider_params`; assert the Nova body for `nova1024` contains the multimodal schema with `embeddingDimension=1024`; assert `boto3.client("bedrock-runtime", region_name=…)` honored `AWS_REGION`; assert returned vector length matches `profile.dimensions` for both profiles
    - File: `tests/unit/test_bedrock_provider.py`
    - _Requirements: 11.2_

  - [ ]* 2.6 Unit tests for retry schedule and `LocalProvider`
    - With `time.sleep` patched to record call args, assert three transient errors followed by success yield exactly the `[1.0, 2.0, 4.0]` schedule; assert HTTP 500 / 503 retried, HTTP 400 `ValidationException` not retried, exhaustion raises a single `EmbeddingError` carrying `profile.model_id` and the last underlying error
    - In a separate test, mask `sentence_transformers` from `sys.modules` and assert `LocalProvider(mpnet768_profile)` raises `EmbeddingError` containing "sentence-transformers is not installed" and emits exactly one `[ERROR]` log line
    - Files: `tests/unit/test_bedrock_provider_retry.py`, `tests/unit/test_local_provider.py`
    - _Requirements: 11.3, 11.4_

- [ ] 3. Profile-aware index resolver
  - [ ] 3.1 Replace `PRODUCTION_INDICES` with profile-keyed structure
    - In `src/config/aws_config.py`, remove the module-level `PRODUCTION_INDICES` constant and add `PRODUCTION_INDICES_BY_PROFILE: dict[str, dict[str, str]]` containing the `titan1024` map (the five `mdc-{domain}-titan1024` indices) and the `mpnet768` map (preserve the prior `mdc-{domain}-mpnet768` values)
    - Add `get_production_indices(profile_short_name) -> dict[str, str]` returning the inner map for the given profile or `{}` for profiles with no registered map (the Nova family for now)
    - _Requirements: 8.1, 8.2, 8.5_

  - [ ] 3.2 Extend `resolve_index` for profile routing
    - Change the signature to `resolve_index(collection: str, profile_short_name: str = "titan1024") -> str`
    - Consult `get_production_indices(profile_short_name)`; return the mapped index when the collection is registered, otherwise return the collection name unchanged (covers Nova profiles with no registered map and any unknown collection)
    - Preserve backwards compatibility for callers that pass only the collection arg by defaulting to `titan1024`
    - _Requirements: 8.3, 8.4, 8.5_

  - [ ]* 3.3 Unit tests for resolver routing
    - Cover all five known collections under both `titan1024` and `mpnet768`, an unknown collection passing through unchanged for both, and a Nova profile (`nova1024`) returning the collection name unchanged
    - File: `tests/unit/test_aws_config_resolver.py`
    - _Requirements: 11.5_

- [ ] 4. Environment variable + warn line
  - [ ] 4.1 Parse and validate `MCP_EMBEDDING_PROFILE` in `src/config/environment.py`
    - Add `embedding_profile: str = "titan1024"` to `ServerConfig`
    - In `load_config`, read `MCP_EMBEDDING_PROFILE`, default to `titan1024` when unset, and validate the value against `EmbeddingModelRegistry().list_profiles()`
    - On an unrecognized value, raise `ConfigError` whose message lists the six accepted values
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ] 4.2 Emit one-shot `[WARN]` log line on `mpnet768`
    - When the resolved profile is `mpnet768`, emit a single `[WARN]` line stating that the legacy parity-debug fallback is active and that sentence-transformers is not installed in the runtime image
    - Guard with a module-level flag so the line is emitted at most once per process; ensure `ConfigError` paths short-circuit before any warn fires
    - _Requirements: 7.4_

  - [ ]* 4.3 Unit tests for env var parsing
    - Cover unset → `titan1024`, each of the six accepted values accepted, a bogus value raises `ConfigError` whose message contains all six accepted names, and `mpnet768` triggers exactly one `[WARN]` log line per process
    - File: `tests/unit/test_environment_embedding_profile.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 5. OpenSearchAdapter integration
  - [ ] 5.1 Drop the sentence-transformers default and `_mpnet_model` cache
    - In `src/data/opensearch_adapter.py`, remove the lazy `from sentence_transformers import SentenceTransformer` inside `_default_mpnet_embedding`, the `_default_mpnet_embedding` method itself, and the module-level `_MPNET` / `_mpnet_model()` cache
    - Confirm no remaining import of `sentence_transformers` exists at module load time
    - _Requirements: 6.1, 6.2, 6.3, 10.2, 10.3, 10.4_

  - [ ] 5.2 Resolve provider in `__init__` and rewrite `_generate_embedding`
    - In `__init__`, read `MCP_EMBEDDING_PROFILE` (default `titan1024`), look up the profile via `EmbeddingModelRegistry().get_profile`, and build the provider via `create_provider(profile)` only when `embedding_function` was not supplied; cache `self._profile` and `self._provider`
    - Rewrite `_generate_embedding` to invoke `self._embedding_function or self._provider.embed` via `asyncio.to_thread([query_text])`, return `embeddings[0]`, and translate `EmbeddingError` into `OpenSearchQueryError(str(exc), status=None)`
    - Catch any `EmbeddingError` raised by `create_provider` itself (e.g. `mpnet768` `LocalProvider` import failure) so the error surfaces from `_generate_embedding` rather than from adapter construction
    - _Requirements: 5.1, 5.2, 5.3, 6.4, 6.5, 9.3_

  - [ ] 5.3 Pass the active profile through to `resolve_index` in `query`
    - In `query` (and `multi_collection_query`), pass `self._profile.short_name` to `resolve_index` so a `titan1024` query vector hits a `titan1024` index
    - Leave the hybrid BM25 + k-NN body, the SigV4 transport, the `_search_with_retry` wrapper, and `_format_hits` unchanged
    - _Requirements: 8.1_

  - [ ] 5.4 Update `tests/conftest.py` fixtures
    - Add a `mock_bedrock_provider` fixture that yields a `BedrockProvider` whose `embed(texts)` returns `[[0.0] * profile.dimensions for _ in texts]`, and a `bedrock_provider_factory` fixture that patches `src.data.embedding_provider.create_provider` so the adapter constructor pulls the mock provider for any profile
    - Retire the prior mpnet stubs that injected `embedding_function=lambda xs: [[0.0]*768 for _ in xs]`; the dimension is now derived from the active profile so the same fixture works for `titan1024` (1024-dim) tests
    - _Requirements: 11.6_

  - [ ]* 5.5 Update `tests/unit/test_opensearch_adapter_embedding.py`
    - Cover: `_generate_embedding` returns the first vector from `provider.embed`; `EmbeddingError` raised by the provider becomes `OpenSearchQueryError(status=None)`; `MCP_EMBEDDING_PROFILE=titan1024` selects a `BedrockProvider` (via the fixture); `MCP_EMBEDDING_PROFILE=mpnet768` triggers a `LocalProvider` whose construction error propagates as `OpenSearchQueryError` from the first query
    - _Requirements: 11.6_

- [ ] 6. Container deps verification
  - [ ] 6.1 Verify `pyproject.toml` runtime deps
    - Confirm `boto3` is in `[project].dependencies` from Phase B2 and add no new packages
    - Run `pip install --dry-run` (or `uv pip compile` / equivalent) against the lock file and assert that `sentence-transformers`, `torch`, and `transformers` are absent from both direct and transitive deps
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 6.2 Document transitive dep audit results
    - Capture the `pip list` (or `pip-audit`) output from inside the built image into the phase-report scratch buffer for Task 11.1
    - Note any packages flagged as candidates for the "could pull torch back in" risk row, with the verifying check
    - _Requirements: 10.5_

- [ ] 7. Integration test gated on RUN_INTEGRATION
  - [ ]* 7.1 Add `tests/integration/test_bedrock_embedding.py`
    - Skip when `os.getenv("RUN_INTEGRATION") != "1"`; otherwise build the `titan1024` profile, construct a real `BedrockProvider`, run `provider.embed(["hello world"])` 5 times, assert each returned vector has length 1024
    - Compute p50 and p95 from `time.perf_counter` deltas across the 5 runs and print them; expose a small latency-stats helper for re-use
    - Use `AWS_REGION=us-east-1` from the boto3 default chain
    - _Requirements: 11.7, 12.4_

- [ ] 8. Pre-deploy validation
  - [ ] 8.1 Run the full pytest suite
    - From `mcp_server_python/`, run `pytest -q --no-header` and confirm 716 baseline tests plus the new tests added by Phase C-2c all pass without `RUN_INTEGRATION=1`
    - Capture the final `passed` count for the CHANGELOG entry in Task 11.2
    - _Requirements: 11.8_

  - [ ] 8.2 Checkpoint — Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Build, push, deploy
  - [ ] 9.1 Build the `python-titan-v1` image
    - From `mcp_server_python/`, run `docker build --platform linux/arm64 -t 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-titan-v1 -f Dockerfile .`
    - Capture the local image SHA via `docker image inspect … --format '{{.Id}}'` for the deploy artifacts table
    - _Requirements: 13.1_

  - [ ] 9.2 Capture image-size delta vs `python-all-tools-v3`
    - Record uncompressed local sizes via `docker image inspect … --format '{{.Size}}'` for both `python-titan-v1` and `python-all-tools-v3`
    - After the push in 9.3, record the compressed manifest sizes via `aws ecr describe-images --repository-name mdc-mcp-rag --image-ids imageTag=python-titan-v1 imageTag=python-all-tools-v3`
    - Hand both deltas to Task 11.1 for the phase report and Task 11.2 for the CHANGELOG line
    - _Requirements: 10.5_

  - [ ] 9.3 Push `python-titan-v1` to ECR
    - `aws ecr get-login-password … | docker login …`, then `docker push 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-titan-v1`
    - Verify `python-all-tools-v3` is still present in ECR (rollback target preserved)
    - Capture the ECR manifest digest from `aws ecr describe-images` for the deploy artifacts table
    - _Requirements: 13.1, 13.2_

  - [ ] 9.4 `update-agent-runtime` for the staging runtime
    - Run `aws bedrock-agentcore-control update-agent-runtime --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN` with `--agent-runtime-artifact` pointing at the new `python-titan-v1` image
    - Pass `--environment-variables` preserving the Phase C-2b set (`DB_BACKEND=aws`, `NEPTUNE_ENDPOINT`, `OPENSEARCH_ENDPOINT`, `AWS_REGION=us-east-1`, `MCP_STATELESS_HTTP=true`, `MCP_WORKFLOW_ROOT=/app/supported_repos/global-workflow`) and additionally `MCP_EMBEDDING_PROFILE=titan1024` (set explicitly even though it is the default, so the active profile is auditable from the AgentCore console)
    - Reuse the same `--role-arn`, `--network-configuration`, `--protocol-configuration`, `--lifecycle-configuration` from C-2b
    - _Requirements: 13.3, 13.4_

  - [ ] 9.5 Poll runtime status until READY
    - `aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN --query 'status'` until `READY`; record the new version number
    - On any non-`READY` terminal status, abort the deploy and surface the failure reason rather than proceeding to live validation
    - _Requirements: 13.3_

- [ ] 10. Live validation
  - [ ] 10.1 `get_server_info` and `mcp_health_check({deep:true})`
    - Call both tools against the redeployed runtime
    - Confirm 51/51 tools and 9/9 modules from `get_server_info`; confirm Vector status `healthy` and Vector index doc-count totals greater than 100 000 from `mcp_health_check`
    - _Requirements: 12.2_

  - [ ] 10.2 `search_documentation({query:"data assimilation cycling"})`
    - Call the tool and assert at least one hit is returned (smokes the `titan1024` indices end-to-end through the new `BedrockProvider` path)
    - Record the top-5 hit IDs for the phase report
    - _Requirements: 12.1_

  - [ ] 10.3 `get_knowledge_base_status`
    - Call the tool and confirm vector status `healthy` and that no `Unhealthy / sentence_transformers missing` line appears in the output
    - _Requirements: 12.3_

  - [ ] 10.4 Capture verbatim outputs into the phase-report scratch
    - Save the raw responses from 10.1 / 10.2 / 10.3 plus the integration-test p50/p95 from Task 7.1 into a scratch markdown buffer for Task 11.1 to fold into the phase report
    - _Requirements: 14.2_

- [ ] 11. Documentation
  - [ ] 11.1 Write the phase report
    - Create `docs/reports/2026-05-14-phase-c2c-bedrock-embedding-swap.md`
    - Document the root cause (`No module named sentence_transformers` on every `search_documentation` call), the implementation (new registry + provider + profile-aware resolver + adapter rewrite), the test results (suite count delta from Task 8.1), the deploy outcome (image SHA + ECR manifest digest from Tasks 9.1–9.3), the p50/p95 latency (Task 7.1), the live validation outcomes (Task 10.4), the image-size delta (Task 9.2), and any parity deltas observed against the `mpnet768` indices
    - _Requirements: 14.2_

  - [ ] 11.2 Add the `[8.22.3]` CHANGELOG entry
    - Append a new `[8.22.3]` section to `CHANGELOG.md` summarizing the embedding-swap scope, the new and modified files, the test-count delta (716 baseline + N), the deploy artifacts (image SHA, ECR manifest digest, ECR tag `python-titan-v1`), the live validation outcomes, and the image-size delta
    - _Requirements: 14.1_

  - [ ] 11.3 Update the steering document
    - Add a `Phase C-2c` section to `.kiro/steering/06-python-port-progress.md` listing the runtime version (post-9.5), the new image tag `python-titan-v1`, the env-var set with `MCP_EMBEDDING_PROFILE=titan1024` highlighted, and a link to the Task 11.1 phase report
    - _Requirements: 14.3_

- [ ] 12. Final checkpoint and commit
  - [ ] 12.1 Checkpoint — All tests pass, live validation outputs documented
    - Confirm Task 8.1 ran green, Task 10.x outputs are captured, and Tasks 11.1 / 11.2 / 11.3 are written; ask the user if any questions arise.

  - [ ] 12.2 Single commit on `develop_aws` referencing Phase C-2c
    - Stage the new and modified Python files, the conftest update, the unit + integration test files, `pyproject.toml` (if touched), the phase report, the CHANGELOG entry, and the steering update
    - Commit with a message of the form `Phase C-2c: Bedrock-native embedding swap (titan1024 default)` on the existing `develop_aws` branch
    - Do **not** push — the operator handles the batch push to the remote
    - _Requirements: 14.1, 14.2, 14.3_

## Notes

- Sub-tasks marked with `*` are optional (test-only or audit-only) and can be skipped to ship faster; core implementation, deploy, validation, and documentation sub-tasks are unmarked.
- Each sub-task references the specific requirement IDs from `requirements.md` for traceability.
- Property-based tests are deliberately omitted: per the design's Testing Strategy section, the embedding step is a side-effect-only call to an external service, the profile / index resolver is a small fixed mapping, and the retry schedule is a specific timing contract — all better verified by mocked unit tests plus one real integration call.
- Tasks 9.1 → 9.5 are strictly sequential (build → measure → push → update-runtime → poll). Tasks 10.1 / 10.2 / 10.3 can be issued in parallel against the redeployed runtime; 10.4 collects their outputs.
- Task 12.2 stops at `git commit` — the operator pushes as part of the batch push window per workspace convention.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0,  "tasks": ["1.1", "3.1", "6.1"] },
    { "id": 1,  "tasks": ["1.2", "2.1", "3.2", "4.1"] },
    { "id": 2,  "tasks": ["2.2", "3.3", "4.2"] },
    { "id": 3,  "tasks": ["2.3"] },
    { "id": 4,  "tasks": ["2.4", "4.3"] },
    { "id": 5,  "tasks": ["5.1"] },
    { "id": 6,  "tasks": ["2.5", "5.2", "5.4"] },
    { "id": 7,  "tasks": ["2.6", "5.3"] },
    { "id": 8,  "tasks": ["5.5", "6.2", "7.1"] },
    { "id": 9,  "tasks": ["8.1"] },
    { "id": 10, "tasks": ["9.1"] },
    { "id": 11, "tasks": ["9.2"] },
    { "id": 12, "tasks": ["9.3"] },
    { "id": 13, "tasks": ["9.4"] },
    { "id": 14, "tasks": ["9.5"] },
    { "id": 15, "tasks": ["10.1", "10.2", "10.3"] },
    { "id": 16, "tasks": ["10.4"] },
    { "id": 17, "tasks": ["11.1", "11.2", "11.3"] },
    { "id": 18, "tasks": ["12.2"] }
  ]
}
```
