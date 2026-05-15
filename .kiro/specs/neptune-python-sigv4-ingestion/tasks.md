# Implementation Plan: Neptune Python SigV4 Ingestion

## Overview

Replace the non-functional Bolt driver in `aws_backend.py` with an HTTP-based Neptune adapter using SigV4 request signing. All changes are confined to `mcp_server_node/scripts/aws_backend.py` (new classes + modified `get_graph_driver()`). Tests go in `mcp_server_node/test/tests/unit/test_neptune_http_adapter.py`. The four ingestion scripts require zero code changes.

## Tasks

- [x] 1. Add exception classes and endpoint normalization
  - [x] 1.1 Add `NeptuneQueryError` and `NeptuneConnectionError` exception classes to `aws_backend.py`
    - `NeptuneQueryError(status_code, message)` stores status code and formats error string
    - `NeptuneConnectionError` for network/timeout failures
    - Add required imports: `time`, `urllib.parse`
    - _Requirements: 4.4, 6.1, 6.2, 6.4_
  - [x] 1.2 Add `_normalize_endpoint(endpoint)` helper function
    - Convert `wss://` prefix to `https://`
    - Convert `bolt+s://` prefix to `https://`
    - Prepend `https://` and append `:8182` for bare hostnames
    - Ensure URL ends with `/opencypher`
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - [x] 1.3 Write property test for endpoint normalization (Property 3)
    - **Property 3: Endpoint normalization produces valid HTTPS URL**
    - Use Hypothesis to generate random hostnames with `wss://`, `bolt+s://`, `https://`, and bare formats
    - Assert output starts with `https://`, contains original hostname, ends with `/opencypher`
    - **Validates: Requirements 7.2, 7.3, 7.4**

- [x] 2. Implement `NeptuneResult` class
  - [x] 2.1 Add `NeptuneResult` class to `aws_backend.py`
    - Constructor takes `records: list[dict]` (the `results` array from Neptune JSON)
    - `single()` returns first record or `None` if empty
    - `__iter__` and `__next__` support iteration over records
    - Each record supports `record["column"]` dict-style access
    - _Requirements: 4.1, 4.2, 4.3, 4.5_
  - [x] 2.2 Write property test for response parsing (Property 2)
    - **Property 2: Response parsing preserves all records and column access**
    - Use Hypothesis to generate lists of dicts with string keys and mixed-type values
    - Assert `NeptuneResult` yields exactly N records, column access returns correct values, `single()` returns first or None
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5**

- [x] 3. Implement `NeptuneSession` class with SigV4 signing
  - [x] 3.1 Add `NeptuneSession` class to `aws_backend.py`
    - Constructor takes `endpoint`, `region`, `pool` (urllib3 PoolManager)
    - `run(query, **params)` calls internal `_execute_with_retry`
    - `close()` is a no-op; `__enter__`/`__exit__` support context manager
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [x] 3.2 Implement `_execute_query` method on `NeptuneSession`
    - Build POST body: `query=<url-encoded-cypher>&parameters=<url-encoded-json>` (omit parameters when none)
    - Set `Content-Type: application/x-www-form-urlencoded`
    - Obtain fresh credentials via `boto3.Session().get_credentials().get_frozen_credentials()`
    - Create `botocore.awsrequest.AWSRequest` and sign with `botocore.auth.SigV4Auth(creds, "neptune-db", region)`
    - Send via `urllib3.PoolManager.request("POST", url, body=..., headers=..., timeout=30)`
    - Parse JSON response, return `NeptuneResult(response["results"])`
    - Raise `NeptuneQueryError` on HTTP 4xx errors, `NeptuneConnectionError` on timeouts
    - _Requirements: 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 3.4, 3.5, 6.3, 6.5_
  - [x] 3.3 Implement `_execute_with_retry` method on `NeptuneSession`
    - Wrap `_execute_query` with retry logic: up to 3 retries on HTTP 429, 500, 503
    - Exponential backoff: 1s, 2s, 4s
    - Print `[WARN]` on retry attempts, `[ERROR]` on final failure
    - _Requirements: 6.1, 6.2, 8.2, 8.3_
  - [x] 3.4 Write property test for parameter serialization (Property 1)
    - **Property 1: Parameter serialization preserves all values**
    - Use Hypothesis to generate dicts with string/int/float/bool/None/list/nested-dict values
    - Mock urllib3 to capture the POST body, decode and verify `parameters` field equals original dict
    - **Validates: Requirements 3.1, 3.4, 3.5**

