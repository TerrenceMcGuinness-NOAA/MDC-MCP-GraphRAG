# Requirements Document

**Spec ID:** `gateway-interceptor-verification`
**Created:** 2026-08-14
**Parent spec:** `.kiro/specs/mcp-external-access-alternative-gateway/` (Path C, Requirements 0.1–0.5)
**Normative context:** `../mcp-external-access-revised/decision-log.md` (Parts 1–4),
`../mcp-external-access-alternative-gateway/design.md` (AD-C1, AD-C4, AD-C7, §9 Gate Register)

---

## Introduction

This spec operationalizes Path C's **Requirement 0 (Verification Gate)** — the single
blocking gate for the entire Cognito-based external authentication system for the NOAA Global
Workflow MCP-RAG server. Path C's architecture depends on two unverified AWS platform
behaviors:

1. **DP-7 (AWS half):** Do REQUEST interceptor Lambdas fire for an `agentcoreRuntime` target
   on a Gateway when the MCP server responds with `Content-Type: application/json` (buffered
   mode)?
2. **DP-1 (confirmation):** Do headers injected by the interceptor
   (`X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`) arrive at the MCP container?

If both answers are YES, Path C is viable and the full implementation
(`.kiro/specs/mcp-external-access-alternative-gateway/` Tasks 1–9) may proceed. If either
answer is NO, the Runtime-target architecture (AD-C1) is invalidated and DP-8 flips to the
MCP-target architecture before any further work.

### Why this gate matters

The MCP External Access feature has gone through three spec iterations. Path A (original)
failed on two Cognito defects (no RFC 8628 device flow, no Pre-Token trigger for M2M).
Path B (revised) corrected the auth flows and implemented Tasks 0–5 (CDK stack with Cognito
user pool, Token_Broker Lambda, 53/53 tests pass), but then discovered that an AgentCore
Runtime supports either SigV4 or JWT, not both simultaneously — attaching JWT would break
the developer SigV4 path. Path C pivots to a Gateway-fronted architecture where the Runtime
stays SigV4 and the Gateway holds the JWT authorizer. Path C exists precisely because Path B
built on an unverified platform assumption (dual inbound auth). This gate ensures we do not
repeat that mistake.

### Sandbox relaxation

The operator has explicitly relaxed the throwaway-runtime constraint from Path C Task 0. The
live runtime (`mdc_mcp_rag_server_python-v5K2F8BGrN`, v44, `python-tenants-v16`) may be
modified directly for verification purposes, saving the overhead of creating and managing a
parallel runtime. All changes are reversible via `update-agent-runtime` with the pre-
verification payload.

### Scope boundary

This spec verifies the **interceptor mechanism only**. It does NOT cover: Cognito user pool
creation (already done in Path B Tasks 1–5), Token_Broker Lambda (already done), full
MCP_Server authorization middleware, HPC CLI helper, GitHub Actions composite action, cost
sizing (separate DP-6 gate), or Runtime resource-based policy (separate DP-2 decision).

---

## Glossary

- **Runtime** — the live AgentCore Runtime `mdc_mcp_rag_server_python-v5K2F8BGrN` (v44,
  `python-tenants-v16`, 53 tools, HEALTHY 4/4) in account 903050880929, region us-east-1.
- **Gateway** — a temporary AgentCore Gateway created for this verification, with protocol
  type unset.
- **Runtime_Target** — the `agentcoreRuntime` target registered on the Gateway, addressed by
  the Runtime ARN with qualifier `DEFAULT`.
- **Echo_Interceptor** — a minimal REQUEST-type interceptor Lambda that logs event structure
  and injects a single fixed trusted-context header.
- **Trusted_Context_Header** — any header matching
  `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`, the documented channel for injecting
  runtime-bound custom context from an interceptor.
- **Framing_Mode** — the response wire format: SSE (`text/event-stream`, the current
  default) or JSON (`application/json`, the buffered mode required for interceptors).
- **Developer_Proxy** — `tools/agentcore-kiro-proxy.py` v1.2.0, the stdio-to-AgentCore
  bridge used by Kiro developers. Already framing-tolerant (handles both SSE and JSON
  responses per AD-C7).
