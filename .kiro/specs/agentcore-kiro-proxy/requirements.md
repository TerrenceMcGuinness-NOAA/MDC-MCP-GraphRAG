# Requirements Document

## Introduction

Build a stdio-based MCP proxy that bridges Kiro IDE to the AgentCore Runtime (`mdc_mcp_rag_server-TMXDllG2Wi`). Kiro connects to an EC2 instance via SSH remote development and runs MCP servers as local "command" type processes. This proxy receives MCP JSON-RPC messages from Kiro over stdin, forwards them to the AgentCore Runtime via the boto3 `InvokeAgentRuntime` API (SigV4-signed), parses the SSE response stream, and returns JSON-RPC results to Kiro over stdout.

This is the missing link for the 10-user NOAA developer cohort: each user's Kiro instance spawns its own proxy process on the EC2, which creates its own AgentCore session (separate microVM), providing per-user isolation with zero additional infrastructure.

## Glossary

- **Proxy**: The stdio-based Python MCP proxy process that translates between Kiro's stdin/stdout MCP transport and the AgentCore Runtime's HTTP SSE transport
- **AgentCore_Runtime**: The deployed AWS Bedrock AgentCore Runtime (`mdc_mcp_rag_server-TMXDllG2Wi`) hosting the 51-tool MCP server in isolated microVMs
- **Kiro_IDE**: The AI-powered IDE connecting to the EC2 via SSH remote development, which spawns "command" type MCP servers as child processes
- **MCP_JSON_RPC**: The Model Context Protocol message format — JSON-RPC 2.0 messages exchanged over stdin/stdout between Kiro and the Proxy
- **InvokeAgentRuntime**: The boto3 API call (`bedrock-agentcore-runtime.invoke_agent_runtime`) that sends JSON-RPC payloads to the AgentCore Runtime and receives SSE responses
- **SSE_Response**: The Server-Sent Events stream returned by InvokeAgentRuntime, formatted as `event: message\ndata: {json-rpc}\n\n`
- **Runtime_Session**: An AgentCore session identified by a `runtimeSessionId` (33+ characters), which maps to an isolated microVM and is reusable across multiple tool calls
- **MCP_Config**: The Kiro MCP server configuration file at `/home/ec2-user/.kiro/settings/mcp.json` where the Proxy is registered as a "command" type server

## Requirements

### Requirement 1: Stdin/Stdout MCP Transport

**User Story:** As a Kiro user, I want the proxy to communicate via stdin/stdout, so that Kiro can spawn it as a "command" type MCP server like the existing AWS Powers.

#### Acceptance Criteria

1. THE Proxy SHALL read MCP JSON-RPC messages from stdin, one JSON object per line (newline-delimited JSON)
2. THE Proxy SHALL write MCP JSON-RPC responses to stdout, one JSON object per line (newline-delimited JSON)
3. THE Proxy SHALL write all diagnostic and error logging to stderr, never to stdout
4. WHEN Kiro sends an EOF on stdin, THE Proxy SHALL terminate gracefully within 5 seconds
5. THE Proxy SHALL handle partial reads on stdin by buffering until a complete JSON object is received

### Requirement 2: AgentCore Runtime Forwarding

**User Story:** As a Kiro user, I want the proxy to forward my MCP requests to the AgentCore Runtime, so that I can access all 51 tools without direct HTTP connectivity to the runtime.

#### Acceptance Criteria

1. WHEN the Proxy receives a JSON-RPC request on stdin, THE Proxy SHALL forward it to the AgentCore Runtime via the boto3 `invoke_agent_runtime` API
2. THE Proxy SHALL use `contentType='application/json'` and `accept='application/json, text/event-stream'` in the API call
3. THE Proxy SHALL authenticate the API call using SigV4 signing via the EC2 instance's IAM credentials (boto3 default credential chain)
4. THE Proxy SHALL target the runtime identified by `agentRuntimeId='mdc_mcp_rag_server-TMXDllG2Wi'` in region `us-east-1`
5. IF the `invoke_agent_runtime` call fails with a boto3 exception, THEN THE Proxy SHALL return a JSON-RPC error response with the exception details and log the full traceback to stderr

### Requirement 3: SSE Response Parsing

**User Story:** As a Kiro user, I want the proxy to correctly parse AgentCore's SSE responses, so that tool results arrive intact.

#### Acceptance Criteria

1. WHEN the AgentCore Runtime returns an SSE stream, THE Proxy SHALL parse each `event: message\ndata: {json-rpc}\n\n` frame
2. THE Proxy SHALL extract the JSON-RPC payload from the `data:` field of each SSE event
3. THE Proxy SHALL write the extracted JSON-RPC payload to stdout as a single line
4. IF an SSE frame contains malformed JSON in the `data:` field, THEN THE Proxy SHALL log the raw frame to stderr and return a JSON-RPC error response to Kiro
5. THE Proxy SHALL handle multi-line SSE data fields by concatenating lines before JSON parsing

### Requirement 4: Session Management

**User Story:** As a Kiro user, I want the proxy to maintain a single AgentCore session across my tool calls, so that I get consistent performance from a warm microVM.

#### Acceptance Criteria