- [x] 4. Implement `NeptuneHTTPAdapter` class and wire `get_graph_driver()`
  - [x] 4.1 Add `NeptuneHTTPAdapter` class to `aws_backend.py`
    - Constructor takes `endpoint` and `region`, normalizes endpoint, creates `urllib3.PoolManager`
    - `session()` returns a new `NeptuneSession`
    - `close()` clears the urllib3 pool
    - `verify_connectivity()` runs `RETURN 1` and prints `[OK] Connected to Neptune (HTTP/SigV4): <endpoint>`
    - _Requirements: 1.1, 2.1, 2.5, 2.6, 8.1_
  - [x] 4.2 Modify `get_graph_driver()` to return `NeptuneHTTPAdapter` when `BACKEND == "aws"`
    - Replace the existing Bolt driver creation with `NeptuneHTTPAdapter(endpoint, AWS_REGION)`
    - Keep the `NEPTUNE_ENDPOINT` missing check and `sys.exit(1)`
    - Remove the `neo4j` import from the `aws` branch (move it to the `else` branch only)
    - _Requirements: 1.1, 1.5, 7.1, 7.5_

- [x] 5. Checkpoint — Verify adapter compiles and basic structure
  - Ensure all classes are syntactically correct and importable
  - Run `python3 -c "import aws_backend"` from `mcp_server_node/scripts/`
  - Ask the user if questions arise

- [x] 6. Write unit tests
  - [x] 6.1 Create `mcp_server_node/test/tests/unit/test_neptune_http_adapter.py` with test scaffolding
    - Import adapter classes from `aws_backend`
    - Set up `unittest.mock` patches for `urllib3.PoolManager.request` and `boto3.Session`
    - Add helper to build mock Neptune JSON responses
    - _Requirements: all_
  - [x] 6.2 Implement factory and session unit tests
    - `test_get_graph_driver_returns_adapter`: BACKEND=aws returns NeptuneHTTPAdapter
    - `test_get_graph_driver_exits_without_endpoint`: sys.exit(1) when NEPTUNE_ENDPOINT missing
    - `test_session_context_manager`: `with adapter.session() as s:` works
    - `test_run_sends_post_to_opencypher`: HTTP POST to /opencypher URL
    - `test_run_includes_sigv4_auth_header`: Authorization header present
    - `test_content_type_header`: Content-Type is application/x-www-form-urlencoded
    - `test_request_timeout_30s`: timeout=30 passed to urllib3
    - `test_credentials_refreshed_per_request`: get_credentials() called each time
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.4, 3.3, 6.3, 6.5_
  - [x] 6.3 Implement parameter and result unit tests
    - `test_run_with_params_includes_parameters_field`: POST body has `parameters=`
    - `test_run_without_params_omits_parameters_field`: POST body has only `query=`
    - `test_result_iteration`: iterate over multi-row response
    - `test_result_single_returns_first`: single() returns first record
    - `test_result_single_empty`: single() returns None for empty results
    - `test_result_column_access`: record["col"] returns correct value
    - _Requirements: 3.1, 3.2, 4.1, 4.2, 4.3, 4.5_
  - [x] 6.4 Implement error handling and endpoint unit tests
    - `test_retry_on_503`: retries 3 times on 503, then succeeds
    - `test_retry_exhausted_raises`: raises after max retries
    - `test_error_response_raises`: 400 raises NeptuneQueryError
    - `test_timeout_raises`: network timeout raises NeptuneConnectionError
    - `test_verify_connectivity_sends_return_1`: verify_connectivity() sends RETURN 1
    - `test_verify_connectivity_prints_ok`: prints [OK] on success
    - `test_endpoint_normalization_wss`: wss:// → https://
    - `test_endpoint_normalization_bolt`: bolt+s:// → https://
    - `test_endpoint_normalization_bare`: bare hostname → https://host:8182/opencypher
    - _Requirements: 4.4, 6.1, 6.2, 6.4, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3_

- [x] 7. Checkpoint — Run all tests
  - Run unit tests: `python3 -m pytest mcp_server_node/test/tests/unit/test_neptune_http_adapter.py -v`
  - Run property tests (if implemented): verify all 3 properties pass with 100+ iterations
  - Ensure all tests pass, ask the user if questions arise

- [x] 8. Final validation
  - [x] 8.1 Verify zero changes to ingestion scripts
    - Confirm `ingest_fortran_graph.py`, `ingest_shell_graph_v8.py`, `ingest_cross_language_bridges.py`, `ingest_code_v8.py` have no modifications
    - _Requirements: 5.5_
  - [x] 8.2 Verify `aws_backend.py` imports cleanly and legacy path is unaffected
    - Run `python3 -c "from aws_backend import get_graph_driver, get_vector_client"` from scripts dir
    - Verify `DB_BACKEND=legacy` still returns neo4j driver (no regression)
    - _Requirements: 1.1, 5.5_

- [x] 9. Final checkpoint — All tests green
  - Ensure all unit tests and property tests pass
  - Ensure all tests pass, ask the user if questions arise

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All implementation is confined to `mcp_server_node/scripts/aws_backend.py`
- Tests use `unittest.mock` to patch urllib3 and boto3 — no live Neptune needed
- Property tests use the `hypothesis` library with minimum 100 iterations per property
- The four ingestion scripts must have zero code changes (Requirement 5.5)
- After task completion, run Track B ingestion script against live Neptune to validate end-to-end