- **Full_Payload** — the complete `update-agent-runtime` request body including all six
  fields that the full-replacement API requires: `agentRuntimeArtifact`,
  `roleArn`, `networkConfiguration`, `environmentVariables`, `protocolConfiguration`,
  `lifecycleConfiguration`, `metadataConfiguration`, and `filesystemConfigurations`.
- **Verification_Report** — the evidence document written to
  `docs/reports/mcp-external-access-gateway-verification.md`.

---

## Requirements

### Requirement 1: Response Framing Switch

**User Story:** As a platform operator, I want the MCP server to respond with
`Content-Type: application/json` (buffered mode) rather than `text/event-stream` (SSE), so
that Gateway interceptors can fire against the Runtime target.

#### Acceptance Criteria

1. THE Runtime SHALL be updated via `update-agent-runtime` to include the environment
   variable `FASTMCP_JSON_RESPONSE=true` alongside all existing environment variables
   (DB_BACKEND, NEPTUNE_ENDPOINT, OPENSEARCH_ENDPOINT, AWS_REGION, MCP_STATELESS_HTTP,
   MCP_WORKFLOW_ROOT).
2. THE `update-agent-runtime` call SHALL carry the Full_Payload, because
   `bedrock-agentcore-control:update-agent-runtime` is a full-replacement API — a partial
   payload silently wipes `networkConfiguration`, `environmentVariables`,
   `protocolConfiguration`, `roleArn`, `agentRuntimeArtifact`, `lifecycleConfiguration`,
   and `filesystemConfigurations`.
3. THE `MCP_STATELESS_HTTP=true` environment variable SHALL NOT be removed or changed,
   because stateless mode is mandatory for AgentCore MCP protocol mode.
4. WHEN the Runtime restarts with `FASTMCP_JSON_RESPONSE=true`, THE MCP_Server SHALL
   respond to `tools/list` and `tools/call` requests with `Content-Type: application/json`
   rather than `text/event-stream`.
5. WHEN the Runtime restarts with `FASTMCP_JSON_RESPONSE=true`, THE Runtime health check
   SHALL report HEALTHY (4/4 components: Base, Utility, Vector, Graph DB), AND `get_server_info`
   SHALL report 53 registered tools.
6. THE Verification_Report SHALL record the actual fastmcp and mcp library versions
   running inside the container, since `pyproject.toml` pins `fastmcp==3.2.4` but the
   environment has been observed running `fastmcp 3.4.1` / `mcp 1.27.2` (AD-C7 dependency-
   pin drift).

### Requirement 2: Developer Proxy Preservation

**User Story:** As a developer, I want the Kiro developer SigV4 proxy to continue working
after the framing change, so that existing tooling is not disrupted by the verification.

#### Acceptance Criteria

1. WHEN the Runtime is serving `json_response=True`, THE Developer_Proxy SHALL successfully
   invoke `get_server_info` via the SigV4 `invoke_agent_runtime` transport and return a
   valid JSON-RPC response.
2. WHEN the Runtime is serving `json_response=True`, THE Developer_Proxy SHALL successfully
   invoke at least one graph-backed tool (`find_callers_callees` or `get_code_context`) and
   return a non-empty result.
3. IF the Developer_Proxy returns a `-32603 "Empty SSE response"` error for any tool call,
   THEN the proxy's framing tolerance is broken and THE Verification_Report SHALL record
   this as a blocking regression requiring investigation before proceeding.
4. THE `.kiro/settings/mcp.json` entry for the developer server SHALL remain byte-identical
   to its pre-verification state.
5. THE Developer_Proxy file (`tools/agentcore-kiro-proxy.py`) SHALL NOT be modified as part
   of this verification — it is already framing-tolerant at v1.2.0.

### Requirement 3: Gateway and Runtime Target Creation

**User Story:** As a platform operator, I want a temporary Gateway fronting the Runtime, so
that the interceptor mechanism can be tested against the live MCP server.

#### Acceptance Criteria

1. THE Gateway SHALL be created with no protocol type set, because `agentcoreRuntime`
   targets cannot be attached to MCP-protocol-type gateways.
2. THE Runtime_Target SHALL reference the live Runtime by ARN
   (`arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN`)
   with qualifier `DEFAULT`, AND SHALL NOT require the Runtime URL to be constructed by hand.
