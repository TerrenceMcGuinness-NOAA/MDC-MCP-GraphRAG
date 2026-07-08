# Implementation Tasks

## Task Group 1: Network Verification Gate (R8.5, R8.6)

> Implementation MUST NOT proceed beyond this group until the verification result is recorded.

- [ ] **Task 1.1** Run the AD-2 confirmatory curl test from a host outside VPC `vpc-055f30ffa3d661e6b` against the AgentCore MCP endpoint with a bogus Bearer token. Record the HTTP status code (expected: 401), timestamp, and source IP in `.kiro/specs/mcp-external-access-revised/design.md` §11.2.
  - **Traces to:** R8.5
  - **Depends on:** none
- [ ] **Task 1.2** Run the Neptune/OpenSearch isolation test (`nc -vz` with 30 s timeout) from the same external host. Record connection-refused/timeout results in the design §11.4 verification artifact.
  - **Traces to:** R8.7
  - **Depends on:** none
- [ ] **Task 1.3** If Task 1.1 returns a TCP error (not HTTP 401), document the Gateway fallback path per R8.6 in the design before proceeding. Otherwise mark the verification as PASS and unblock subsequent groups.
  - **Traces to:** R8.6
  - **Depends on:** Task 1.1

## Task Group 2: CDK Stack — Cognito Identity Layer (R1, R9)

- [ ] **Task 2.1** Create `infrastructure/cdk/lib/mdc-external-access-alternative-stack.ts` with the Cognito user pool (`removalPolicy: RETAIN`), resource server (scopes `mcp/ci-readonly`, `mcp/hpc-user`), and Hosted UI domain per design §3.1–§3.3.
  - **Traces to:** R1.1, R1.2, R1.3, R1.6, R9.2
  - **Depends on:** Task 1.3 (verification PASS)
- [ ] **Task 2.2** Add the CI_App_Client (client-credentials only, generated secret in Secrets Manager with `RETAIN`) per design §3.4.
  - **Traces to:** R1.4, R9.3
  - **Depends on:** Task 2.1
- [ ] **Task 2.3** Add the HPC_App_Client (authorization-code + PKCE primary, `USER_SRP_AUTH` fallback, no client-credentials, no ROPC) per design §3.5.
  - **Traces to:** R1.5
  - **Depends on:** Task 2.1
- [ ] **Task 2.4** Configure access token lifetime (900 s) on both clients. Verify `300 <= lifetime <= 3600`.
  - **Traces to:** R1.8, R3.8, R4.11
  - **Depends on:** Task 2.2, Task 2.3
- [ ] **Task 2.5** Verify the user pool does NOT declare a `PreTokenGeneration` or `PreTokenGenerationConfig` Lambda trigger. Confirm no DynamoDB table is provisioned by this stack.
  - **Traces to:** R9.10, R13.1, R13.2
  - **Depends on:** Task 2.1

## Task Group 3: CDK Stack — Token_Broker Lambda and GitHub OIDC Role (R3, R9)

- [ ] **Task 3.1** Create the federated IAM role with GitHub OIDC trust policy, `sub` allowlist from CDK context, per design §4.2.
  - **Traces to:** R3.1
  - **Depends on:** Task 2.2 (needs CI_App_Client ID for Lambda env)
- [ ] **Task 3.2** Implement the Token_Broker Lambda handler (`infrastructure/cdk/lambda/token_broker/index.py`) per design §4.1 — sub allowlist check, Secrets Manager read, Cognito client-credentials call, structured attribution log, return token + request_id.
  - **Traces to:** R3.2, R3.3, R3.6, R3.10, R3.11, R13.3
  - **Depends on:** Task 3.1
- [ ] **Task 3.3** Wire the Lambda in CDK: grant invoke to the OIDC role only, grant Secrets Manager read on the CI client secret ARN, set reserved concurrency 10, configure CloudWatch log group (`/mdc-mcp-rag-alt/token-broker`, `RETAIN`, 90-day retention).
  - **Traces to:** R3.2, R9.3
  - **Depends on:** Task 3.2
- [ ] **Task 3.4** Write unit tests for the Token_Broker: sub-mismatch → 403/no Cognito call; Cognito failure → 502; success → token + request_id in response + attribution log line without token; SLO timing.
  - **Traces to:** R3.3, R3.6, R3.10, R3.11
  - **Depends on:** Task 3.2

## Task Group 4: CDK Stack — AgentCore Runtime JWT Authorizer (R2, R9)

- [ ] **Task 4.1** Add the `AwsCustomResource` that calls `UpdateAgentRuntime` to attach the Cognito JWT authorizer (discovery URL, allowed audiences/clients) per design §7.2.
  - **Traces to:** R2.1, R2.8
  - **Depends on:** Task 2.1, Task 2.2, Task 2.3
