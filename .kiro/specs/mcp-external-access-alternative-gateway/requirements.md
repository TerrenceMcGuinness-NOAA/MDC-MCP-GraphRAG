# Requirements: MCP External Access — Path C (Gateway-fronted, Cognito JWT on AgentCore Gateway)

**Spec ID:** `mcp-external-access-alternative-gateway`
**Created:** 2026-08-06
**Supersedes:** `.kiro/specs/mcp-external-access-revised/` (Path B, Runtime-attached JWT) —
partially. See "Inheritance" below.
**Created under:** R11.3 of the Path B spec, which reserved this spec ID for Path C work.

---

## Introduction

Path B attached a Cognito JWT authorizer directly to the AgentCore Runtime and assumed the
Runtime would serve JWT (for CI and HPC) and IAM SigV4 (for developers) on the same
endpoint. **That assumption is false.** AWS documents that an AgentCore Runtime supports
either IAM SigV4 or JWT bearer inbound auth, but not both simultaneously.

Path C resolves this by moving the authorizer off the Runtime:

- The **AgentCore Runtime stays on default IAM SigV4** inbound auth. The Developer_Principal
  path is therefore unchanged **by construction**, not by regression-testing a coexistence
  behavior that does not exist.
- An **AgentCore Gateway** fronts the Runtime as an `agentcoreRuntime` target, holds the
  Cognito JWT authorizer, and signs SigV4 outbound to the Runtime using its execution role.
- A **Gateway REQUEST interceptor Lambda** injects validated principal, scope, and
  attribution context into `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*` headers, which the
  MCP_Server reads for tool gating and audit.

The full analysis, including the AWS documentation citations and the eight decision points,
is in `../mcp-external-access-revised/decision-log.md`. That file is normative context for
this spec.

### Inheritance from the Path B spec

The following Path B content is **inherited unchanged** and is not restated here. Treat the
referenced sections as part of this spec by reference.

| Inherited | Source | Why it transfers |
|---|---|---|
| Cognito user pool, resource server, scopes, CI + HPC app clients | Path B requirements R1, R12; design §3 | Authorizer config shape is identical for Runtime or Gateway |
| HPC auth via Authorization Code + PKCE (primary), SRP (fallback) | Path B R4, R12; design AD-1, §6 | Cognito-side only; no dependency on where the authorizer attaches |
| Token_Broker Lambda and federated CI role | Path B R3; design §4 | Issues tokens; agnostic to authorizer placement |
| CI attribution via Token_Broker log-join on `broker_request_id` | Path B R3.6–R3.12, R13; design AD-3, §4.4 | Migrates cleanly; the interceptor carries the same field |
| GitHub Actions composite action | Path B R3; design §5 | Consumes a token and a URL |
| HPC_CLI_Helper (`mdc-mcp-jwt`) | Path B R4.15; design §6 | Unchanged |
| Allowed_Tool_Set *structure* — explicit enumeration, default-deny, `MUTATION_TOOL_SET` excluded from both JWT scopes | Path B R5; design AD-5, §10 | Gateway does not rename tools (Runtime targets forward unmodified) |
| Audit log JSON Lines schema and non-blocking writer | Path B R6; design §9 | Stateless by design (C-IMPACT-1) |
| Data safety, `cdk diff` guardrails, DeletionPolicy tests | Path B R9; design §12.4–§12.6 | Repo-wide steering, unchanged |

**Explicitly NOT inherited** (superseded — do not implement):

- Path B **R2.9** and **R2.10** — dual inbound auth on one Runtime. Void.
- Path B **R7.2** — "separate SigV4 path bypassing the JWT requirement" on the Runtime.
  Restated as R2.4 / R7.2 below.
- Path B design **§7.4** (SigV4 coexistence) — factually wrong.
- Path B design **AD-6** claims-header propagation mechanism — replaced by R4 below.

### Scope boundary

Out of scope: NOAA SSO / SAML federation (remains a forward reference; see Path B R12.4 and
`decision-log.md` §2.3 item 2), MFA enforcement, FIPS endpoint pinning, and
customer-managed KMS. These are tracked as hardening backlog from
`docs/reports/2026-06-30-mcp-external-access-fedramp-control-mapping.md`, which is
**advisory** — we are confirmed not operating inside a FedRAMP boundary.

---

## Glossary (delta from Path B)

- **Gateway** — the AgentCore Gateway resource fronting the Runtime. Its protocol type is
  **unset** (Runtime targets cannot be added to MCP-protocol-type gateways).
- **Runtime_Target** — the `agentcoreRuntime` target registered on the Gateway, addressed by
  runtime ARN plus optional qualifier.
- **Gateway_Execution_Role** — the IAM role the Gateway assumes to sign SigV4 requests to
  the Runtime_Target.
- **Request_Interceptor** — the REQUEST-type interceptor Lambda that injects trusted context
  headers.
