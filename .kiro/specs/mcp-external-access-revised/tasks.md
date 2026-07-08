# Implementation Plan: MCP External Access — Alternative (Path B, Cognito JWT on AgentCore Runtime)

## Overview

Expose the MDC MCP RAG Server to GitHub Actions CI pipelines and HPC user sessions (Hera, Orion, Hercules, Gaea, Ursa) via a Cognito-backed JWT authorizer attached to the existing AgentCore Runtime `mdc_mcp_rag_server-TMXDllG2Wi`. This is the **scoped alternative** to `mcp-external-access`, per [Design §1](./design.md#1-overview). It preserves everything sound in the original and replaces exactly two decisions:

- **HPC authentication (AD-1)** — primary flow is **Authorization Code + PKCE** (RFC 7636) through the Cognito Hosted UI with **loopback** (RFC 8252) and **manual-code-paste** transports; **`USER_SRP_AUTH`** is a flag-selectable headless fallback. There is **no** RFC 8628 device flow and **no** dependency on a Cognito `/oauth2/device_authorization` endpoint (R4.4, R12.2).
- **CI attribution (AD-3)** — attribution is the **Token_Broker structured log** joined to the **MCP Request_Metadata** on the Token_Broker request id. There is **no** Cognito Pre-Token-Generation trigger and **no** DynamoDB claims-stash table (R3.12, R9.10, R13.1–R13.4).

The developer SigV4 path (`tools/agentcore-kiro-proxy.py`) remains byte-identical (R7). Path C (AgentCore Gateway + Cedar) is explicitly deferred per R11 — this plan contains **no** Path C implementation tasks. The CDK stack is `MdcExternalAccessAlternativeStack` so it coexists with the original stack without collision (AD-4).

## Task Counts

| Category | Count |
|----------|-------|
| Executable top-level tasks | 14 (Task 0 through Task 13) |
| Property-test subtasks | 10 (P1–P10) |
| Deferred placeholder groups | 1 ("Phase B → C Migration (deferred)") |

## Dependency Graph

```
Task 0 (pre-implementation gate — AD-2 curl → HTTP 401)
   │
   └─► Task 1 (CDK stack scaffold: MdcExternalAccessAlternativeStack)
         │
         ├─► Task 2 (Cognito pool + Hosted UI + resource server + CI/HPC clients + Secrets Manager)
         │        │
         │        ├─► Task 3 (GitHub OIDC federated IAM role)
         │        │
         │        ├─► Task 4 (Token_Broker Lambda — simplified, NO DynamoDB) depends on Task 2, Task 3
         │        │
         │        ├─► Task 5 (AgentCore authorizer update + drift detector) depends on Task 2
         │        │
         │        └─► Task 6 (MCP_Server middleware + toolScopeGuard + audit + Request_Metadata) depends on Task 2
         │
   Task 7 (GitHub composite action) depends on Task 4, Task 3
   Task 8 (HPC CLI helper — PKCE + SRP)   depends on Task 2
   Task 9 (developer SigV4 51/51 regression suite) depends on Task 5
   Task 10 (network verification) depends on Task 5
   Task 11 (documentation: CI + HPC runbooks) depends on Task 7, Task 8
   Task 12 (cdk diff guardrails + review record + drift) depends on Task 5
   Task 13 (end-to-end acceptance) depends on all prior tasks
```

## Tasks

- [ ] 0. Pre-implementation gate — verify public endpoint reachability under VPC mode
  - [ ] 0.1 Run the design-gate `curl` test against the existing Runtime
    - Execute: `curl -sS -o /tmp/mcp-401.json -w '%{http_code}
' "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A903050880929%3Aruntime%2Fmdc_mcp_rag_server-TMXDllG2Wi/invocations?qualifier=DEFAULT" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -H 'Authorization: Bearer not-a-real-token' -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'`
    - Expected: HTTP 401 response code (not a TCP refusal, not a 502) — proving the public endpoint is reachable and the authorizer is the rejecting component
    - _Requirements: R8.5, R8.6_
    - _Design: §2 AD-2, §11.2_
  - [ ] 0.2 Record the verification result in `docs/reports/mcp-external-access-alternative-verification.md`
    - Capture the UTC timestamp, the exact curl invocation, the response body, and the observed HTTP status code
    - This report is the R8.5 gate artifact — no other implementation task starts until it records a passing (HTTP 401) result
    - _Requirements: R8.5_
    - _Design: §11.2_
  - [ ] 0.3 Decision gate: if HTTP 401 observed, proceed to Task 1; otherwise pivot design per §11.3
    - If the test returns a TCP error or 502, STOP and revise the design to front the Runtime with an AgentCore Gateway (the §11.3/R8.6 fallback) before any implementation task begins
    - _Requirements: R8.6_
    - _Design: §11.3_

- [ ] 1. CDK stack scaffold — `MdcExternalAccessAlternativeStack`
  - [ ] 1.1 Create `infrastructure/cdk/lib/mdc-external-access-alternative-stack.ts` skeleton
    - Declare `MdcExternalAccessAlternativeStackProps` with `runtimeArn`, `mcpServerTaskRole`, `allowedGithubSubPatterns`
    - Export empty `MdcExternalAccessAlternativeStack` class extending `cdk.Stack`
    - _Requirements: R9.1_
    - _Design: §12.1, AD-4_
  - [ ] 1.2 Wire into `infrastructure/cdk/bin/cdk.ts`
    - Instantiate `MdcExternalAccessAlternativeStack` with env, `runtimeArn`, `mcpServerTaskRole: securityStack.ecsTaskRole`, and `addDependency(serverStack)`
    - Pass `allowedGithubSubPatterns` as `['repo:NOAA-EMC/global-workflow:ref:refs/heads/*', 'repo:NOAA-EMC/mdc-mcp-rag:ref:refs/heads/*']`
    - _Requirements: R9.1_
    - _Design: §12.2_
  - [ ] 1.3 Create test file `infrastructure/cdk/test/mdc-external-access-alternative-stack.test.ts`
    - Include placeholder assertions for each stateful resource type and for the R9.10 negative assertions (no DynamoDB, no PreTokenGeneration)
    - _Requirements: R9.4, R9.10_
    - _Design: §12.4_
  - [ ] 1.4 Validate `cdk synth MdcExternalAccessAlternativeStack` succeeds on the empty stack
    - No errors; an empty `Resources` block is acceptable at this stage
    - _Requirements: R9.1_
    - _Design: §12.1_

- [ ] 2. Cognito User Pool + Hosted UI domain + resource server + app clients + Secrets Manager
  - [ ] 2.1 Define `McpUserPool` in `mdc-external-access-alternative-stack.ts`
    - `userPoolName: 'mdc-mcp-external-access-alt'`, self-signup disabled, password policy min-length 14, advanced security ENFORCED, MFA optional/OTP
    - Set `removalPolicy: cdk.RemovalPolicy.RETAIN` per R1.2 and steering file 05
    - Add an explicit code comment: intentionally NO `lambdaTriggers.preTokenGeneration` (AD-3, R9.10)
    - _Requirements: R1.1, R1.2, R9.2_
    - _Design: §3.1_
  - [ ] 2.2 Define the Hosted UI domain `McpUserPoolDomain`
    - `cognitoDomain: { domainPrefix: 'mdc-mcp-external-alt' }` → `mdc-mcp-external-alt.auth.us-east-1.amazoncognito.com`
    - This domain serves the Authorization_Code_PKCE_Flow authentication pages for the HPC client
    - _Requirements: R1.6_
    - _Design: §3.2_
  - [ ] 2.3 Register resource server `McpResourceServer` with identifier `mcp`
    - Declare exactly two scopes: `ci-readonly` and `hpc-user` — ONLY these two custom scopes
    - Fully-qualified scope strings become `mcp/ci-readonly` and `mcp/hpc-user`
    - _Requirements: R1.3_
    - _Design: §3.3_
  - [ ] 2.4 Define `CiAppClient` (client-credentials only)
    - `generateSecret: true`; allowed OAuth scope `mcp/ci-readonly` only
    - Enable `clientCredentials`; disable authorization-code, implicit, and all `authFlows` (admin/user password, SRP, custom)
    - `accessTokenValidity: 60 minutes` (R1.8, R3.8); no access-token-customization trigger (plain M2M token per AD-3)
    - _Requirements: R1.4, R1.8, R3.8_
    - _Design: §3.4_
  - [ ] 2.5 Define `HpcAppClient` (Authorization Code + PKCE primary, SRP fallback)
    - `generateSecret: false` (public client → Cognito enforces PKCE on the auth-code exchange)
    - Enable `authorizationCodeGrant: true`; disable `clientCredentials` and `implicitCodeGrant`
    - `authFlows: { userSrp: true, userPassword: false, adminUserPassword: false, custom: false }` (SRP fallback enabled; ROPC disabled)
    - `callbackUrls`: `http://127.0.0.1:8765/callback` and `http://localhost:8765/callback` (RFC 8252 loopback; manual-paste reuses the same redirect)
    - Allowed OAuth scope `mcp/hpc-user` only; `accessTokenValidity: 60 minutes`, `enableTokenRevocation: true` (R1.8, R4.11)
    - _Requirements: R1.5, R1.8, R4.11_
    - _Design: §3.5, §2 AD-1_
  - [ ] 2.6 Store the CI_App_Client secret in Secrets Manager
    - Secret `mdc-mcp-external-access-alt/ci-app-client` = `{ client_id, client_secret }`
    - `removalPolicy: cdk.RemovalPolicy.RETAIN` (R9.3)
    - _Requirements: R9.3_
    - _Design: §3.4, §4.3_
  - [ ] 2.7 CDK unit tests for the Cognito constructs
    - Assert `DeletionPolicy: Retain` on the UserPool and the CI secret (R9.4)
    - Assert the resource server declares exactly the two scopes `ci-readonly`, `hpc-user` (R1.3)
    - Assert grant isolation: `CiAppClient` has only client-credentials; `HpcAppClient` has authorization-code + `USER_SRP_AUTH` and no client-credentials/ROPC (R1.4, R1.5)
    - Assert the Hosted UI domain resource is present (R1.6)
    - _Requirements: R1.3, R1.4, R1.5, R1.6, R9.4_
    - _Design: §12.4_
  - [ ] 2.8 CDK test — R9.10 negative assertions (no DynamoDB, no Pre-Token trigger)
    - Assert `template.resourceCountIs('AWS::DynamoDB::Table', 0)` — no claims-stash table exists anywhere in the stack
    - Assert every `AWS::Cognito::UserPool` has no `LambdaConfig.PreTokenGeneration` and no `LambdaConfig.PreTokenGenerationConfig`
    - _Requirements: R9.10, R13.1, R13.2_
    - _Design: §12.4, §2 AD-3_
  - [ ] 2.9 CDK test — no existing stateful resource types present in this stack (R9.5)
    - Assert the synthesized template contains no `AWS::Neptune::*`, `AWS::OpenSearchService::*`, `AWS::S3::Bucket`, or `AWS::EFS::*` resource types
    - _Requirements: R9.5_
    - _Design: §12.4_
  - [ ]* 2.10 Property P7 — JWT issuance invariants (scope isolation + lifetime bounds)
    - **Property 7: JWT issuance invariants (scope isolation + lifetime bounds)**
    - Property-based test (≥100 iterations, `fast-check`/Hypothesis) against a mocked Cognito token endpoint sampling both app clients: assert every issued token has `scope` equal to exactly `mcp/ci-readonly` (CI) or `mcp/hpc-user` (HPC) — never both, never empty — and `300 <= (exp - iat) <= 3600`
    - Tag: `Feature: mcp-external-access-alternative, Property 7`
    - **Validates: Requirements 1.8, 3.7, 3.8, 4.11**
    - _Design: §3.6, §13 Property 7_

- [ ] 3. GitHub OIDC federated IAM role
  - [ ] 3.1 Create IAM role `mdc-mcp-alt-gh-oidc-ci`
    - Trust policy federating `token.actions.githubusercontent.com` with `WebIdentityPrincipal`
    - `StringEquals` on `...:aud` = `sts.amazonaws.com`
    - `StringLike` on `...:sub` = `props.allowedGithubSubPatterns`, so STS rejects any `AssumeRoleWithWebIdentity` whose `sub` matches no allowlist entry
    - _Requirements: R3.1_
    - _Design: §4.2_
  - [ ] 3.2 Restrict the role's permissions to `lambda:InvokeFunction` on the Token_Broker ARN only
    - No other actions and no other resources; grant via `tokenBroker.grantInvoke(ciOidcRole)` after Task 4 defines the function
    - _Requirements: R3.2_
    - _Design: §4.2_
  - [ ] 3.3 CDK tests for the federated role
    - Assert `Principal.Federated` includes `token.actions.githubusercontent.com`
    - Assert `Condition.StringLike['token.actions.githubusercontent.com:sub']` equals the configured allowlist
    - Assert the attached policy is scoped to a single Lambda ARN with only `lambda:InvokeFunction`
    - _Requirements: R3.1, R3.2, R9.4_
    - _Design: §4.2_

- [ ] 4. Token_Broker Lambda (simplified — log-join attribution, NO DynamoDB, NO trigger)
  - [ ] 4.1 Implement handler at `infrastructure/cdk/lambda/token_broker/index.py`
    - Python 3.12 runtime; use `context.aws_request_id` as the attribution join key
    - Parse `github_claims` (`sub`, `run_id`, `repository`, `ref`) from the invocation payload
    - Flow: allowlist check → read CI secret → mint plain client-credentials token → return token + `request_id` → emit one attribution log line
    - Do **not** create a nonce, and do **not** write to any DynamoDB table (AD-3, R9.10)
    - _Requirements: R3.3, R3.12, R9.10_
    - _Design: §4.1, §2 AD-3_
  - [ ] 4.2 Enforce the repository/ref allowlist before any Cognito call (R3.10)
    - Compile `ALLOWED_SUB_PATTERNS_JSON` regex patterns at cold start; match against the assumed-role `github_claims.sub`
    - On mismatch: emit a `forbidden_repository` attribution log line, return HTTP 403 `{"error":"forbidden_repository","request_id":...}`, and do NOT call Cognito
    - _Requirements: R3.10_
    - _Design: §4.1, §4.5_
  - [ ] 4.3 Mint a plain client-credentials access token
    - Read the CI client secret from Secrets Manager (`CI_CLIENT_SECRET_ARN`)
    - POST `grant_type=client_credentials&scope=mcp/ci-readonly&client_id=...&client_secret=...` to `COGNITO_TOKEN_ENDPOINT`
    - Return `{access_token, expires_in, token_type, request_id}` to the caller within the 5 s end-to-end SLO (R3.3)
    - No custom claims are requested or injected — the token stays a plain M2M token (AD-3)
    - _Requirements: R3.3, R3.12_
    - _Design: §4.1_
  - [ ] 4.4 Emit the attribution-anchor log line keyed by the Token_Broker request id (R3.6, R13.3)
    - Write one structured JSON line `{event, request_id, github_run_id, github_repository, github_ref}` to `/mdc-mcp-rag-alt/token-broker`
    - NEVER write the issued access token to the log
    - This line is the join anchor recovered by the MCP_Server audit log on `broker_request_id`
    - _Requirements: R3.6, R13.3_
    - _Design: §4.1, §4.4_
  - [ ] 4.5 Handle upstream Cognito failures per R3.11
    - Catch network/timeout/HTTP errors from the Cognito token endpoint
    - Emit an `upstream_failure` attribution log line and return HTTP 502 `{"error":"upstream_token_issuance_failed",...}` without returning a JWT
    - _Requirements: R3.11_
    - _Design: §4.5_
  - [ ] 4.6 Emit an `slo_breach` warning when elapsed > 5000 ms
    - Still return 200 with the token (SLO, not a hard cutoff); log `{"warn":"slo_breach","request_id","elapsed_ms"}`
    - _Requirements: R3.3_
    - _Design: §4.1_
  - [ ] 4.7 Configure the Lambda function and its IAM
    - Name `mdc-mcp-alt-token-broker`, reserved concurrency 10, ~10 s timeout, 256 MB
    - Grant `secretsmanager:GetSecretValue` on the CI secret ARN only; grant NO DynamoDB permissions
    - Create log group `/mdc-mcp-rag-alt/token-broker` with `removalPolicy: RETAIN`, 90-day retention (R9.3)
    - _Requirements: R3.2, R9.1, R9.3_
    - _Design: §4.3, §4.6_
  - [ ]* 4.8 Unit tests with mocked Cognito + Secrets Manager
    - Cover: happy path (token + request_id returned), allowlist rejection (403, no Cognito call), Cognito timeout (502), secret-read failure
    - Assert the attribution log line never contains token material, and no DynamoDB client is instantiated
    - _Requirements: R3.6, R3.10, R3.11, R9.10_
    - _Design: §4.5_

- [ ] 5. AgentCore Runtime authorizer update + drift detector
  - [ ] 5.1 Implement the `AwsCustomResource` calling `bedrock-agentcore-control:UpdateAgentRuntime`
    - Use `cr.AwsCustomResource` in `MdcExternalAccessAlternativeStack` with a stable `physicalResourceId`
    - Set `authorizerConfiguration.customJWTAuthorizer` with `discoveryUrl`, `allowedAudience`, `allowedClients`
    - _Requirements: R2.1, R2.8_
    - _Design: §7.2_
  - [ ] 5.2 Populate authorizer config from Task 2 outputs
    - `discoveryUrl` = `https://cognito-idp.us-east-1.amazonaws.com/${userPool.userPoolId}/.well-known/openid-configuration`
    - `allowedAudience` and `allowedClients` = both `ciAppClient.userPoolClientId` and `hpcAppClient.userPoolClientId`
    - `addDependency(userPoolDomain, ciAppClient, hpcAppClient)`
    - _Requirements: R2.1, R2.3_
    - _Design: §7.1, §7.2_
  - [ ] 5.3 Grant the custom resource its scoped IAM policy
    - `bedrock-agentcore-control:UpdateAgentRuntime` and `:GetAgentRuntime` on the Runtime ARN only
    - _Requirements: R9.1_
    - _Design: §7.2_
  - [ ] 5.4 Snapshot the authorizer config and implement the drift detector (CodeBuild nightly)
    - Persist expected config to `infrastructure/cdk/snapshots/authorizer-config.json`
    - Shell script diffs live `get-agent-runtime` authorizer config against the snapshot; on drift emit a CloudWatch metric and open a `cdk-drift` GitHub issue
    - Every `cdk deploy` re-applies `updateAgentRuntime`, overwriting out-of-band changes (R2.8, R9.9)
    - _Requirements: R2.8, R9.9_
    - _Design: §7.3_
  - [ ] 5.5 Integration tests — three-path authorization at the MCP_Endpoint
    - Test A: invalid/opaque Bearer → HTTP 401 with no claim/tool metadata in the body (R2.5, R2.6)
    - Test B: valid CI JWT → forwarded to the MCP_Server (R2.3, R2.10)
    - Test C: SigV4 invocation via the unmodified proxy → forwarded to the MCP_Server (R2.9)
    - Test D: unreachable JWKS / missing `kid` → 401 or 503 (R2.7)
    - _Requirements: R2.5, R2.6, R2.7, R2.9, R2.10_
    - _Design: §7.4, §14_
  - [ ]* 5.6 Property P1 — valid token admission
    - **Property 1: Valid token admission**
    - Property-based test (≥100 iterations) generating valid Cognito-signed JWTs with random claim combinations; assert the MCP_Endpoint returns a successful MCP response for every token whose `iss`/`aud`/`exp` pass and whose scope maps to an Allowed_Tool_Set containing the requested tool
    - Tag: `Feature: mcp-external-access-alternative, Property 1`
    - **Validates: Requirements 1.8, 2.2, 2.3, 2.4, 5.1, 5.2**
    - _Design: §13 Property 1_
  - [ ]* 5.7 Property P2 — invalid token rejection without claim leakage
    - **Property 2: Invalid token rejection without claim leakage**
    - Property-based test (≥100 iterations) generating JWTs with bad signature, failing `iss`/`aud`/`scope`, expired beyond the 60 s skew, or non-JWT opaque bearers; assert HTTP 401 AND the response body contains no substring equal to any presented claim value or any tool-registry name
    - Tag: `Feature: mcp-external-access-alternative, Property 2`
    - **Validates: Requirements 2.5, 2.6, 2.7**
    - _Design: §13 Property 2_
  - [ ]* 5.8 Property P6 — developer SigV4 path preservation
    - **Property 6: Developer path preservation across all 51 tools**
    - Property-based test invoking tools from the 51-tool registry via the unmodified `agentcore-kiro-proxy.py` and unmodified `.kiro/settings/mcp.json` after the authorizer is live; assert each returns a non-error MCP response structurally identical to the pre-deployment response
    - Tag: `Feature: mcp-external-access-alternative, Property 6`
    - **Validates: Requirements 2.9, 2.10, 7.2, 7.5**
    - _Design: §13 Property 6_

- [ ] 6. MCP_Server authorization middleware + audit logger + Request_Metadata
  - [ ] 6.1 Create `mcp_server_node/src/auth/authMiddleware.js`
    - Read `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorizer-Claims`; base64url-decode and JSON-parse
    - Treat header ABSENCE as the `developer-sigv4` principal (SigV4 path bypasses JWT — R7.2)
    - Return `{type:'reject', status:401}` on missing/empty scope; `{type:'reject', status:403}` on unrecognized scope; never re-validate the JWT signature (AgentCore is the trust boundary)
    - _Requirements: R5.1, R5.9, R5.10, R7.2_
    - _Design: §8.2, §2 AD-6_
  - [ ] 6.2 Create `mcp_server_node/src/auth/allowedToolSets.js` — single source of truth (R5.11)
    - Export `CI_READONLY` (40 tools per Design §10.1), `HPC_USER` (48 tools = CI_READONLY ∪ 8 additions per §10.2), and `developer-sigv4` sentinel `'ALL'` (all 51, R5.6)
    - Export `MUTATION_TOOL_SET` (6 tools: `mark_as_modified`, `checkpoint_state`, `restore_checkpoint`, `start_sdd_session`, `record_sdd_step`, `complete_sdd_session`)
    - Header comment citing R5.11 (sole authority) and the Cedar-shape note for the future Phase C maintainer (C-IMPACT-2)
    - _Requirements: R5.2, R5.3, R5.4, R5.5, R5.6, R5.11_
    - _Design: §8.3, §10_
  - [ ] 6.3 Create `mcp_server_node/src/auth/toolScopeGuard.js`
    - `toolScopeGuard(principal, toolName)` → `{ok, status, code, message}`
    - `'ALL'` sentinel → allow (developer-sigv4); unknown scope → 403 `-32001`; tool absent from the set → 403 `-32001` naming the tool
    - _Requirements: R5.7, R5.8_
    - _Design: §8.1_
  - [ ] 6.4 Integrate middleware into `mcp-agentcore-entrypoint.js` and `UnifiedMCPServer.js`
    - Call `authMiddleware(req)` in the `/mcp` handler before `transport.handleRequest`; attach `req.mcpPrincipal`
    - In the `tools/call` handler, call `toolScopeGuard(principal, toolName)` before executing the tool
    - _Requirements: R5.1, R5.7_
    - _Design: §8.1_
  - [ ] 6.5 Read Request_Metadata for CI attribution (R6.6, R6.8, R13.4)
    - In the `tools/call` handler, extract `params._meta.github_attribution` (`run_id`, `repository`, `ref`, `broker_request_id`) — NEVER from JWT claims (there are none for M2M)
    - Map each to an audit field, defaulting absent values to explicit JSON `null` (R6.7)
    - _Requirements: R6.6, R6.7, R6.8, R13.4_
    - _Design: §8.4_
  - [ ] 6.6 Create `mcp_server_node/src/auth/auditLogger.js`
    - Async non-blocking writer using `@aws-sdk/client-cloudwatch-logs`; 2 s `Promise.race` timeout
    - On timeout/failure emit a separate error entry carrying the MCP request id, but never block the caller response
    - Keep the logger PURELY STATELESS — one entry derived only from `(principal, tool, outcome, request_id, ts, request_metadata)` (C-IMPACT-1)
    - _Requirements: R6.1, R6.9_
    - _Design: §9.3, §14 C-IMPACT-1_
  - [ ] 6.7 Emit exactly one audit entry per invocation with the §9.1 JSON Lines schema
    - Fields: `ts`, `request_id`, `caller_sub` (JWT `sub` or literal `developer-sigv4`), `scope`, `tool`, `outcome` (`success`|`authorization_denied`|`execution_error`), plus the four `github_*`/`broker_request_id` fields for CI callers
    - Single-line UTF-8 JSON terminated by `
`; never include raw JWT, tool args, or tool output (R6.4, R6.5)
    - _Requirements: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8_
    - _Design: §9.1_
  - [ ] 6.8 Create the audit CloudWatch log group in the CDK stack
    - `/mdc-mcp-rag-alt/audit`, `removalPolicy: RETAIN`, 365-day retention (R9.3)
    - Attach `logs:CreateLogStream` + `logs:PutLogEvents` on this group to the Runtime task role via a separate managed policy (task role definition unchanged)
    - _Requirements: R6.1, R9.3_
    - _Design: §9.2_
  - [ ] 6.9 Add the `no-tool-set-mutation.js` ESLint rule + CODEOWNERS entry (R5.11)
    - Custom rule forbids `ALLOWED_TOOL_SETS.*.add(`/`.delete(`/direct reassignment outside `allowedToolSets.js`; register in `mcp_server_node/.eslintrc.js`
    - Add CODEOWNERS: `mcp_server_node/src/auth/allowedToolSets.js @NOAA-EMC/mdc-mcp-platform-maintainers`
    - _Requirements: R5.11_
    - _Design: §8.3_
  - [ ]* 6.10 Unit tests for middleware, guard, and audit
    - SigV4 path (no claims header) → `developer-sigv4`; valid CI JWT → CI_READONLY; missing/empty scope → 401; unknown scope → 403; assert `CI_READONLY ∩ MUTATION_TOOL_SET = ∅` (`ci-readonly-excludes-mutation.test.js`); audit shape for all three outcomes
    - _Requirements: R5.4, R5.7, R5.8, R5.9, R5.10, R6.1_
    - _Design: §8.5, §9_
  - [ ]* 6.11 Property P3 — CI mutation rejection
    - **Property 3: CI mutation rejection**
    - Property-based test (≥100 iterations) iterating every `MUTATION_TOOL_SET` member with `mcp/ci-readonly` scope; assert HTTP 403 and no backend side-effect on Neptune/OpenSearch/SDD session-state files
    - Tag: `Feature: mcp-external-access-alternative, Property 3`
    - **Validates: Requirements 5.3, 5.4, 5.7, 5.8**
    - _Design: §13 Property 3_
  - [ ]* 6.12 Property P4 — authorization rejection for unknown scope and missing auth
    - **Property 4: Authorization rejection for unknown scope and missing auth**
    - Property-based test (≥100 iterations): arbitrary malformed/unmapped scope strings on otherwise-valid JWTs → 403; missing Authorization header and missing SigV4 signature → 401; assert the tool is never executed
    - Tag: `Feature: mcp-external-access-alternative, Property 4`
    - **Validates: Requirements 5.9, 5.10**
    - _Design: §13 Property 4_
  - [ ]* 6.13 Property P5 — audit entry well-formedness and no-leak
    - **Property 5: Audit entry well-formedness and no-leak**
    - Property-based test (≥100 iterations) over `(scope, tool, outcome)` tuples; assert exactly one JSON Lines entry per dispatch with non-empty `ts`/`request_id`/`caller_sub`/`tool`/`outcome`, CI `github_*`/`broker_request_id` present as value-or-explicit-null, and no substring equal to the raw JWT, any tool argument, or any tool output
    - Tag: `Feature: mcp-external-access-alternative, Property 5`
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7**
    - _Design: §13 Property 5_
  - [ ]* 6.14 Property P10 — CI attribution completeness via log-join / request-metadata
    - **Property 10: CI attribution completeness via log-join / request-metadata**
    - Property-based test (≥100 iterations) generating arbitrary GitHub attribution values supplied as Request_Metadata; assert the MCP_Server Audit_Log `github_run_id`/`repository`/`ref`/`broker_request_id` match the supplied values, each field is present (value or explicit `null`, never omitted), the `broker_request_id` is joinable to the Token_Broker log line recording the same values, and attribution holds with no dependence on any Pre-Token-Generation trigger or native token claim
    - Tag: `Feature: mcp-external-access-alternative, Property 10`
    - **Validates: Requirements 3.6, 3.7, 3.12, 6.6, 6.7, 6.8, 13.1, 13.2, 13.3, 13.4**
    - _Design: §13 Property 10, §2 AD-3_

- [ ] 7. GitHub Actions composite action `.github/actions/mcp-token`
  - [ ] 7.1 Create `.github/actions/mcp-token/action.yml`
    - Composite action per Design §5.2; inputs `aws-region`, `aws-role-arn`, `token-broker-function`
    - Outputs `bearer-token` (masked), `broker-request-id`, `mcp-metadata-json`, `mcp-url`
    - Steps: `aws-actions/configure-aws-credentials@v4` (OIDC, `audience: sts.amazonaws.com`) → `aws lambda invoke` Token_Broker → parse `access_token` + `request_id` → `::add-mask::` the token → build Request_Metadata JSON (`run_id`, `repository`, `ref`, `broker_request_id`)
    - _Requirements: R3.4, R3.5, R3.7, R3.9, R13.4_
    - _Design: §5.2, §5.3_
  - [ ] 7.2 Create `.github/actions/mcp-token/README.md`
    - Document inputs, the four named outputs (including `broker-request-id` and `mcp-metadata-json` that carry attribution), and required repo permissions (`id-token: write`, `contents: read`)
    - Include a minimal consumer step that places `mcp-metadata-json` into the MCP `tools/call` `_meta.github_attribution` field
    - _Requirements: R3.9_
    - _Design: §5.3, §5.4_
  - [ ] 7.3 Create the example consumer workflow `.github/workflows/ee2-analysis.yml`
    - Triggers on `workflow_run`, calls the composite action, and invokes a representative `mcp/ci-readonly` tool (e.g., `search_documentation`) with Request_Metadata attached; labeled a reference workflow
    - _Requirements: R3.5, R3.7_
    - _Design: §5.3_
  - [ ]* 7.4 Property P8 — no long-lived secrets in the CI path
    - **Property 8: No long-lived secrets in CI path**
    - Property/static-analysis test (≥100 iterations over generated file/env states): assert no AWS access key id, AWS secret access key, or Cognito client secret appears as a source literal in any `.github/actions/mcp-token/**` file and none is read from the repo tree, the `secrets` context, or a pre-existing runner env var (subject to `::add-mask::`)
    - Tag: `Feature: mcp-external-access-alternative, Property 8`
    - **Validates: Requirements 3.4, 3.5, 3.9**
    - _Design: §13 Property 8, §5.4_

- [ ] 8. HPC_CLI_Helper `mdc-mcp-jwt` (Authorization Code + PKCE primary, SRP fallback)
  - [ ] 8.1 Create the package layout under `tools/mdc_mcp_jwt/`
    - `pyproject.toml` with `requires-python = ">=3.9"` and three pinned deps (`requests`, `boto3`, `pyjwt`); console script `mdc-mcp-jwt = mdc_mcp_jwt.cli:main`
    - Create `src/mdc_mcp_jwt/{__init__.py, __main__.py, cli.py, pkce_flow.py, loopback.py, srp_flow.py, cache.py, errors.py}`
    - No `device_flow` module exists and nothing references `/oauth2/device_authorization` (R4.4, R12.2)
    - _Requirements: R4.1, R4.4, R4.15, R12.2_
    - _Design: §6.1, §6.2, §6.3_
  - [ ] 8.2 Implement `cli.py` argument parser and orchestration
    - Flags: `--flow={pkce,srp}` (default `pkce`), `--auth-transport={loopback,manual}` (default `loopback`), `--user-pool-id`, `--client-id`, `--hosted-ui-domain`, `--region`, `--scope` (default `mcp/hpc-user`), `--cache`/`--no-cache` (default `--no-cache`), `--cache-file`, `--username`, `--timeout` (default 30), `--verbose`
    - Read defaults from `~/.mdc-mcp-jwt/config.ini` if present
    - _Requirements: R4.1, R4.2_
    - _Design: §6.4_
  - [ ] 8.3 Implement `pkce_flow.py` — Authorization Code + PKCE (RFC 7636) primary flow
    - Generate `code_verifier` (43–128 unreserved chars from CSPRNG) and `code_challenge = BASE64URL(SHA256(verifier))`, `code_challenge_method=S256`, plus a CSPRNG `state`
    - Build the `/oauth2/authorize` URL against the Hosted UI domain; exchange the code + verifier at `/oauth2/token`; return only the `access_token` (scope `mcp/hpc-user`)
    - Validate returned `state`; a mismatch aborts with a non-zero exit and empty stdout (CSRF guard)
    - _Requirements: R4.2, R4.4, R12.1_
    - _Design: §6.5, §2 AD-1 §2.1_
  - [ ] 8.4 Implement `loopback.py` — one-shot listener + manual-paste transport (RFC 8252)
    - `wait_for_loopback_redirect`: bind a one-shot `http.server` on `127.0.0.1:8765` (SSH-tunnelable), open/print the authorize URL, capture `code`+`state` from the redirect query string
    - `prompt_manual_paste`: print the authorize URL to stderr, read the pasted code from stdin (no inbound connectivity to the login node); both honor the 30 s deadline
    - _Requirements: R4.2_
    - _Design: §6.5, §2 AD-1 §2.1_
  - [ ] 8.5 Implement `srp_flow.py` — `USER_SRP_AUTH` headless fallback
    - `boto3` `initiate_auth(AuthFlow='USER_SRP_AUTH', ...)` + `RespondToAuthChallenge`; requires `--username`; plaintext password never traverses the network
    - Selected only via `--flow=srp`; no browser required
    - _Requirements: R4.3, R4.4, R12.1_
    - _Design: §6.6, §2 AD-1 §2.2_
  - [ ] 8.6 Implement `cache.py` with atomic write + 0600 enforcement
    - Default: no token written to disk (R4.7); `--cache` enables the guarded write
    - Pre-existence verification: regular file, owned by the invoking user, mode 0600 (R4.9); on failure exit non-zero naming path + violation
    - Atomic: `mkstemp` in the same dir → `fchmod 0600` → write → fsync → `os.replace`; on error unlink the temp file and never leave a partial (R4.8, R4.14)
    - _Requirements: R4.7, R4.8, R4.9, R4.14_
    - _Design: §6.8_
  - [ ] 8.7 Enforce stdout/stderr discipline and typed errors in `cli.py`
    - Success: raw token + single `
` to stdout only, exit 0 (R4.5); all diagnostics/prompts to stderr (R4.6)
    - Every non-zero-exit path leaves stdout empty; distinct exit codes for input errors (R4.12), network/DNS/TLS/HTTP failures (R4.13), cache filesystem errors (R4.14), and `state` mismatch
    - _Requirements: R4.5, R4.6, R4.12_
    - _Design: §6.7_
  - [ ] 8.8 Implement the retry/timeout policy (R4.13)
    - At most 3 HTTP attempts per endpoint with exponential backoff (0.5 s, 1.0 s, 2.0 s), total wall-clock ≤ 30 s enforced by a `time.monotonic()` deadline checked before each attempt
    - On exhaustion: non-zero exit, empty stdout, one stderr line naming the failure category and the endpoint contacted
    - _Requirements: R4.13_
    - _Design: §6.9_
  - [ ] 8.9 Build the wheel and publish to the S3 release bucket
    - Upload `mdc_mcp_jwt-1.0.0-py3-none-any.whl` to `s3://mdc-mcp-rag-releases/mdc_mcp_jwt/`; document the install URL in the HPC Runbook (Task 11)
    - _Requirements: R4.15_
    - _Design: §6.1_
  - [ ]* 8.10 Unit tests
    - `test_cli.py` (argparse defaults, exit codes), `test_pkce_flow.py` (verifier/challenge construction, state validation, manual-paste, mocked `/oauth2/token`), `test_cache.py` (atomicity, 0600, ownership rejection)
    - _Requirements: R4.5, R4.6, R4.9, R4.12, R4.13, R4.14_
    - _Design: §6.2_
  - [ ]* 8.11 Property P9 — HPC token issuance via Cognito-native flow + stdout discipline
    - **Property 9: HPC token issuance via Cognito-native flow**
    - Property-based test (≥100 iterations, Hypothesis) over arbitrary flow selections and failure configurations against mocked Cognito: assert every successful token was obtained via `pkce_flow` or `srp_flow` (never a request to `/oauth2/device_authorization`), the token `scope` equals exactly `mcp/hpc-user`, and on every non-zero-exit path stdout is empty (no token material emitted)
    - Tag: `Feature: mcp-external-access-alternative, Property 9`
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.5, 4.6, 4.13, 12.1, 12.2**
    - _Design: §13 Property 9, §2 AD-1_

- [ ] 9. Developer SigV4 backward-compat regression suite (51/51)
  - [ ] 9.1 Create `mcp_server_node/scripts/verify-developer-sigv4.js`
    - Invoke each of the 51 MCP tools in turn via `tools/agentcore-kiro-proxy.py` using the unmodified `.kiro/settings/mcp.json`
    - Record per-tool outcome to a JSON report; exit non-zero if any tool fails
    - _Requirements: R7.1, R7.2, R7.5_
    - _Design: §7.4_
  - [ ] 9.2 Add the byte-integrity check
    - Checksum `tools/agentcore-kiro-proxy.py` and `.kiro/settings/mcp.json` before and after deploy; assert byte-identical
    - _Requirements: R7.3, R7.4_
    - _Design: §1.3_
  - [ ] 9.3 Wire the suite into CI as a required check
    - Run on any `develop_aws` PR that modifies `infrastructure/cdk/` or `mcp_server_node/src/auth/`; block merge on any tool failure
    - _Requirements: R7.5_
    - _Design: §15_

- [ ] 10. Network verification
  - [ ] 10.1 Confirm R8.1 TLS reachability of the MCP_Endpoint
    - From a GitHub-hosted runner and from each reachable HPC login node (Hera, Orion, Hercules, Gaea, Ursa): `curl -vvv` the endpoint and assert a TLS 1.2/1.3 handshake with a publicly-trusted, SAN-matched AWS cert
    - Document any platform where testing was not possible as a follow-up
    - _Requirements: R8.1_
    - _Design: §11.5_
  - [ ] 10.2 Confirm R8.7 VPC isolation of the data stores
    - From an out-of-VPC host: `timeout 30 nc -vz <neptune-endpoint> 8182` and `timeout 30 nc -vz <opensearch-endpoint> 443` — expect timeout/refused within 30 s for each
    - _Requirements: R8.2, R8.3, R8.7_
    - _Design: §11.4_
  - [ ] 10.3 Record all results in `docs/reports/mcp-external-access-alternative-network-verification.md`
    - Include timestamps, platforms tested, and raw curl/nc outputs
    - _Requirements: R8.1, R8.7_
    - _Design: §11_

- [ ] 11. Documentation
  - [ ] 11.1 CI Runbook at `docs/runbooks/mcp-external-access-ci.md`
    - Sections in order (R10.1): Prerequisites, Step-by-step Configuration, Reusable Workflow Snippet, Allowed Tool List, Troubleshooting
    - Reusable snippet copied from `.github/actions/mcp-token/README.md`, runnable verbatim (R10.2)
    - Enumerate all 40 members of the `mcp/ci-readonly` Allowed_Tool_Set by name (R10.3)
    - Document that CI run attribution is recovered by joining the MCP_Server Audit_Log to the Token_Broker log on the Token_Broker request id, and that GitHub attribution is NOT a native token claim (R10.4)
    - Troubleshooting: HTTP 401 and HTTP 403 each with a probable cause + corrective action (R10.5)
    - Add the SigV4-vs-JWT disambiguation section naming the Developer_Principal path (R10.11)
    - _Requirements: R10.1, R10.2, R10.3, R10.4, R10.5, R10.11_
    - _Design: §5, §9.1_
  - [ ] 11.2 HPC Runbook at `docs/runbooks/mcp-external-access-hpc.md`
    - Sections in order (R10.6): Prerequisites, Step-by-step Installation and Session Setup, Reusable Snippet, Allowed Tool List, Troubleshooting
    - Document BOTH the primary Authorization_Code_PKCE_Flow (loopback-redirect and manual-code-paste transports) and the SRP_Password_Flow fallback, with install + invocation steps for each of Hera, Orion, Hercules, Gaea, Ursa and no other platform (R10.7)
    - State JWT lifetime numerically with a unit (e.g., "3600 seconds (1 hour) maximum"), the expired-token procedure (re-run `mdc-mcp-jwt`), and that JWTs SHALL NOT be stored in shared filesystem locations (R10.8)
    - Troubleshooting: HTTP 401 and HTTP 403 each with a probable cause + corrective action (R10.9)
    - Add the SigV4-vs-JWT disambiguation section naming the Developer_Principal path (R10.11)
    - _Requirements: R10.6, R10.7, R10.8, R10.9, R10.11_
    - _Design: §6, §2 AD-1_
  - [ ] 11.3 Steering summary update (R10.10)
    - Extend `.kiro/steering/01-architecture-context.md` with a ≤150-word "External Access Paths" summary, OR create a new steering file, including direct markdown links to both runbooks
    - _Requirements: R10.10_
    - _Design: §12.3_

- [ ] 12. `cdk diff` guardrails + review record + drift detection
  - [ ] 12.1 Add the deployment-pipeline `cdk diff` destructive-change gate
    - Run `cdk diff MdcExternalAccessAlternativeStack > diff.txt`; block deploy if `grep -E '^\[-\] AWS::(Neptune|OpenSearchService|S3|EFS)' diff.txt` matches, requiring explicit override by a steering-05 authorized reviewer
    - _Requirements: R9.5, R9.6_
    - _Design: §12.5_
  - [ ] 12.2 Add the `cdk diff` review-record artifact
    - CI step captures reviewer identity, review timestamp, and SHA256 of the diff content; persist to `s3://mdc-mcp-rag-audit/cdk-reviews/`
    - Pre-deploy check: the review artifact is ≤24 h old and matches the current diff hash
    - _Requirements: R9.7_
    - _Design: §12.5_
  - [ ] 12.3 Nightly drift detector CodeBuild project
    - Compare live Cognito user pool, the federated IAM role, and the AgentCore authorizer config against CDK-synthesized state; on drift emit a CloudWatch metric and open a `cdk-drift` GitHub issue
    - _Requirements: R9.8, R9.9_
    - _Design: §12.6_

- [ ] 13. End-to-end acceptance
  - [ ] 13.1 Deploy `MdcExternalAccessAlternativeStack` to the dev account
    - Run the Task 12 `cdk diff` review, then `cdk deploy`; verify all CloudFormation outputs (Design §12.3) are populated
    - _Requirements: R9.1, R9.5, R9.6_
    - _Design: §12.3_
  - [ ] 13.2 CI end-to-end
    - Trigger the reference `.github/workflows/ee2-analysis.yml`; assert a JWT is obtained, the MCP tool returns 200, and the audit entry appears with `github_run_id`/`broker_request_id` matching the Token_Broker log line (log-join succeeds)
    - _Requirements: R3.5, R3.6, R3.12, R6.6_
    - _Design: §5.3, §2 AD-3_
  - [ ] 13.3 HPC end-to-end (PKCE + SRP)
    - From a test Hera login session: install the wheel, run `mdc-mcp-jwt` via PKCE (loopback and manual-paste) and via `--flow=srp`, invoke `search_documentation` with the token, and verify 200 + an audit entry
    - _Requirements: R4.1, R4.2, R4.3_
    - _Design: §6_
  - [ ] 13.4 Developer SigV4 post-deploy regression
    - Re-run Task 9.1 after deploy; assert 51/51 tools succeed
    - _Requirements: R7.5_
    - _Design: §7.4_
  - [ ] 13.5 Tool-scoping enforcement checks
    - Valid CI JWT calling `mark_as_modified` (Mutation) → 403; valid HPC JWT calling `checkpoint_state` → 200; valid CI JWT calling `search_issues` (HPC-only per AD-5) → 403
    - _Requirements: R5.4, R5.7, R5.8_
    - _Design: §10_
  - [ ] 13.6 R9.10 + R11 compliance sign-off
    - Confirm the synthesized template has zero DynamoDB tables and no PreTokenGeneration config (Task 2.8), all stateful resources RETAIN, CDK tests pass, and the tasks document contains no Path C implementation task
    - Record sign-off in `docs/reports/mcp-external-access-alternative-acceptance.md`
    - _Requirements: R9.4, R9.7, R9.10, R11.4_
    - _Design: §12.4, §12.5_

## Phase B → C Migration (deferred)

_Per R11.4 and R11.5, this section is a placeholder. It contains zero executable subtasks._

Path C introduces an AgentCore Gateway fronting the Runtime with Cedar tool-level policies, interceptor-based audit enrichment, cross-account resource policies, and a stable Gateway URL decoupled from Runtime redeploys. Path C acceptance criteria, CDK constructs, and implementation tasks are **out of scope** for this spec (R11.3, R11.4).

When Phase C work begins, a follow-on spec will be created at:

**`.kiro/specs/mcp-external-access-alternative-gateway/`**

That spec will include: Gateway provisioning, Cedar policy authoring and CDK deployment, Gateway-attached authorizer wiring, Gateway-based tool routing, migration of audit emission from the MCP_Server to Gateway interceptors, and consumer URL cutover from the Runtime-invocation URL to the Gateway URL.

See Design §14 "Path C — Deferred" for the conceptual migration outline and the four Phase B design decisions (C-IMPACT-1 through C-IMPACT-4) — audit emission location, scope enumeration mechanism, MCP endpoint URL distribution, and CI attribution mechanism — that were made to preserve Phase C compatibility.

## Notes

- Sub-tasks marked with `*` are optional (unit and property tests) and can be skipped for a faster MVP; core implementation sub-tasks are never optional.
- Each property test (P1–P10) is implemented as a SINGLE property-based test running ≥100 iterations, tagged `Feature: mcp-external-access-alternative, Property {n}`.
- Every task references specific requirements and design sections for traceability.
- This plan reflects the two replaced decisions: HPC auth is Authorization Code + PKCE (primary) with SRP fallback — no RFC 8628 device flow; CI attribution is the Token_Broker log-join + Request_Metadata — no Pre-Token-Generation trigger and no DynamoDB claims-stash table (Task 2.8 asserts both absences).