- [ ] **Task 4.2** Verify SigV4 coexistence: after deploying the authorizer, confirm the Developer_Principal SigV4 path still works (invoke one tool via `agentcore-kiro-proxy.py`).
  - **Traces to:** R2.9, R7.2
  - **Depends on:** Task 4.1
- [ ] **Task 4.3** Add the nightly drift-detector script (`infrastructure/cdk/snapshots/authorizer-config.json` + comparison) per design §7.3.
  - **Traces to:** R2.8, R9.9
  - **Depends on:** Task 4.1

## Task Group 5: CDK Tests — Data Safety Assertions (R9)

- [ ] **Task 5.1** Create `infrastructure/cdk/test/mdc-external-access-alternative-stack.test.ts` with DeletionPolicy:Retain assertions for Cognito user pool, Secrets Manager secret, CloudWatch log groups per design §12.4.
  - **Traces to:** R9.4
  - **Depends on:** Task 2.1, Task 3.3
- [ ] **Task 5.2** Assert `AWS::DynamoDB::Table` count == 0 and no `PreTokenGeneration` config on the user pool.
  - **Traces to:** R9.10
  - **Depends on:** Task 5.1
- [ ] **Task 5.3** Assert no Neptune/OpenSearch/S3/EFS resource types present in this stack.
  - **Traces to:** R9.5
  - **Depends on:** Task 5.1
- [ ] **Task 5.4** Assert CI client secret readable only by Token_Broker execution role.
  - **Traces to:** R3.2, R9.3
  - **Depends on:** Task 5.1

## Task Group 6: CDK Stack Registration and `cdk diff` Guardrails (R9)

- [ ] **Task 6.1** Register `MdcExternalAccessAlternativeStack` in `bin/cdk.ts` with `addDependency(serverStack)` per design §12.2.
  - **Traces to:** R9.1
  - **Depends on:** Task 2.1
- [ ] **Task 6.2** Add the `cdk diff` destructive-change guardrail script per design §12.5.
  - **Traces to:** R9.6, R9.7
  - **Depends on:** Task 6.1

## Task Group 7: MCP_Server Authorization Middleware (R5, R7)

- [ ] **Task 7.1** Implement `mcp_server_node/src/auth/authMiddleware.js` — detect SigV4 (no claims header → `developer-sigv4`) vs JWT (decode base64url claims header, extract scope) per design §8.2.
  - **Traces to:** R5.1, R5.9, R5.10, R7.2
  - **Depends on:** Task 4.1 (authorizer must be live to produce the claims header)
- [ ] **Task 7.2** Implement `mcp_server_node/src/auth/allowedToolSets.js` — the single-source-of-truth tool-to-scope map with explicit `CI_READONLY` (40), `HPC_USER` (48), `developer-sigv4: ALL`, and `MUTATION_TOOL_SET` per design §8.3/§10.
  - **Traces to:** R5.2, R5.3, R5.4, R5.5, R5.6, R5.11
  - **Depends on:** none (pure data)
- [ ] **Task 7.3** Implement `mcp_server_node/src/auth/toolScopeGuard.js` — enforce Allowed_Tool_Set before tool dispatch; return 403/-32001 on denial per design §8.1.
  - **Traces to:** R5.7, R5.8
  - **Depends on:** Task 7.2
- [ ] **Task 7.4** Wire `authMiddleware` and `toolScopeGuard` into `mcp-agentcore-entrypoint.js` per design §8.1.
  - **Traces to:** R5.1
  - **Depends on:** Task 7.1, Task 7.3
- [ ] **Task 7.5** Write unit tests: developer-sigv4 path grants all 51; ci-readonly denies mutation tools (P3); hpc-user grants expected 48; unknown scope → 403 (P4); missing scope → 401.
  - **Traces to:** R5.3–R5.10, P3, P4
  - **Depends on:** Task 7.4

## Task Group 8: MCP_Server Audit Logger (R6)

- [ ] **Task 8.1** Implement `mcp_server_node/src/auth/auditLogger.js` — emit exactly one JSON-Lines entry per tool invocation to CloudWatch, with 2 s non-blocking timeout per design §9.3.
  - **Traces to:** R6.1, R6.4, R6.9
  - **Depends on:** Task 7.4 (needs principal context)
- [ ] **Task 8.2** Implement the audit entry schema: `caller_sub`, `tool`, `ts`, `scope`, `request_id`, `outcome`, and the four GitHub attribution fields (string or explicit null) per design §9.1.
  - **Traces to:** R6.2, R6.3, R6.5, R6.6, R6.7, R6.8
  - **Depends on:** Task 8.1