- **Trusted_Context_Headers** — `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal`,
  `-Scope`, and `-BrokerRequestId`.
- **Gateway_Endpoint** — `https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/{targetName}/invocations`;
  the new value of the exported `McpEndpointUrl`.

---

## Requirements

### Requirement 0: Verification Gate (blocking)

**User Story:** As a platform operator, I want the two unverified AWS behaviors confirmed
against a real deployment before implementation begins, so that we do not repeat the Path B
failure of building on an unverified platform assumption.

#### Acceptance Criteria

1. THE verification SHALL confirm whether a REQUEST interceptor Lambda is invoked for an
   MCP-protocol AgentCore Runtime target when the Runtime responds with
   `Content-Type: application/json`, and THE result SHALL be recorded in
   `docs/reports/mcp-external-access-gateway-verification.md` (DP-7).
2. THE verification SHALL confirm whether headers injected by the Request_Interceptor
   arrive at the MCP_Server container, and SHALL record the exact header names observed
   (DP-1).
3. IF the interceptor is NOT invoked for a JSON-response Runtime target, THEN
   implementation SHALL NOT proceed on the Runtime_Target architecture, AND THE MCP-target
   architecture (DP-8) SHALL be evaluated as the alternative before any further work.
4. THE verification SHALL record whether the Runtime, when reached through the Gateway,
   requires `FASTMCP_JSON_RESPONSE=true` for criterion 1 to hold, OR whether interceptors
   fire regardless of response framing.
5. Implementation tasks (Requirements 1–9) SHALL NOT start until criteria 1, 2, and 4 are
   recorded.

### Requirement 1: AgentCore Gateway and Runtime Target

**User Story:** As a platform operator, I want a Gateway fronting the Runtime, so that there
is a single governed public entry point for external MCP consumers.

#### Acceptance Criteria

1. THE Gateway SHALL be created with no protocol type set, so that an `agentcoreRuntime`
   target can be attached.
2. THE Runtime_Target SHALL reference the existing AgentCore Runtime by ARN with an explicit
   qualifier, and SHALL NOT require the Runtime URL to be constructed by hand.
3. THE Runtime_Target outbound authorization SHALL be **IAM (SigV4)**, such that the Gateway
   assumes the Gateway_Execution_Role to sign requests to the Runtime.
4. THE Gateway SHALL expose the Gateway_Endpoint, and THE CDK stack SHALL export it as
   `McpEndpointUrl`, replacing the Runtime invocation URL previously exported under that
   name.
5. THE Runtime_Target SHALL NOT be given an OpenAPI or Smithy schema, since the Runtime uses
   the MCP protocol and receives a default schema automatically.

### Requirement 2: Gateway JWT Authorizer

**User Story:** As a platform operator, I want the Cognito authorizer on the Gateway, so
that JWT validation happens at the governed entry point and the Runtime keeps SigV4.

#### Acceptance Criteria

1. THE Gateway `customJWTAuthorizer` SHALL be configured with the Cognito discovery URL, a
   non-empty `allowedClients` list, a non-empty `allowedAudience` list, and a non-empty
   `allowedScopes` list. *(Inherits Path B R2.1–R2.8 validation semantics verbatim.)*
2. WHEN a request arrives at the Gateway_Endpoint without a valid Cognito JWT, THE Gateway
   SHALL reject it with HTTP 401 and SHALL NOT forward it to the Runtime_Target, AND THE
   error response SHALL NOT contain claim values or tool metadata.
3. THE AgentCore Runtime SHALL NOT be configured with a `customJWTAuthorizer` at any point.
4. **(Replaces Path B R7.2.)** THE Developer_Principal SigV4 path to the Runtime SHALL
   remain functional, AND IF a resource-based policy restricting Runtime invocation to the
   Gateway_Execution_Role is attached, THEN that policy SHALL explicitly permit the
   Developer_Principal role in addition to the Gateway_Execution_Role.
5. THE Gateway_Execution_Role trust policy SHALL include `aws:SourceArn` and
   `aws:SourceAccount` conditions scoped to the Gateway ARN, so that no other principal can
   assume it and invoke the Runtime as the Gateway (DP-4).

### Requirement 3: Response Framing for Interceptor Compatibility

**User Story:** As a platform operator, I want the MCP_Server's response framing pinned to a
mode in which interceptors run, so that the trusted-context channel cannot silently vanish.

#### Acceptance Criteria

1. THE MCP_Server SHALL serve Streamable HTTP with `json_response` enabled, such that tool
   responses carry `Content-Type: application/json` and not `text/event-stream`.
2. THE `json_response` setting SHALL be expressed explicitly in `mcp_server.py` with an
   environment override, mirroring the existing `stateless_http` / `MCP_STATELESS_HTTP`
   treatment, so that the value is pinned in code rather than dependent on ambient
   environment configuration.