3. THE Runtime_Target outbound authorization SHALL be IAM (SigV4), such that the Gateway
   signs requests to the Runtime using the Gateway's execution role.
4. THE Gateway SHALL NOT have a `customJWTAuthorizer` configured — this verification tests
   only the interceptor mechanism, not JWT validation.
5. THE Runtime_Target `metadataConfiguration.allowedRequestHeaders` SHALL include at least
   `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal`, so that the Echo_Interceptor's
   injected header is permitted to reach the container.
6. THE Gateway creation SHALL record the Gateway ID and the full Gateway_Endpoint URL in
   the Verification_Report for traceability.
7. IF Gateway creation fails due to a missing execution role, THEN THE
   Verification_Report SHALL record the exact IAM error and the role name required, AND THE
   role requirements SHALL be added to
   `docs/mdc-external-access-alt-iam-request.txt` for admin pre-creation.

### Requirement 4: Echo Interceptor Lambda

**User Story:** As a platform operator, I want a minimal interceptor Lambda attached to the
Gateway, so that I can observe whether the interceptor fires and whether its injected headers
reach the container.

#### Acceptance Criteria

1. THE Echo_Interceptor SHALL be a REQUEST-type interceptor Lambda configured with
   `passRequestHeaders: true`, so that it can observe inbound headers.
2. THE Echo_Interceptor SHALL log the event structure to CloudWatch, logging only header
   **names** (never values), the request path, and the request method, so that event
   structure is recorded without leaking tokens or credentials.
3. THE Echo_Interceptor SHALL inject the header
   `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal` with value `probe` into the
   `transformedGatewayRequest`, overwriting any client-supplied value of that header.
4. THE Echo_Interceptor SHALL pass the request body through unchanged (still base64-encoded
   for HTTP/Runtime targets), so that the MCP server receives a valid JSON-RPC payload.
5. THE Echo_Interceptor SHALL return the `interceptorOutputVersion` as `"1.0"` in its
   response envelope, per the documented interceptor contract.
6. THE Echo_Interceptor SHALL be configured with a payload filter excluding `RESPONSE_BODY`,
   so that large RAG responses cannot breach the 6 MB Lambda synchronous invoke payload
   limit.
7. IF the Echo_Interceptor encounters an error parsing the event, THEN it SHALL log the
   error with the event keys (never the full body) and return a
   `transformedGatewayResponse` with HTTP 500, rather than crashing and leaving the request
   in an undefined state.
8. THE Echo_Interceptor source code SHALL be committed to
   `infrastructure/cdk/lambda/gateway_echo_interceptor/index.py` for reproducibility, even
   though the verification is a one-time probe.

### Requirement 5: Verification Invocations

**User Story:** As a platform operator, I want to invoke the MCP server through the Gateway
and observe whether the interceptor fired and whether its header arrived, so that DP-7 and
DP-1 are answered with empirical evidence.

#### Acceptance Criteria

1. THE verification SHALL invoke the Gateway_Endpoint with a `tools/list` JSON-RPC body
   (`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`) and record the HTTP
   status code, response content type, and response body.
2. THE verification SHALL determine whether the Echo_Interceptor fired by checking for a
   CloudWatch log entry in the interceptor Lambda's log group containing the logged request
   path.
3. THE verification SHALL determine whether the injected header
   `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal: probe` arrived at the MCP container
   by one of: (a) adding a temporary debug log line to `mcp_server.py` that logs received
   header names (never values) when a `Custom-Principal` header is present, (b) inspecting
   the Runtime's CloudWatch log group, or (c) invoking a tool that echoes request metadata.
4. THE verification SHALL record the answers to both questions as structured fields in the
   Verification_Report:
   - **Q1 (DP-7):** Did the interceptor Lambda execute? (YES/NO, with CloudWatch log
     evidence)
   - **Q2 (DP-1):** Did the injected header arrive at the container? (YES/NO, with
     evidence)
5. IF the Gateway rejects the invocation with HTTP 401 or 403, THEN THE Verification_Report
   SHALL record the rejection reason, AND THE verification SHALL attempt the invocation
   with SigV4 credentials signed against the Gateway endpoint (since no JWT authorizer is
   configured, SigV4 may be required).
