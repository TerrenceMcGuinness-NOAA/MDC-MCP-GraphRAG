# Tasks

## Task 1: Create proxy script skeleton with CLI argument parsing and logging

- [x] 1.1 Create `tools/agentcore-kiro-proxy.py` with shebang line (`#!/usr/bin/env python3`) and module docstring
- [x] 1.2 Implement CLI argument parsing: `--runtime-id` (required), `--region` (default: us-east-1), `--verbose` flag
- [x] 1.3 Implement environment variable fallbacks: `AGENTCORE_RUNTIME_ID`, `AWS_REGION`, `LOG_LEVEL`
- [x] 1.4 Configure Python logging to stderr only (never stdout), with INFO default and DEBUG when verbose
- [x] 1.5 Implement startup banner: log version, runtime ID, region, and generated session ID to stderr
- [x] 1.6 Implement session ID generation: `f"kiro-proxy-{uuid.uuid4().hex}"` (43 chars, exceeds 33 minimum)

## Task 2: Implement StdinReader — newline-delimited JSON-RPC input

- [x] 2.1 Implement `read_message()` function that reads one line from stdin and parses as JSON
- [x] 2.2 Handle EOF detection (return None, triggering shutdown)
- [x] 2.3 Handle malformed JSON lines: log to stderr, skip the line, continue reading
- [x] 2.4 Handle partial/empty lines: strip whitespace, skip blank lines

## Task 3: Implement AgentCoreClient — boto3 invoke_agent_runtime wrapper

- [x] 3.1 Create boto3 client: `boto3.client('bedrock-agentcore', region_name=region)`
- [x] 3.2 Implement `invoke()` method: serialize JSON-RPC payload, call `invoke_agent_runtime` with correct parameters (agentRuntimeId, runtimeSessionId, contentType, accept, payload, qualifier)
- [x] 3.3 Implement retry logic: up to 3 retries with exponential backoff (0.5s, 1.0s, 2.0s) for retryable exceptions (ThrottlingException, ServiceUnavailableException, InternalServerException, RequestTimeoutException)
- [x] 3.4 Implement session recovery: detect session-expired errors, generate new session ID, retry once
- [x] 3.5 Read StreamingBody response: `response['response'].read().decode('utf-8')`

## Task 4: Implement SSEParser — parse AgentCore SSE response format

- [x] 4.1 Implement SSE frame parsing: split on double-newline (`\n\n`) to get individual frames
- [x] 4.2 Extract `data:` field from each frame, handling `event: message` prefix
- [x] 4.3 Handle multi-line `data:` fields by concatenating lines (strip `data:` prefix from each)
- [x] 4.4 Parse extracted data as JSON; on malformed JSON, log raw frame to stderr and return error dict
- [x] 4.5 Return list of parsed JSON-RPC response objects

## Task 5: Implement main loop and stdout writer

- [x] 5.1 Implement main loop: read_message → invoke → parse_sse → write_stdout, repeat until EOF
- [x] 5.2 Implement stdout writer: serialize JSON-RPC response as single-line JSON + newline, flush immediately
- [x] 5.3 Handle notifications (messages without `id`): forward to AgentCore, handle case where response may differ
- [x] 5.4 Implement error response construction: `make_error_response(request_id, code, message, data)`
- [x] 5.5 Wrap message processing in try/except to catch unhandled exceptions, return error response, continue loop

## Task 6: Implement signal handling and graceful shutdown

- [x] 6.1 Register SIGTERM and SIGINT handlers that set a shutdown flag
- [x] 6.2 Check shutdown flag in main loop; finish in-flight request before exiting
- [x] 6.3 Log shutdown reason and session ID to stderr on exit
- [x] 6.4 Exit with code 0 on clean shutdown (EOF, SIGTERM, SIGINT) and non-zero on error

## Task 7: Write property-based tests with Hypothesis

- [x] 7.1 [PBT] Property 1: JSON-RPC message round-trip — for any valid JSON-RPC message, serialize as line then parse back produces identical object
- [x] 7.2 [PBT] Property 2: SSE parsing round-trip — for any valid JSON-RPC response, wrapping in SSE format then parsing extracts the original object
- [x] 7.3 [PBT] Property 3: Transparent forwarding — for any JSON-RPC message, the payload sent to boto3 preserves method, params, and id fields exactly
- [x] 7.4 [PBT] Property 4: Session ID invariants — all generated session IDs are >= 33 chars and unique
- [x] 7.5 [PBT] Property 5: Error responses are well-formed — for any error condition, response has code -32603, non-empty message, and correct id
- [x] 7.6 [PBT] Property 6: Retry behavior — for any retryable exception, exactly 4 total calls (1 + 3 retries) before error response
- [x] 7.7 [PBT] Property 7: Resilience — after an error on one request, subsequent requests are processed successfully

## Task 8: Write unit tests for specific scenarios

- [x] 8.1 Test EOF handling: send EOF on stdin, verify process exits cleanly within 5 seconds
- [x] 8.2 Test notification forwarding: send `notifications/initialized`, verify forwarded without expecting response
- [x] 8.3 Test session reuse: send multiple requests, verify all use same session ID
- [x] 8.4 Test session recovery: mock session-expired error, verify new session ID and retry
- [x] 8.5 Test CLI argument parsing: verify --runtime-id required, --region defaults, --verbose sets DEBUG
- [x] 8.6 Test credential error: mock NoCredentialsError, verify clear stderr message
- [x] 8.7 Test startup banner: verify version, runtime ID, region, session ID all present in stderr

## Task 9: Create Kiro MCP configuration and documentation

- [x] 9.1 Create example mcp.json entry for the proxy (command type, python3, args with script path and --runtime-id)
- [x] 9.2 Add README section or inline comments documenting usage, configuration, and troubleshooting
- [x] 9.3 Verify the proxy works end-to-end: configure in mcp.json, restart Kiro, confirm tools/list returns 51 tools