3. THE MCP_Server SHALL continue to run with `stateless_http=True`, which is mandatory for
   AgentCore Runtime MCP protocol mode.
4. IF `json_response` is disabled while the Gateway path is active, THEN a startup log line
   at WARNING level SHALL state that Gateway interceptors may not fire.
5. THE stdio transport path used for local development SHALL be unaffected by criteria 1–4.

### Requirement 4: Trusted Context Propagation

**User Story:** As a security reviewer, I want principal and scope derived from the
Gateway-validated token and unforgeable by the caller, so that tool scoping cannot be
bypassed by header spoofing.

#### Acceptance Criteria

1. THE Request_Interceptor SHALL read the Gateway-validated JWT claims and SHALL inject
   `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal`,
   `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope`, and
   `X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId`.
2. THE Runtime_Target `metadataConfiguration.allowedRequestHeaders` SHALL allowlist exactly
   the Trusted_Context_Headers and SHALL NOT exceed 10 request headers.
3. WHEN a client supplies any Trusted_Context_Header itself, THE Request_Interceptor
   SHALL overwrite it, such that the value reaching the MCP_Server is always
   interceptor-derived.
4. THE Request_Interceptor SHALL NOT log the inbound `Authorization` header or any raw token
   value.
5. THE Request_Interceptor SHALL be configured with `passRequestHeaders: true`, since it
   requires inbound header visibility.
6. IF the Request_Interceptor cannot derive a principal, THEN it SHALL return a
   `transformedGatewayResponse` with HTTP 403 and SHALL NOT forward the request.
7. THE Request_Interceptor SHALL complete within 2 seconds, and IF it exceeds that budget
   THEN the failure SHALL be recorded in the audit log.

### Requirement 5: MCP_Server Authorization Middleware

**User Story:** As a security reviewer, I want tool scoping enforced in the MCP_Server, since
the Gateway cannot see tool names for a Runtime target.

#### Acceptance Criteria

1. THE MCP_Server middleware SHALL derive the principal from the Trusted_Context_Headers
   rather than from any authorizer-claims header. *(Inherits Path B R5 tool-set semantics.)*
2. WHEN no Trusted_Context_Header is present, THE MCP_Server SHALL treat the request as the
   `developer-sigv4` principal and SHALL apply the all-53-tools Allowed_Tool_Set.
3. IF a principal invokes a tool outside its Allowed_Tool_Set, THEN THE MCP_Server SHALL
   reject with HTTP 403 and SHALL NOT execute the tool.
4. IF a `Scope` header value is not a recognized scope, THEN THE MCP_Server SHALL reject
   with HTTP 403 (default-deny).
5. THE Allowed_Tool_Set source file SHALL remain a single explicit enumeration with
   default-deny, preserving Path B C-IMPACT-2.
6. **THE per-scope tool counts SHALL be re-derived against the Python runtime before
   enforcement is written.** Path B's "CI 40 / HPC 48 / developer 51" was derived against the
   retired **Node** runtime (`mdc_mcp_rag_server-TMXDllG2Wi`, 51 tools). The active runtime is
   **Python** `mdc_mcp_rag_server_python-v5K2F8BGrN` with **53 tools** (verified live
   2026-08-13 via `get_server_info`; progress.md C1 recorded 52, which is now also stale), so at
   least two tools are unaccounted for in the Path B split. The known additions are
   `extract_ci_error_signal` (module `error_analysis`, absent from the steering catalog until
   2026-08-13) plus one further tool to be identified during re-derivation. THE re-derivation
   SHALL enumerate
   the Python runtime's actual `tools/list` output and assign every tool to
   `mcp/ci-readonly`, `mcp/hpc-user`, both, or neither, with no tool left unclassified.

### Requirement 6: Audit Logging

**User Story:** As an operator, I want every external invocation attributable.

#### Acceptance Criteria

1. THE audit entry SHALL include principal, scope, tool name, outcome, timestamp, and
   `broker_request_id`. *(Inherits Path B R6 schema.)*
2. THE audit entry SHALL include `SOURCE_IP` when the Gateway supplies it via Lambda client
   context, AND SHALL tolerate its absence.
3. THE Request_Interceptor SHALL be configured with a payload filter excluding
   `RESPONSE_BODY`, so that large RAG responses cannot breach the 6 MB Lambda payload
   limit, AND excluding it SHALL NOT alter the response returned to the caller.
4. THE audit log SHALL NOT contain raw token values or full JWT claim sets.

### Requirement 7: Developer Backward Compatibility

#### Acceptance Criteria