1. THE Proxy SHALL generate a `runtimeSessionId` of 33 or more characters on startup
2. THE Proxy SHALL reuse the same `runtimeSessionId` for all `invoke_agent_runtime` calls during its lifetime
3. WHEN the Proxy starts, THE Proxy SHALL log the generated session ID to stderr for debugging
4. IF the AgentCore Runtime returns a session error (expired or invalid session), THEN THE Proxy SHALL generate a new session ID and retry the request once

### Requirement 5: MCP Protocol Handling

**User Story:** As a Kiro user, I want the proxy to handle the full MCP handshake and tool lifecycle, so that Kiro discovers and invokes all 51 tools seamlessly.

#### Acceptance Criteria

1. WHEN Kiro sends an `initialize` request, THE Proxy SHALL forward it to the AgentCore Runtime and return the runtime's response
2. WHEN Kiro sends a `notifications/initialized` notification, THE Proxy SHALL forward it to the AgentCore Runtime
3. WHEN Kiro sends a `tools/list` request, THE Proxy SHALL forward it and return the complete tool list from the AgentCore Runtime
4. WHEN Kiro sends a `tools/call` request, THE Proxy SHALL forward it and return the tool execution result from the AgentCore Runtime
5. THE Proxy SHALL forward all JSON-RPC messages transparently without modifying the `method`, `params`, or `id` fields

### Requirement 6: Kiro MCP Configuration

**User Story:** As a developer onboarding to the cohort, I want a simple MCP configuration entry, so that I can connect to the AgentCore Runtime by adding one block to my mcp.json.

#### Acceptance Criteria

1. THE Proxy SHALL be configurable in Kiro's `mcp.json` as a "command" type server with `"command": "python3"` and `"args"` pointing to the proxy script
2. THE Proxy SHALL accept the `agentRuntimeId` and `region` as command-line arguments or environment variables
3. THE Proxy SHALL work with the existing EC2 IAM credentials without requiring additional credential configuration
4. THE MCP_Config entry SHALL follow the same pattern as the existing AWS Powers (uvx-based command servers)

### Requirement 7: Error Handling and Resilience

**User Story:** As a Kiro user, I want the proxy to handle transient failures gracefully, so that a single network hiccup does not require restarting my IDE.

#### Acceptance Criteria

1. IF a boto3 API call fails with a retryable error (throttling, transient network error), THEN THE Proxy SHALL retry up to 3 times with exponential backoff
2. IF all retries are exhausted, THEN THE Proxy SHALL return a JSON-RPC error response with code `-32603` (internal error) and a descriptive message
3. IF the Proxy encounters an unhandled exception during message processing, THEN THE Proxy SHALL log the exception to stderr and return a JSON-RPC error response rather than crashing
4. THE Proxy SHALL remain running and ready for the next request after any error, unless stdin is closed

### Requirement 8: Multi-User Isolation

**User Story:** As a member of the 10-user cohort, I want my proxy instance to be isolated from other users, so that my tool calls do not interfere with others.

#### Acceptance Criteria

1. THE Proxy SHALL generate a unique `runtimeSessionId` per process instance, ensuring each Kiro connection maps to a separate AgentCore microVM
2. WHEN two users run the Proxy simultaneously on the same EC2, THE Proxy instances SHALL operate independently with no shared state
3. THE Proxy SHALL NOT use any shared files, sockets, or IPC mechanisms between instances

### Requirement 9: Packaging and Distribution

**User Story:** As a developer onboarding to the cohort, I want the proxy available as a single file with no extra dependencies beyond boto3, so that setup is trivial on the provisioned EC2.

#### Acceptance Criteria

1. THE Proxy SHALL be implemented as a single Python file with no dependencies beyond the Python standard library and boto3
2. THE Proxy SHALL be compatible with Python 3.9 or later (the version available on the EC2)
3. THE Proxy script SHALL be executable and include a shebang line (`#!/usr/bin/env python3`)
4. THE Proxy SHALL be located in the repository at a documented path (e.g., `tools/agentcore-kiro-proxy.py`)

### Requirement 10: Observability and Debugging

**User Story:** As a developer troubleshooting connectivity issues, I want the proxy to provide clear diagnostic output, so that I can identify whether problems are in the proxy, the network, or the AgentCore Runtime.

#### Acceptance Criteria

1. WHEN the Proxy starts, THE Proxy SHALL log its version, the target `agentRuntimeId`, the AWS region, and the generated session ID to stderr
2. WHEN the Proxy forwards a request, THE Proxy SHALL log the JSON-RPC method name and request ID to stderr at debug level
3. WHEN the Proxy receives a response, THE Proxy SHALL log the response status and elapsed time to stderr at debug level
4. THE Proxy SHALL support a `--verbose` flag or `LOG_LEVEL` environment variable to control log verbosity (default: INFO, optional: DEBUG)
5. IF the Proxy fails to authenticate with AWS, THEN THE Proxy SHALL log a clear message identifying the credential issue to stderr

### Requirement 11: Graceful Shutdown

**User Story:** As a Kiro user, I want the proxy to shut down cleanly when I close my IDE, so that AgentCore sessions are released promptly.

#### Acceptance Criteria

1. WHEN the Proxy receives SIGTERM or SIGINT, THE Proxy SHALL stop reading from stdin and finish processing any in-flight request
2. WHEN the Proxy shuts down, THE Proxy SHALL log the shutdown reason and session ID to stderr
3. THE Proxy SHALL exit with code 0 on clean shutdown and non-zero on error shutdown
