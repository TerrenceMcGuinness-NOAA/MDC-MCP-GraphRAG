# Implementation Plan: MCP External Access (Path B)

## Overview

Expose the MDC MCP RAG Server to GitHub Actions CI pipelines and HPC user sessions (Hera, Orion, Hercules, Gaea, Ursa) via a Cognito-backed JWT authorizer attached to the existing AgentCore Runtime. This is Path B per [Design §1](./design.md#1-overview). The developer SigV4 path remains byte-identical (R7). Path C (AgentCore Gateway + Cedar) is explicitly deferred per R11 — this plan contains no Path C implementation tasks.

## Task Counts

| Category | Count |
|----------|-------|
| Executable top-level tasks | 15 (Task 0 through Task 14) |
| Property-test subtasks | 8 (P1–P8) |
| Deferred placeholder groups | 1 ("Phase B → C Migration (deferred)") |

## Dependency Graph

```
Task 0 (pre-implementation gate)
   │
   └─► Task 1 (CDK stack scaffold)
         │
         ├─► Task 2 (Cognito) ─────┐
         │                         │
         ├─► Task 3 (claims stash + PreToken trigger)
         │                         │
         ├─► Task 5 (OIDC IAM role)
         │                         │
         ├─► Task 4 (Token_Broker)  depends on Task 2, Task 3
         │                         │
         ├─► Task 6 (authorizer update) depends on Task 2, Task 3, Task 5
         │                         │
         └─► Task 7 (MCP_Server middleware + audit) depends on Task 2
                                   │
   Task 8 (composite action) depends on Task 4, Task 5
   Task 9 (HPC CLI helper)    depends on Task 2
   Task 10 (dev backward-compat suite) depends on Task 6
   Task 11 (network verification) depends on Task 6
   Task 12 (documentation) depends on Task 8, Task 9
   Task 13 (drift detection + guardrails) depends on Task 6
   Task 14 (end-to-end acceptance) depends on all prior tasks
```

## Tasks

- [ ] 0. Pre-implementation gate — verify public endpoint reachability under VPC mode
  - [ ] 0.1 Run the design-gate `curl` test against the existing Runtime
    - Execute: `curl -sS -o /tmp/mcp-401.json -w '%{http_code}\n' "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A903050880929%3Aruntime%2Fmdc_mcp_rag_server-TMXDllG2Wi/invocations?qualifier=DEFAULT" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -H 'Authorization: Bearer not-a-real-token' -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'`
    - Expected: HTTP 401 response code (not TCP refusal, not 502)
    - _Requirements: R8.5_
    - _Design: §2 AD-2, §11.2_
  - [ ] 0.2 Record verification result in `docs/reports/mcp-external-access-verification.md`
    - Include timestamp, curl output, and the HTTP code observed
    - _Requirements: R8.5_
    - _Design: §11.2_
  - [ ] 0.3 Decision gate: if HTTP 401 observed, proceed to Task 1; otherwise pivot design per §11.3
    - If the test returns a TCP error or 502, STOP and revise the design to use AgentCore Gateway fronting the Runtime (Path C fallback promoted to primary) before any implementation task begins
    - _Requirements: R8.6_
    - _Design: §11.3_

- [ ] 1. CDK stack scaffold
  - [ ] 1.1 Create `infrastructure/cdk/lib/mdc-external-access-stack.ts` skeleton
    - Declare `MdcExternalAccessStackProps` interface with `runtimeArn`, `mcpServerTaskRole`, `allowedGithubSubPatterns`
    - Export empty `MdcExternalAccessStack` class extending `cdk.Stack`
    - _Requirements: R9.1_
    - _Design: §12.1_
  - [ ] 1.2 Wire into `infrastructure/cdk/bin/cdk.ts`
    - Instantiate `MdcExternalAccessStack` with env and `addDependency(serverStack)`
    - Pass `allowedGithubSubPatterns` as `['repo:NOAA-EMC/global-workflow:ref:refs/heads/.*', 'repo:NOAA-EMC/mdc-mcp-rag:ref:refs/heads/.*']`
    - _Requirements: R9.1_
    - _Design: §12.2_
  - [ ] 1.3 Create placeholder test file `infrastructure/cdk/test/mdc-external-access-stack.test.ts`
    - Include failing placeholder tests for each stateful resource type
    - _Requirements: R9.4_
    - _Design: §12.4_
  - [ ] 1.4 Validate `cdk synth MdcExternalAccessStack` succeeds on empty stack
    - No errors, empty `Resources` block acceptable at this stage
    - _Requirements: R9.1_

- [ ] 2. Cognito User Pool + resource server + app clients
  - [ ] 2.1 Define `McpUserPool` with hosted-UI domain `mdc-mcp-external`
    - Self-signup disabled, password policy min-length 14, advanced security enforced, MFA optional/OTP
    - Set `removalPolicy: cdk.RemovalPolicy.RETAIN` per R1.2 and steering file 05
    - _Requirements: R1.1, R1.2, R9.2_
    - _Design: §3.1_
  - [ ] 2.2 Register resource server `McpResourceServer` with identifier `mcp`
    - Declare two scopes: `ci-readonly`, `hpc-user` — ONLY these two
    - _Requirements: R1.3_
    - _Design: §3.2_
  - [ ] 2.3 Define `CiAppClient` (client-credentials only)
    - `generateSecret: true`, allowed scope `mcp/ci-readonly`
    - All other grants disabled
    - Access token validity 60 minutes (R1.7, R3.7)
    - _Requirements: R1.4, R1.7, R3.7_
    - _Design: §3.3_
  - [ ] 2.4 Define `HpcAppClient` (authorization-code for device flow)
    - Public client (no secret), allowed scope `mcp/hpc-user`
    - Client-credentials grant disabled
    - Access token validity 60 minutes, refresh 1 day
    - Enable SRP auth flow as fallback per AD-1
    - _Requirements: R1.5, R1.7, R4.9_
    - _Design: §3.4, AD-1_
  - [ ] 2.5 Store CI_App_Client secret in Secrets Manager
    - Secret name `mdc-mcp-external-access/ci-app-client`
    - `removalPolicy: RETAIN`
    - _Requirements: R9.2_
    - _Design: §3.3, §4.3_
  - [ ] 2.6 CDK unit tests
    - Assert DeletionPolicy: Retain on UserPool and Secret (R9.4)
    - Assert resource server declares exactly the two scopes (R1.3)
    - Assert grant isolation: CiAppClient has only client-credentials; HpcAppClient has no client-credentials (R1.4, R1.5)
    - Assert OIDC discovery document fields include both scopes (R1.6)
    - _Requirements: R1.3, R1.4, R1.5, R1.6, R9.4_
    - _Design: §12.4_
  - [ ] 2.7 Property P7 — JWT issuance invariants (issuance side only)
    - Hypothesis test with mocked Cognito token endpoint asserting every issued token has `scope` in {`mcp/ci-readonly`, `mcp/hpc-user`}, `exp - iat` between 300 and 3600, standard claims present
    - _Requirements: R1.7, R1.8_
    - _Design: §3.5, §13 Property 7_

- [ ] 3. DynamoDB claims stash + Cognito Pre-Token-Generation v2 trigger
  - [ ] 3.1 Define `ClaimsStash` DynamoDB table
    - Partition key `nonce` (string), TTL attribute `ttl`
    - `billingMode: PAY_PER_REQUEST`, AWS-managed encryption
    - `removalPolicy: RETAIN`
    - _Requirements: R9.2_
    - _Design: §4.4_
  - [ ] 3.2 Implement `CognitoClaimsLambda` Python handler
    - File `infrastructure/cdk/lambda/cognito_claims/index.py`
    - Read `nonce` from the incoming PreTokenGeneration v2 event's `request.clientMetadata` or header channel
    - Fetch stashed GitHub claims from DynamoDB by nonce
    - Return `claimsAndScopeOverrideDetails` adding `github_run_id`, `github_repository`, `github_ref`, `github_sha`, `github_actor`
    - _Requirements: R3.6, R6.6_
    - _Design: §3.1, §4.1, AD-3_
  - [ ] 3.3 Wire the trigger to the user pool
    - Attach CognitoClaimsLambda as `preTokenGeneration` V2_0 trigger
    - Grant Cognito `lambda:InvokeFunction` permission
    - Grant the Lambda `dynamodb:GetItem` on `ClaimsStash` only
    - _Requirements: R3.6_
    - _Design: §3.1_
  - [ ] 3.4 Unit tests for claim enrichment
    - Mock DynamoDB client; assert correct claim fields returned for valid nonce
    - Assert empty return for missing nonce (no enrichment, token issued without GitHub claims)
    - _Requirements: R3.6_
    - _Design: §4.1_

- [ ] 4. Token_Broker Lambda
  - [ ] 4.1 Implement handler at `infrastructure/cdk/lambda/token_broker/index.py`
    - Python 3.12 runtime, async via `urllib.request`
    - Extract caller STS identity, parse GitHub claims from event payload
    - Generate nonce, write to `ClaimsStash` with 60s TTL
    - Call Cognito `/oauth2/token` with `grant_type=client_credentials`, `scope=mcp/ci-readonly`
    - Return JWT to caller within 5s SLO
    - _Requirements: R3.2, R3.3_
    - _Design: §4.1_
  - [ ] 4.2 Grant Secrets Manager read policy
    - `secretsmanager:GetSecretValue` on `mdc-mcp-external-access/ci-app-client` ARN only
    - _Requirements: R9.1_
    - _Design: §4.3_
  - [ ] 4.3 Grant DynamoDB write policy
    - `dynamodb:PutItem` on `ClaimsStash` table only
    - _Requirements: R9.1_
    - _Design: §4.4_
  - [ ] 4.4 Configure Lambda function
    - Name `mdc-mcp-token-broker`, reserved concurrency 10
    - 60s timeout, 256 MB memory
    - _Requirements: R3.3_
    - _Design: §4.7_
  - [ ] 4.5 Enforce R3.9 repository/ref allowlist
    - Read `ALLOWED_SUB_PATTERNS_JSON` from Lambda env
    - Compile patterns at cold-start, match against caller's assumed-role `sub`
    - Return HTTP 403 `{"error": "forbidden_repository"}` without calling Cognito on mismatch
    - _Requirements: R3.9_
    - _Design: §4.1, §4.5_
  - [ ] 4.6 Handle upstream Cognito failures per R3.10
    - Catch network/timeout/HTTP errors from Cognito token endpoint
    - Return HTTP 502 `{"error": "upstream_token_issuance_failed", "detail": "..."}` without issuing a JWT
    - _Requirements: R3.10_
    - _Design: §4.5_
  - [ ] 4.7 Emit `slo_breach` warning if elapsed > 5000ms
    - Still return 200 with token (SLO, not hard cutoff)
    - Log JSON line `{"warn":"slo_breach","elapsed_ms":N}` to CloudWatch
    - _Requirements: R3.3_
    - _Design: §4.5, §4.6_
  - [ ] 4.8 Unit tests with mocked Cognito + Secrets Manager + DynamoDB
    - Cover: happy path, allowlist rejection, Cognito timeout, secret read failure, DynamoDB write failure
    - _Requirements: R3.9, R3.10_
    - _Design: §4.5_
  - [ ] 4.9 Integration test against live Cognito
    - Run in dev account: assume federated role, invoke Lambda, decode returned JWT, verify `github_*` claims present
    - _Requirements: R3.6, R3.9_
    - _Design: §4.1_
  - [ ] 4.10 Property P8 — no long-lived secrets
    - Static-analysis test asserting no AWS access key, AWS secret key, or Cognito client secret appears as a literal string in any `.github/actions/mcp-token/**/*` file or composite action output
    - Runtime assertion: runner environment variables expected from the action contain no key named `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or `*_CLIENT_SECRET` set from a literal value
    - _Requirements: R3.4, R3.5, R3.8_
    - _Design: §13 Property 8_

- [ ] 5. GitHub OIDC federated IAM role
  - [ ] 5.1 Create IAM role `mdc-mcp-gh-oidc-ci`
    - Trust policy federating `token.actions.githubusercontent.com`
    - `audience: sts.amazonaws.com`
    - `sub` condition: `StringLike` matching `allowedGithubSubPatterns` from stack props
    - _Requirements: R3.1_
    - _Design: §4.2_
  - [ ] 5.2 Restrict permissions to `lambda:InvokeFunction` on Token_Broker ARN only
    - No other actions, no other resources
    - _Requirements: R3.2_
    - _Design: §4.2_
  - [ ] 5.3 CDK tests
    - Assert trust policy `Principal.Federated` includes `token.actions.githubusercontent.com`
    - Assert `Condition.StringLike.token.actions.githubusercontent.com:sub` equals the allowlist
    - Assert Policy permission is scoped to a single Lambda ARN
    - _Requirements: R3.1, R3.2, R9.4_

- [ ] 6. AgentCore Runtime authorizer update
  - [ ] 6.1 Implement custom resource calling `bedrock-agentcore-control:UpdateAgentRuntime`
    - Use `cr.AwsCustomResource` in `MdcExternalAccessStack`
    - `authorizerConfiguration.customJWTAuthorizer` with `discoveryUrl`, `allowedAudience`, `allowedClients`
    - `physicalResourceId` stable across updates
    - _Requirements: R2.1, R2.5_
    - _Design: §7.2_
  - [ ] 6.2 Populate authorizer config from Task 2 outputs
    - `discoveryUrl` = `https://cognito-idp.us-east-1.amazonaws.com/${userPool.userPoolId}/.well-known/openid-configuration`
    - `allowedAudience` = both `ciAppClient.userPoolClientId` and `hpcAppClient.userPoolClientId`
    - `allowedClients` = same list
    - _Requirements: R2.1, R2.3_
    - _Design: §7.1, §7.2_
  - [ ] 6.3 Grant custom resource IAM policy
    - `bedrock-agentcore-control:UpdateAgentRuntime` and `GetAgentRuntime` on the Runtime ARN only
    - _Requirements: R9.1_
    - _Design: §7.2_
  - [ ] 6.4 Implement authorizer drift detector (CodeBuild nightly)
    - Shell script comparing live authorizer config to `infrastructure/cdk/snapshots/authorizer-config.json`
    - On drift: emit CloudWatch metric + create a GitHub issue tagged `cdk-drift`
    - _Requirements: R2.8_
    - _Design: §7.3_
  - [ ] 6.5 Integration tests — three-path authorization
    - Test A: invalid Bearer → HTTP 401 (R2.5)
    - Test B: valid CI JWT → routed to MCP_Server (R2.9)
    - Test C: SigV4 invocation via proxy → routed to MCP_Server (R2.9, R7.1)
    - _Requirements: R2.5, R2.9, R7.1_
    - _Design: §7.4, §12.5_
  - [ ] 6.6 Property P1 — valid token admission
    - Hypothesis test generating valid JWTs (signed by Cognito test pool) with random claim combinations; assert MCP_Endpoint returns 200 for every token whose scope maps to a tool in the Allowed_Tool_Set
    - _Requirements: R1.8, R2.2, R2.3, R2.4, R5.1, R5.2_
    - _Design: §13 Property 1_
  - [ ] 6.7 Property P2 — invalid token rejection no-leak
    - Hypothesis test generating invalid JWTs (bad signature, expired, missing claims, non-JWT opaque bearers); assert 401 returned and response body contains no claim values or tool-registry names
    - _Requirements: R2.5, R2.6, R2.7_
    - _Design: §13 Property 2_
  - [ ] 6.8 Property P6 — Developer SigV4 path preservation
    - Test invoking `get_server_info`, `search_documentation`, `get_code_context`, `mcp_health_check` via unmodified `agentcore-kiro-proxy.py` after the authorizer is live
    - Assert responses structurally identical to pre-deployment
    - _Requirements: R2.9, R2.10, R7.2, R7.5_
    - _Design: §13 Property 6_

- [ ] 7. MCP_Server authorization middleware + audit logger
  - [ ] 7.1 Create `mcp_server_node/src/auth/authMiddleware.js`
    - Read `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorizer-Claims` header
    - Base64url-decode and JSON-parse the claims
    - Fall through to `developer-sigv4` principal when header absent (SigV4 path)
    - Return reject `{type:'reject', status, message}` on parse error or unrecognized scope
    - _Requirements: R5.1, R5.9, R5.10_
    - _Design: §8.1, §8.2, AD-6_
  - [ ] 7.2 Create `mcp_server_node/src/auth/allowedToolSets.js` — single source of truth
    - Export three Sets: CI_READONLY (40 tools per Design §10.1), HPC_USER (48 tools per §10.2), MUTATION_TOOL_SET (6 tools)
    - DEVELOPER_SIGV4 sentinel `'ALL'` bypasses the filter
    - Header comment citing R5.11 as the rationale for single-file authority
    - _Requirements: R5.2, R5.3, R5.4, R5.5, R5.6, R5.11_
    - _Design: §8.3, §10_
  - [ ] 7.3 Create `mcp_server_node/src/auth/toolScopeGuard.js`
    - `toolScopeGuard(principal, toolName)` returns `{ok, status, code, message}`
    - Unknown scope → 403 with `code: -32001`
    - Tool absent from Allowed_Tool_Set → 403 with message identifying the tool
    - _Requirements: R5.7, R5.8_
    - _Design: §8.1_
  - [ ] 7.4 Integrate middleware into `mcp-agentcore-entrypoint.js` and `UnifiedMCPServer.js`
    - Call `authMiddleware(req)` in the `/mcp` handler before `transport.handleRequest`
    - Attach `req.mcpPrincipal` for the dispatch layer
    - In the `tools/call` handler, invoke `toolScopeGuard(principal, toolName)` before executing the tool
    - _Requirements: R5.1, R5.7_
    - _Design: §8.1_
  - [ ] 7.5 Create `mcp_server_node/src/auth/auditLogger.js`
    - Async non-blocking writer using `@aws-sdk/client-cloudwatch-logs`
    - Enforce 2s timeout via `Promise.race`
    - Emit error log on timeout but do not block the response
    - _Requirements: R6.1, R6.8_
    - _Design: §9.3_
  - [ ] 7.6 Emit exactly-one audit entry per invocation
    - Call `emitAuditEntry` once per dispatched tool invocation
    - Schema matches Design §9.1: `ts`, `request_id`, `caller_sub`, `scope`, `tool`, `outcome`, plus `github_*` fields for CI callers
    - `caller_sub = 'developer-sigv4'` for SigV4 path
    - CI `github_*` fields explicitly `null` when JWT lacks the claim (per R6.7)
    - _Requirements: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7_
    - _Design: §9.1_
  - [ ] 7.7 Create CloudWatch log group `/mdc-mcp-rag/audit` in CDK stack
    - Retention 365 days
    - Grant `mdc-mcp-rag-ecs-task-role` `logs:CreateLogStream` + `logs:PutLogEvents` on this group only (attached as a separate managed policy; task role itself unchanged)
    - _Requirements: R6.1_
    - _Design: §9.2_
  - [ ] 7.8 Add ESLint rule `no-tool-set-mutation.js`
    - Custom rule: forbid `ALLOWED_TOOL_SETS.*.add(` / `.delete(` / direct assignment outside `allowedToolSets.js`
    - Add rule to `mcp_server_node/.eslintrc.js`
    - _Requirements: R5.11_
    - _Design: §8.3_
  - [ ] 7.9 Add CODEOWNERS entry
    - `mcp_server_node/src/auth/allowedToolSets.js @NOAA-EMC/mdc-mcp-platform-maintainers`
    - _Requirements: R5.11_
    - _Design: §8.3_
  - [ ] 7.10 Unit tests
    - Cover: SigV4 path (no claims header) → DEVELOPER_SIGV4 principal; valid CI JWT → CI_READONLY principal; unknown scope → 403; Mutation tool with CI scope → 403; audit entry shape for all three outcomes
    - _Requirements: R5.7, R5.8, R5.9, R5.10, R6.1–R6.7_
    - _Design: §8.4, §9_
  - [ ] 7.11 Property P3 — CI mutation rejection
    - Hypothesis test iterating every `MUTATION_TOOL_SET` member with `mcp/ci-readonly` scope; assert 403 returned and no side effects on Neptune/OpenSearch/SDD state files
    - _Requirements: R5.3, R5.4, R5.7, R5.8_
    - _Design: §13 Property 3_
  - [ ] 7.12 Property P4 — unknown scope / missing auth rejection
    - Hypothesis test: arbitrary malformed scope strings with valid signatures → 403; missing Authorization header and missing SigV4 signature → 401
    - _Requirements: R5.9, R5.10_
    - _Design: §13 Property 4_
  - [ ] 7.13 Property P5 — audit well-formedness + no-leak
    - Hypothesis test generating `(scope, tool, outcome)` tuples; assert exactly one JSONL line per invocation with the required fields, and no substring equal to the raw JWT, any tool argument value, or any tool output value
    - _Requirements: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7_
    - _Design: §13 Property 5_

- [ ] 8. GitHub Actions composite action
  - [ ] 8.1 Create `.github/actions/mcp-token/action.yml`
    - Composite action per Design §5.2
    - Inputs: `aws-region`, `aws-role-arn`, `token-broker-function`
    - Outputs: `bearer-token` (masked), `expires-in`, `mcp-url`
    - Steps: configure-aws-credentials@v4 (OIDC) → aws lambda invoke → parse + mask + set-output
    - _Requirements: R3.4, R3.8_
    - _Design: §5.2_
  - [ ] 8.2 Create `.github/actions/mcp-token/README.md`
    - Document inputs, outputs, and a minimal consumer example
    - Include required repo permissions (`id-token: write`, `contents: read`)
    - _Requirements: R3.8_
    - _Design: §5_
  - [ ] 8.3 Create example consumer at `.github/workflows/ee2-analysis.yml`
    - Triggers on `workflow_run`, calls the composite action, calls a representative MCP tool (e.g., `search_documentation`)
    - Labeled clearly as a reference workflow (not production yet)
    - _Requirements: R3.8_
    - _Design: §5.3_
  - [ ] 8.4 End-to-end smoke test
    - Run the reference workflow against the dev stack
    - Assert: non-empty JWT obtained, MCP_Endpoint returns 200, audit entry appears in `/mdc-mcp-rag/audit` with matching `run_id`
    - _Requirements: R3.4, R3.5, R3.6_
    - _Design: §5.3_

- [ ] 9. HPC_CLI_Helper `mdc-mcp-jwt`
  - [ ] 9.1 Package layout under `tools/mdc_mcp_jwt/`
    - Create pyproject.toml with `requires-python = ">=3.9"`, two pinned deps (`requests`, `pyjwt`)
    - Create `src/mdc_mcp_jwt/{__init__.py, __main__.py, cli.py, device_flow.py, password_flow.py, cache.py, errors.py}`
    - Console script `mdc-mcp-jwt = mdc_mcp_jwt.cli:main`
    - _Requirements: R4.1, R4.13_
    - _Design: §6.2, §6.3_
  - [ ] 9.2 Implement `cli.py` argument parser
    - Flags: `--flow={device,password}`, `--user-pool-id`, `--client-id`, `--region`, `--cache`, `--cache-file`, `--username`, `--timeout`, `--verbose`
    - Read defaults from `~/.mdc-mcp-jwt/config.ini` if present
    - `--flow` default: `device`
    - _Requirements: R4.1_
    - _Design: §6.4_
  - [ ] 9.3 Implement `device_flow.py` per RFC 8628
    - Request device code from Cognito `/oauth2/device_authorization`
    - Print verification URI and user code to stderr
    - Poll `/oauth2/token` at interval with `deadline = time.monotonic() + 30s`
    - Handle `authorization_pending`, `slow_down` error codes per the RFC
    - Cap retries at 3 per R4.11
    - _Requirements: R4.2, R4.11_
    - _Design: §6.5_
  - [ ] 9.4 Implement `password_flow.py` as SRP fallback
    - Use `boto3.client('cognito-idp').initiate_auth` with `USER_SRP_AUTH`
    - Invoked only when `--flow=password` and `--username` provided
    - _Requirements: R4.2_
    - _Design: §6.6, AD-1_
  - [ ] 9.5 Implement `cache.py` with atomic write + 0600 enforcement
    - Pre-write verification: regular file, owned by user, mode 0600 (R4.7)
    - Atomic: write to `tempfile.mkstemp` in same directory, fsync, `os.replace`
    - On failure: unlink temp file, raise `CacheFilesystemError` (R4.12)
    - _Requirements: R4.5, R4.6, R4.7, R4.12_
    - _Design: §6.8_
  - [ ] 9.6 Enforce stdout/stderr discipline in `cli.py`
    - Success path: raw token + `\n` to stdout only, exit 0
    - All diagnostics and errors to stderr
    - On error: non-zero exit, empty stdout (R4.10, R4.11, R4.12)
    - _Requirements: R4.3, R4.4, R4.10, R4.11, R4.12_
    - _Design: §6.7_
  - [ ] 9.7 Retry/timeout policy
    - At most 3 HTTP attempts per endpoint with exponential backoff (0.5s, 1.0s, 2.0s)
    - Total wall-clock budget 30s enforced via `time.monotonic()` deadline
    - _Requirements: R4.11_
    - _Design: §6.9_
  - [ ] 9.8 Build wheel and publish to S3 release bucket
    - Create `s3://mdc-mcp-rag-releases/mdc_mcp_jwt/` (separate from migration bucket)
    - Upload `mdc_mcp_jwt-1.0.0-py3-none-any.whl`
    - Document install URL in HPC Runbook (Task 12)
    - _Requirements: R4.1_
    - _Design: §6.1_
  - [ ] 9.9 Unit tests
    - `test_cli.py`: argparse defaults, help output, error exit codes
    - `test_device_flow.py`: mocked Cognito endpoint for each state (pending, slow_down, success, expired)
    - `test_cache.py`: atomicity, 0600 enforcement, ownership rejection
    - `test_stdout_discipline.py`: Hypothesis test — for every random configuration and failure mode, stdout is empty unless exit code 0
    - _Requirements: R4.3, R4.4, R4.5, R4.6, R4.7, R4.10, R4.11, R4.12_
    - _Design: §6.2_
  - [ ] 9.10 Smoke test on Hera (primary) + one other platform
    - Install wheel in user venv, run device flow, obtain JWT, invoke representative MCP tool
    - Platforms to attempt: Hera first; then Orion, Hercules, Gaea, or Ursa based on access availability
    - Document any platform where the test could not be executed as a follow-up in docs/reports/
    - _Requirements: R4.13_
    - _Design: §6.1_
  - [ ] 9.11 Property P7 — JWT issuance invariants (HPC side)
    - Hypothesis test: for every JWT obtained by the HPC CLI (mocked Cognito), `scope == 'mcp/hpc-user'`, `300 ≤ exp - iat ≤ 3600`, `sub` non-empty
    - _Requirements: R4.8, R4.9_
    - _Design: §13 Property 7_

- [ ] 10. Developer backward-compat regression suite
  - [ ] 10.1 Create test script `mcp_server_node/scripts/verify-developer-sigv4.js`
    - Invoke each of the 51 MCP tools in turn via `tools/agentcore-kiro-proxy.py`
    - Use unmodified `.kiro/settings/mcp.json` (byte-compare to pre-feature state)
    - Record per-tool outcome (success/failure/timeout) to JSON report
    - Exit non-zero if any tool fails
    - _Requirements: R7.1, R7.2, R7.3, R7.4, R7.5_
    - _Design: §12.4_
  - [ ] 10.2 Wire into CI pipeline
    - Run the script as a required check on any `develop_aws` branch PR that modifies files under `infrastructure/cdk/` or `mcp_server_node/src/auth/`
    - Block merge on any tool failure
    - _Requirements: R7.5_
    - _Design: §12.4_
  - [ ] 10.3 Byte-integrity check
    - Checksum `tools/agentcore-kiro-proxy.py` and `.kiro/settings/mcp.json` before and after deploy; assert identical
    - _Requirements: R7.3, R7.4_

- [ ] 11. Network verification
  - [ ] 11.1 Confirm R8.1 TLS reachability
    - From a GitHub-hosted runner: `curl -vvv https://bedrock-agentcore.us-east-1.amazonaws.com/...` — assert TLS 1.2+ handshake, AWS-signed cert
    - From each HPC platform login node (Hera, Orion, Hercules, Gaea, Ursa): same test
    - Document platforms where testing was not possible as follow-up items
    - _Requirements: R8.1_
    - _Design: §11.5_
  - [ ] 11.2 Confirm R8.7 VPC isolation
    - From an out-of-VPC host: `timeout 30 nc -vz <neptune-endpoint> 8182` — expect timeout
    - Same for OpenSearch: `timeout 30 nc -vz <opensearch-endpoint> 443`
    - _Requirements: R8.2, R8.3, R8.7_
    - _Design: §11.4_
  - [ ] 11.3 Record all results
    - File: `docs/reports/mcp-external-access-network-verification.md`
    - Include: timestamps, platforms tested, curl/nc outputs
    - _Requirements: R8.1, R8.7_
    - _Design: §11_

- [ ] 12. Documentation
  - [ ] 12.1 CI Runbook at `docs/runbooks/mcp-external-access-ci.md`
    - Required sections in order (R10.1): Prerequisites, Step-by-step Configuration, Reusable Workflow Snippet, Allowed Tool List, Troubleshooting
    - Reusable snippet copied from `.github/actions/mcp-token/README.md`, runnable verbatim
    - Enumerate all 40 members of `mcp/ci-readonly` Allowed_Tool_Set (R10.3)
    - Troubleshooting: HTTP 401 (causes: expired token, wrong audience) and HTTP 403 (causes: tool not in Allowed_Tool_Set, unknown scope) each with probable cause + corrective action
    - SigV4-vs-JWT disambiguation section per R10.10
    - _Requirements: R10.1, R10.2, R10.3, R10.4, R10.10_
    - _Design: §5.3_
  - [ ] 12.2 HPC Runbook at `docs/runbooks/mcp-external-access-hpc.md`
    - Required sections in order (R10.5): Prerequisites, Step-by-step Installation and Session Setup, Reusable Snippet, Allowed Tool List, Troubleshooting
    - Per-platform install steps for Hera, Orion, Hercules, Gaea, Ursa (R10.6)
    - JWT token lifetime stated numerically (R10.7): "3600 seconds (1 hour) maximum"
    - Expired-token procedure: re-run `mdc-mcp-jwt`
    - Explicit statement that JWTs SHALL NOT be stored in shared filesystem locations
    - SigV4-vs-JWT disambiguation section per R10.10
    - _Requirements: R10.5, R10.6, R10.7, R10.8, R10.10_
    - _Design: §6_
  - [ ] 12.3 Steering file update per R10.9
    - Either extend `.kiro/steering/01-architecture-context.md` with a ≤150-word "External Access Paths" paragraph, OR create new `.kiro/steering/06-external-access.md`
    - Include direct markdown links to both runbooks
    - _Requirements: R10.9_
    - _Design: §12.3_
  - [ ] 12.4 Update `.kiro/steering/04-phase48-progress.md`
    - Mark Phase mcp-external-access as in-progress, reference this spec
    - _Requirements: —_
    - _Design: —_

- [ ] 13. Drift detection + deployment guardrails
  - [ ] 13.1 Nightly drift detector CodeBuild project
    - Compares live Cognito user pool, IAM role, and AgentCore authorizer config against expected CDK-synthesized state
    - On drift: CloudWatch metric + GitHub issue tagged `cdk-drift`
    - _Requirements: R9.8, R9.9_
    - _Design: §12.6_
  - [ ] 13.2 Deployment pipeline `cdk diff` gate
    - Shell step in deploy workflow: `cdk diff MdcExternalAccessStack > diff.txt`
    - Block deploy if `grep -E '^\[-\] AWS::(Neptune|OpenSearchService|S3|EFS)' diff.txt` matches
    - _Requirements: R9.5, R9.6_
    - _Design: §12.5_
  - [ ] 13.3 Review record artifact
    - CI step captures: reviewer identity (GitHub login), review timestamp, SHA256 of diff content
    - Persist to S3 `s3://mdc-mcp-rag-audit/cdk-reviews/`
    - Pre-deploy check: review artifact ≤24h old and matches current diff hash
    - _Requirements: R9.7_
    - _Design: §12.5_

- [ ] 14. End-to-end acceptance
  - [ ] 14.1 Deploy `MdcExternalAccessStack` to dev account
    - Run `cdk diff` review (Task 13)
    - Run `cdk deploy MdcExternalAccessStack`
    - Verify all CloudFormation outputs are populated (Design §12.3)
    - _Requirements: R9.1, R9.5, R9.6_
    - _Design: §12.3_
  - [ ] 14.2 CI end-to-end
    - Trigger the reference `.github/workflows/ee2-analysis.yml` workflow
    - Assert: JWT obtained, MCP tool returns 200, audit entry in CloudWatch with matching `github_run_id`
    - _Requirements: R3.5, R3.6, R6.6_
    - _Design: §5.3_
  - [ ] 14.3 HPC end-to-end
    - From a test Hera login session: install wheel, run `mdc-mcp-jwt`, invoke `search_documentation` via curl, verify 200 + audit entry
    - _Requirements: R4.1, R4.3_
    - _Design: §6_
  - [ ] 14.4 Developer SigV4 post-deploy regression
    - Re-run Task 10.1 after the deploy; assert 51/51 tools succeed
    - _Requirements: R7.5_
    - _Design: §12.4_
  - [ ] 14.5 Tool scoping enforcement test
    - Valid CI JWT attempting `mark_as_modified` (in Mutation_Tool_Set) → 403 observed
    - Valid HPC JWT attempting `checkpoint_state` → 200 (allowed per HPC set)
    - Valid CI JWT attempting `search_issues` → 403 (excluded from CI per AD-5)
    - _Requirements: R5.4, R5.7, R5.8_
    - _Design: §10_
  - [ ] 14.6 Sign-off per steering file 05 checklist
    - Verify: all stateful resources RETAIN, CDK tests pass, `cdk diff` reviewed, two-step pattern not needed (no existing CDK resource migrations)
    - Record sign-off in `docs/reports/mcp-external-access-acceptance.md`
    - _Requirements: R9.4, R9.7_
    - _Design: §12.4, §12.5_

## Phase B → C Migration (deferred)

_Per R11.4 and R11.5, this section is a placeholder. No executable subtasks._

Path C introduces AgentCore Gateway fronting the Runtime with Cedar tool-level policies and interceptor-based audit enrichment. Path C acceptance criteria, CDK constructs, and implementation tasks are out of scope for this spec.

When Phase C work begins, a follow-on spec will be created at:

**`.kiro/specs/mcp-external-access-gateway/`**

That spec will include: Gateway provisioning, Cedar policy authoring and CDK deployment, Gateway-attached authorizer wiring, Gateway-based tool routing, migration of audit emission from the MCP_Server to Gateway interceptors, and consumer URL cutover from Runtime-invocation URL to Gateway URL.

See Design §14 "Path C — Deferred" for the conceptual migration outline and the four Phase B design decisions (C-IMPACT-1 through C-IMPACT-4) that were made with Phase C compatibility in mind.