1. **(Amended 2026-08-13 — see design.md AD-C7.)** THE Developer_Principal path through
   `tools/agentcore-kiro-proxy.py` SHALL remain **functionally unchanged**: the same
   invocation transport (SigV4 `invoke_agent_runtime`), the same CLI contract, and the same
   `.kiro/settings/mcp.json` entry. THE file is NO LONGER required to be byte-identical.

   *Why amended:* the original "byte-identical" wording is unsatisfiable alongside R3.1.
   Response framing is a single server-wide switch — `mcp/server/streamable_http.py` selects
   JSON vs SSE from `is_json_response_enabled` alone and never from the client's `Accept`
   header — and both the Gateway path and the developer path terminate in the same
   MCP_Server process. The proxy's `parse_sse()` collected only `data:`-prefixed lines, so
   enabling `json_response` made it return zero payloads and emit
   `-32603 "Empty SSE response"` on every developer call. Holding R7.1 literally would
   forbid R3.1 outright.

   THE proxy SHALL therefore accept **both** framings (SSE frames and a bare JSON object or
   array), so that the developer path is insensitive to the server's framing mode. This is
   strictly more robust than the prior state, which silently depended on an
   externally-controlled default.
2. **(Restates Path B R7.2.)** THE Developer_Principal SHALL reach the Runtime over SigV4
   without presenting a JWT, satisfied structurally by R2.3 and R2.4.
3. THE `.kiro/settings/mcp.json` entry for the developer server SHALL remain
   byte-identical to its pre-feature state.
4. WHEN all 53 tools are invoked over the Developer_Principal SigV4 path, THE verification
   SHALL observe a successful MCP response for 53 of 53 tools.

### Requirement 8: Infrastructure as Code

#### Acceptance Criteria

1. THE Gateway, Runtime_Target, Gateway_Execution_Role, and Request_Interceptor SHALL be
   defined in a dedicated CDK stack named `MdcMcpGatewayStack`.
2. THE stack SHALL NOT modify the existing Runtime's inbound auth configuration.
3. THE stack SHALL be added to `bin/cdk.ts` with an explicit dependency on the stack owning
   the Runtime.
4. `cdk synth` SHALL succeed for the full app before any deploy.
5. THE naming inconsistency in the Path B spec SHALL NOT be reproduced: this spec's
   directory name and all internal self-references SHALL agree.
6. **THE stack SHALL NOT create any `AWS::IAM::Role`.** `PowerUserRestrictions` blocks
   `iam:CreateRole` (progress.md C7). All roles SHALL be imported via `fromRoleName` or
   `fromRoleArn` with `mutable: false`, and any role that does not yet exist SHALL be added to
   `docs/mdc-external-access-alt-iam-request.txt` for admin pre-creation. A test SHALL assert
   `AWS::IAM::Role` count == 0, matching the Path B stack's existing guard.
7. THE stack SHALL NOT introduce a CDK construct that implicitly provisions a custom-resource
   Lambda with an auto-created execution role, since that also requires `iam:CreateRole`
   (progress.md C12).
8. IF any update to the AgentCore Runtime is ever required, THEN the call SHALL carry the
   **full lossless payload**, because `bedrock-agentcore-control:update-agent-runtime` is a
   full-replacement API — a partial payload silently wipes `networkConfiguration`,
   `environmentVariables`, `protocolConfiguration`, `roleArn`, `agentRuntimeArtifact`, and
   `lifecycleConfiguration` (progress.md C9). *(Path C should not need this: R2.3 forbids
   attaching an authorizer to the Runtime.)*
9. THE `cdk diff` guardrail SHALL be performed by the operator at actual deploy time.
   `cdk diff` produces no output in the staging environment due to absent CloudFormation
   `GetTemplate` connectivity (progress.md R12 note), so synth success plus resource-type
   assertions are the in-environment substitute, not a replacement for operator review.

### Requirement 9: Documentation

#### Acceptance Criteria

1. `docs/runbooks/mcp-external-access-ci.md` and `...-hpc.md` SHALL document token
   acquisition and the Gateway_Endpoint.
2. THE runbooks SHALL state that the developer SigV4 path targets the Runtime directly, not
   the Gateway.
3. A troubleshooting section SHALL cover: interceptor not firing, 401 at the Gateway, 403
   from tool scoping, and missing Trusted_Context_Headers.

---

## Correctness Properties

Inherits Path B Properties 1–5, 7, 8, 9, 10 with "Runtime authorizer" read as "Gateway
authorizer". Property 6 is restated and two are added.

- **Property 6 (restated):** for all 53 tools, a SigV4 invocation by the Developer_Principal
  directly against the Runtime succeeds, and the Runtime has no `customJWTAuthorizer`.
- **Property 11:** for any client-supplied value of a Trusted_Context_Header, the value
  observed by the MCP_Server equals the interceptor-derived value (unforgeability).
- **Property 12:** for every request admitted by the Gateway, exactly one audit entry exists
  whose `broker_request_id` joins to a Token_Broker log entry, or the principal is
  `developer-sigv4`.