6. WHEN the injected header arrives at the container, THE observed value SHALL be exactly
   `probe` (byte-for-byte match), confirming that interceptor-injected values are not
   truncated or transformed in transit.
7. IF the verification environment permits, THE verification SHOULD invoke through the
   Gateway a second time with `Content-Type: text/event-stream` framing (by temporarily
   removing `FASTMCP_JSON_RESPONSE=true`) to isolate whether framing is the trigger for
   interceptor execution. This is informational — the primary verification uses JSON
   framing.

### Requirement 6: Evidence Recording and Decision Branch

**User Story:** As the spec author, I want the verification results permanently recorded
with the decision branch taken, so that future spec iterations do not repeat the pattern of
building on unverified assumptions.

#### Acceptance Criteria

1. THE Verification_Report SHALL be written to
   `docs/reports/mcp-external-access-gateway-verification.md` and SHALL include: date,
   runtime version, container image tag, fastmcp/mcp library versions, Gateway ID,
   Gateway_Endpoint URL, Echo_Interceptor Lambda ARN, and the answers to Q1 and Q2 with
   raw evidence.
2. THE Verification_Report SHALL include the exact CLI commands or API calls used to create
   the Gateway, attach the target, deploy the interceptor, and invoke through the Gateway,
   so the verification is reproducible.
3. THE Verification_Report SHALL include a **decision branch** section:
   - IF Q1=YES AND Q2=YES: record "**Path C Runtime-target architecture CONFIRMED viable.**
     Proceed with `.kiro/specs/mcp-external-access-alternative-gateway/` Tasks 1–9.
     AD-C1 validated."
   - IF Q1=YES AND Q2=NO: record "**Header injection FAILED.** Interceptor fires but
     injected headers do not reach the container. Investigate
     `metadataConfiguration.allowedRequestHeaders` and target configuration before
     proceeding."
   - IF Q1=NO (regardless of Q2): record "**Interceptors do NOT fire for Runtime targets
     with JSON framing.** AD-C1 invalidated. Evaluate DP-8: the MCP-target architecture,
     which uses the `mcp` interceptor payload with parsed JSON-RPC and carries no
     buffered-only restriction. Amend `design.md` AD-C1 before any further task."
4. THE Verification_Report SHALL include any unexpected observations (error codes, latency
   anomalies, event structure differences from documentation) that inform the full Path C
   implementation.
5. WHEN the decision branch is recorded, THE Gate Register in
   `../mcp-external-access-alternative-gateway/design.md` §9.2 SHALL be updated to reflect
   the new status of Gate 1.

### Requirement 7: Rollback

**User Story:** As a platform operator, I want all verification artifacts cleanly removed
and the runtime restored to its pre-verification configuration, so that the verification
leaves no residual changes in the production environment.

#### Acceptance Criteria

1. THE Gateway created for verification SHALL be deleted after the verification results are
   recorded, so that it cannot be mistaken for a production resource or accrue cost.
2. THE Echo_Interceptor Lambda SHALL be deleted after the verification results are recorded.
3. IF the Runtime's environment variables were modified (adding `FASTMCP_JSON_RESPONSE`),
   THEN the Runtime SHALL be restored to its pre-verification configuration via
   `update-agent-runtime` with the Full_Payload containing exactly the original six
   environment variables (DB_BACKEND=aws, NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182, OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com, AWS_REGION=us-east-1, MCP_STATELESS_HTTP=true, MCP_WORKFLOW_ROOT=/mnt/workflow), unless the operator explicitly chooses to keep `FASTMCP_JSON_RESPONSE=true` for Path C readiness.
4. AFTER rollback, THE Runtime health check SHALL report HEALTHY (4/4) and `get_server_info`
   SHALL report 53 tools, confirming the runtime is in its pre-verification state.
5. THE Verification_Report SHALL document the exact `update-agent-runtime` rollback command
   with the Full_Payload, so the rollback is reproducible.
6. AFTER rollback, THE Developer_Proxy SHALL successfully invoke `get_server_info` and
   return a valid response, confirming the developer path is unaffected.
7. IF any IAM role was created for the Echo_Interceptor, THEN it SHALL be documented for
   admin cleanup, since `PowerUserRestrictions` may prevent the operator from deleting it.

### Requirement 8: Safety Constraints