- [ ] **Task 8.3** Wire Request_Metadata extraction from `params._meta.github_attribution` into the audit entry per design §8.4.
  - **Traces to:** R6.6, R6.8, R13.4
  - **Depends on:** Task 8.2
- [ ] **Task 8.4** Write unit tests: well-formed entry (P5); no raw JWT/args/output in entry; 2 s timeout behavior; explicit null for missing CI fields (R6.7).
  - **Traces to:** R6.5, R6.7, R6.9, P5
  - **Depends on:** Task 8.3

## Task Group 9: GitHub Actions Composite Action (R3)

- [ ] **Task 9.1** Create `.github/actions/mcp-token/action.yml` with inputs, outputs, OIDC credential configuration, Token_Broker invocation, `::add-mask::`, and Request_Metadata construction per design §5.2.
  - **Traces to:** R3.4, R3.5, R3.7, R3.9, P8
  - **Depends on:** Task 3.3 (Lambda deployed)
- [ ] **Task 9.2** Create `.github/actions/mcp-token/README.md` documenting usage, inputs, outputs, and how consumers attach Request_Metadata to MCP calls.
  - **Traces to:** R3.9
  - **Depends on:** Task 9.1
- [ ] **Task 9.3** Verify end-to-end: run the composite action in a test workflow, confirm token returned, `bearer-token` and `broker-request-id` outputs populated, Request_Metadata correctly formed. Confirm no long-lived secrets used (P8).
  - **Traces to:** R3.3, R3.4, R3.7, P8
  - **Depends on:** Task 9.1, Task 4.1

## Task Group 10: HPC_CLI_Helper (R4, R12)

- [ ] **Task 10.1** Create `tools/mdc_mcp_jwt/` package skeleton: `pyproject.toml`, `src/mdc_mcp_jwt/__init__.py`, `__main__.py`, `cli.py`, `errors.py` per design §6.2–§6.3.
  - **Traces to:** R4.15
  - **Depends on:** Task 2.3 (needs HPC_App_Client ID)
- [ ] **Task 10.2** Implement the PKCE flow (`pkce_flow.py`, `loopback.py`) — code_verifier/challenge generation, `/oauth2/authorize` URL build, loopback listener + manual paste transport, `/oauth2/token` exchange per design §6.5.
  - **Traces to:** R4.2, R4.4, R12.1, R12.2
  - **Depends on:** Task 10.1
- [ ] **Task 10.3** Implement the SRP fallback (`srp_flow.py`) — `USER_SRP_AUTH` via boto3 per design §6.6.
  - **Traces to:** R4.3, R12.1
  - **Depends on:** Task 10.1
- [ ] **Task 10.4** Implement stdout/stderr discipline in `cli.py`: raw token to stdout on success (exit 0), all diagnostics to stderr, empty stdout on every non-zero exit per design §6.7.
  - **Traces to:** R4.5, R4.6, R4.12, P9
  - **Depends on:** Task 10.2, Task 10.3
- [ ] **Task 10.5** Implement atomic cache write (`cache.py`) with ownership/mode pre-check per design §6.8.
  - **Traces to:** R4.7, R4.8, R4.9, R4.14
  - **Depends on:** Task 10.4
- [ ] **Task 10.6** Implement retry/timeout policy (≤3 attempts, ≤30 s total) per design §6.9.
  - **Traces to:** R4.13
  - **Depends on:** Task 10.2
- [ ] **Task 10.7** Write tests: stdout discipline property (P9), cache atomicity/permissions property, error exit codes, PKCE state validation, no `/oauth2/device_authorization` in any code path.
  - **Traces to:** R4.4, R4.12–R4.14, R12.2, P9
  - **Depends on:** Task 10.4, Task 10.5, Task 10.6

## Task Group 11: Developer Regression Verification (R7)

- [ ] **Task 11.1** Verify `tools/agentcore-kiro-proxy.py` is byte-identical to its pre-feature state (hash comparison).
  - **Traces to:** R7.3
  - **Depends on:** Task 7.4
- [ ] **Task 11.2** Verify `.kiro/settings/mcp.json` `agentcore-mcp-rag` entry is byte-identical to its pre-feature state.
  - **Traces to:** R7.4
  - **Depends on:** Task 7.4
- [ ] **Task 11.3** Run the 51-tool SigV4 regression suite via the unmodified proxy; confirm 51/51 success (P6).
  - **Traces to:** R7.5, P6
  - **Depends on:** Task 11.1, Task 11.2, Task 8.3 (audit logger must not break SigV4 path)

## Task Group 12: Documentation — Runbooks (R10)

- [ ] **Task 12.1** Create `docs/runbooks/mcp-external-access-ci.md` with sections: Prerequisites, Step-by-step Configuration, Reusable Workflow Snippet, Allowed Tool List (all 40 `mcp/ci-readonly` tools by name), Troubleshooting (401/403), SigV4-vs-JWT disambiguation, and the log-join attribution explanation.
  - **Traces to:** R10.1, R10.2, R10.3, R10.4, R10.5, R10.11
  - **Depends on:** Task 9.1 (composite action finalized), Task 7.2 (tool list finalized)
- [ ] **Task 12.2** Create `docs/runbooks/mcp-external-access-hpc.md` with sections: Prerequisites, Installation & Session Setup (per-platform for Hera/Orion/Hercules/Gaea/Ursa), Reusable Snippet, Allowed Tool List (48 `mcp/hpc-user` tools), Troubleshooting (401/403), SigV4-vs-JWT disambiguation. Document both PKCE (loopback + manual paste) and SRP. State token lifetime with explicit unit, expiry handling, "no JWT on shared filesystem" rule.
  - **Traces to:** R10.6, R10.7, R10.8, R10.9, R10.11
  - **Depends on:** Task 10.4 (CLI finalized), Task 7.2 (tool list finalized)
- [ ] **Task 12.3** Update `.kiro/steering/01-architecture-context.md` (or add a new steering file) with a ≤150-word external-access summary linking both runbooks.
  - **Traces to:** R10.10
  - **Depends on:** Task 12.1, Task 12.2

## Task Group 13: Integration and Property-Based Tests (P1–P10)

- [ ] **Task 13.1** Implement property tests P1 (valid token admission) and P2 (invalid token rejection without leakage) using fast-check against the middleware.
  - **Traces to:** P1, P2
  - **Depends on:** Task 7.4
- [ ] **Task 13.2** Implement property test P3 (CI mutation rejection: `CI_READONLY ∩ MUTATION_TOOL_SET = ∅`).
  - **Traces to:** P3
  - **Depends on:** Task 7.2
- [ ] **Task 13.3** Implement property test P4 (unknown scope / missing auth rejection).
  - **Traces to:** P4
  - **Depends on:** Task 7.4
- [ ] **Task 13.4** Implement property test P5 (audit entry well-formedness and no-leak).
  - **Traces to:** P5
  - **Depends on:** Task 8.3
- [ ] **Task 13.5** Implement property test P6 (developer path preservation — 51/51 SigV4 tools).
  - **Traces to:** P6
  - **Depends on:** Task 11.3
- [ ] **Task 13.6** Implement property test P7 (scope isolation + lifetime bounds) as an integration test against Cognito.
  - **Traces to:** P7
  - **Depends on:** Task 2.4
- [ ] **Task 13.7** Implement property test P8 (no long-lived secrets in CI path) via static analysis of composite action files.
  - **Traces to:** P8
  - **Depends on:** Task 9.1
- [ ] **Task 13.8** Implement property test P9 (HPC token via Cognito-native flow only; empty stdout on failure) using Hypothesis.
  - **Traces to:** P9
  - **Depends on:** Task 10.7
- [ ] **Task 13.9** Implement property test P10 (CI attribution completeness via log-join) — audit log fields match Request_Metadata, broker_request_id joinable, no Pre-Token trigger dependency.
  - **Traces to:** P10
  - **Depends on:** Task 8.3, Task 9.3

## Phase B → C Migration (deferred)

> This placeholder group contains zero executable subtasks per Requirement 11.5.
> Detailed Path C implementation tasks (Gateway provisioning, Cedar policies,
> Gateway-attached authorizer, Gateway-routed invocations) will be captured in the
> follow-on spec at `.kiro/specs/mcp-external-access-gateway/` when Path C work begins.

---

## Dependency Graph (summary)

```
Group 1 (network gate) ──▶ Group 2 (Cognito CDK)
                              │
              ┌───────────────┼───────────────────┐
              ▼               ▼                   ▼
        Group 3 (broker)  Group 4 (authorizer)  Group 6 (stack reg)
              │               │
              ▼               ▼
        Group 5 (CDK tests)  Group 7 (middleware)
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
              Group 8      Group 9    Group 10
              (audit)      (GH action) (HPC CLI)
                    │         │         │
                    └─────────┼─────────┘
                              ▼
                    Group 11 (dev regression)
                              │
                              ▼
                    Group 12 (runbooks)
                              │
                              ▼
                    Group 13 (property tests)
```