**User Story:** As a security reviewer, I want the verification to follow the established
safety constraints for this environment, so that the production MCP-RAG server is not
degraded during the probe.

#### Acceptance Criteria

1. THE verification SHALL NOT attach a `customJWTAuthorizer` to the Runtime at any point,
   because an AgentCore Runtime supports either SigV4 or JWT, not both simultaneously, and
   attaching JWT would break the developer SigV4 path permanently until reversed.
2. THE verification SHALL NOT modify the Runtime's `networkConfiguration`,
   `protocolConfiguration`, `roleArn`, `agentRuntimeArtifact`, `lifecycleConfiguration`,
   or `filesystemConfigurations` — only `environmentVariables` may change.
3. THE Echo_Interceptor SHALL NOT log the `Authorization` header value, any raw token, or
   any request body content, because the interceptor Lambda's CloudWatch logs are a separate
   security boundary from the Runtime's logs.
4. IF the `update-agent-runtime` call fails or returns an unexpected status, THE operator
   SHALL verify the Runtime configuration via `GetAgentRuntime` before retrying, because the
   full-replacement API may have partially applied.
5. THE Echo_Interceptor execution role SHALL have minimal permissions: only CloudWatch Logs
   write access. It SHALL NOT have permissions to invoke the Runtime, read from Neptune or
   OpenSearch, or access any other account resource.
6. THE verification SHALL be completable within a single working session (< 4 hours),
   including rollback, to minimize the window during which the Runtime is in a modified
   state.

---

## Correctness Properties

1. **P1 (Health invariant):** AFTER the `FASTMCP_JSON_RESPONSE=true` environment variable is
   added, THE Runtime SHALL report HEALTHY 4/4 and serve all 53 tools. Violation of P1
   halts the verification and triggers immediate rollback.

2. **P2 (Developer path invariant):** AFTER the framing change, THE Developer_Proxy SHALL
   successfully invoke at least `get_server_info` and one graph-backed tool
   (`find_callers_callees` or `get_code_context`) over SigV4, receiving valid JSON-RPC
   responses. Violation of P2 means the framing-tolerant proxy (AD-C7) has regressed.

3. **P3 (Header fidelity):** IF the interceptor fires AND the injected header arrives at the
   container, THEN the value observed by the MCP_Server SHALL be byte-for-byte identical to
   the value set by the interceptor (`probe`). A mismatch would mean the trusted-context
   channel is unreliable and Path C's unforgeability property (Property 11) cannot hold.

4. **P4 (No-auth Gateway rejection):** WHEN a request arrives at the Gateway_Endpoint
   without valid auth (no SigV4 signature, no JWT), THE Gateway SHALL reject it with
   HTTP 401 or 403. This confirms the Gateway is not an open relay.

5. **P5 (Rollback fidelity):** AFTER rollback, THE Runtime's configuration as reported by
   `GetAgentRuntime` SHALL match the pre-verification configuration byte-for-byte:
   same container image, same environment variables, same network config, same EFS mount,
   same lifecycle settings. Violation of P5 means the full-replacement API lost data.

6. **P6 (No JWT authorizer):** AT NO POINT during the verification SHALL `GetAgentRuntime`
   show a `customJWTAuthorizer` on the Runtime. This is the standing constraint from
   `../mcp-external-access-alternative-gateway/design.md` §9.3.

---

## Traceability to Parent Spec

| This Spec | Path C Parent (`mcp-external-access-alternative-gateway`) |
|---|---|
| Requirement 1 | R0.4, R3.1, R3.3 |
| Requirement 2 | R7.1, R7.2, R7.4 |
| Requirement 3 | R0.1, R1.1, R1.2, R1.3 |
| Requirement 4 | R0.2, R4.1, R4.5 |
| Requirement 5 | R0.1, R0.2, R0.4 |
| Requirement 6 | R0.3, R0.5 |
| Requirement 7 | R0.5, R2.3 |
| Requirement 8 | R2.3, R8.2 |
| P1 | Path C P6 (restated) |
| P2 | Path C P6 |
| P3 | Path C P11 (unforgeability) |
| P4 | Path C R2.2 |
| P5 | Path C R8.8 (full-replacement payload) |
| P6 | Path C §9.3 (standing constraint) |
