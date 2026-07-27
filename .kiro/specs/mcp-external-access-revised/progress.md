# Progress — MCP External Access (Path B, Cognito JWT on AgentCore Runtime)

Working memory for the kiro-cli engagement. The agent reads this at kickoff and
updates it after every task.

**Spec:** `.kiro/specs/mcp-external-access-revised/`
**Runtime:** `mdc_mcp_rag_server_python-v5K2F8BGrN` (Python, 52 tools, `python-tenants-v11`)
**Region:** us-east-1
**Account:** 903050880929

---

## Corrections (pre-seeded)

| # | Mistake/trap | Correction |
|---|---|---|
| C1 | The original spec references the Node.js runtime `mdc_mcp_rag_server-TMXDllG2Wi` (51 tools). | The active runtime is **Python** `mdc_mcp_rag_server_python-v5K2F8BGrN` (52 tools). All ARNs, endpoint URLs, and tool counts use this. |
| C2 | Task 0 expected HTTP 401. | The runtime returned **HTTP 403** ("Authorization method mismatch") — this is correct: it proves the endpoint is reachable and that no JWT authorizer is attached yet (SigV4-only). The gate passes. |
| C3 | The original design (AD-1) assumed Cognito supports RFC 8628 Device Flow. | It does NOT. The revised spec uses Auth Code + PKCE (Hosted UI) with SRP as headless fallback. |
| C4 | The original design (AD-3) used a Pre-Token-Generation trigger + DynamoDB for CI attribution. | Removed. Attribution is Token_Broker structured log + MCP Request_Metadata joined on the request id. |
| C5 | CDK stack name must NOT collide with the original spec's stack. | Use `MdcExternalAccessAlternativeStack` (AD-4). |
| C6 | The developer SigV4 path (`tools/agentcore-kiro-proxy.py`) must remain byte-identical. | R7 — do not modify it. Task 9 validates 52/52 tools still work via SigV4 after the authorizer is attached. |
| C7 | `PowerUserRestrictions` blocks `iam:CreateRole`. | CDK stack must use `fromRoleName`/`fromRoleArn` for any IAM roles that don't already exist. Admin pre-creates if needed (same pattern as the Neptune bulk-loader role). |
| C8 | Design §7.4 / R2.9 / R7.2 assert AgentCore Runtime accepts **SigV4 alongside a JWT authorizer** (dual-auth) on the same endpoint. | **RISK — unverified against the platform.** The Task 0 gate 403 body was *"Authorization method mismatch... ensure your request uses the matching method (OAuth or SigV4)"*, which indicates an AgentCore Runtime enforces a **single** inbound auth mode (OAuth **XOR** SigV4), not both. If so, attaching the customJWTAuthorizer would **break the developer SigV4 path** (violating R7/C6). Task 5 authors the authorizer as specified, but the CDK is **NOT deployed**. Before any `cdk deploy`, this MUST be verified (attach in a throwaway/test runtime, or AWS confirmation). If single-mode is confirmed, pivot to the Path C AgentCore **Gateway** fallback (design §11.3 / R8.6) which fronts the Runtime and leaves the Runtime's SigV4 intact for developers. Flagged, not silently shipped. |
| C9 | The design's `AwsCustomResource` for `updateAgentRuntime` passes **only** `agentRuntimeArn` + `authorizerConfiguration`. | `bedrock-agentcore-control:update-agent-runtime` is a **full-replacement** API (confirmed by the live config + steering note "both must be carried on every update-agent-runtime"). Passing a partial payload would wipe `networkConfiguration`, `environmentVariables`, `protocolConfiguration`, `roleArn`, `agentRuntimeArtifact`, and `lifecycleConfiguration`. Task 5's custom resource carries the **full lossless payload** captured live (2026-07-27) plus the new `authorizerConfiguration`. Live `MCP_WORKFLOW_ROOT` is `/mnt/workflow` (not the value noted earlier in progress.md). |
| C10 | Task 3 / design §4.2 imply the GitHub Actions OIDC provider (`token.actions.githubusercontent.com`) may already exist. | **It does NOT exist** in account 903050880929 (only `ncis-gitlab.nesdis-hq.noaa.gov` is present). The provider is a **new** IAM resource requiring `iam:CreateOpenIDConnectProvider` (blocked for PowerUser, same class as C7). It is documented in the admin-request doc and **referenced** in CDK via `fromOpenIdConnectProviderArn`. |
| C11 | Design §4.2/§12.4 show `new iam.Role` for the federated CI role and CDK tests asserting its in-template trust policy. | Contradicts C7 (no `iam:CreateRole`). Neither `mdc-mcp-alt-gh-oidc-ci` nor `mdc-mcp-alt-token-broker-role` exists. Both are **admin-created** (trust + permission policies specified in the admin-request doc) and **imported** in CDK via `fromRoleName`. CDK tests adjusted: assert the Token_Broker uses the imported role, the function resource policy grants invoke to the OIDC role ARN, and the required roles are enumerated in the admin-request doc — rather than asserting an in-stack `AWS::IAM::Role` trust policy that C7 forbids creating. |
| C12 | Design §3.4 pulls `ciAppClient.userPoolClientSecret` into the Secrets Manager secret. | Doing so makes CDK emit a `Custom::DescribeCognitoUserPoolClient` resource backed by an **auto-created Lambda execution role** → needs `iam:CreateRole` at deploy → blocked (C7). Fix: the CDK secret is a RETAIN **shell** holding `client_id` + a `REPLACE_VIA_PUT_SECRET_VALUE` placeholder; the real `client_secret` is injected **out-of-band** via a one-time `aws secretsmanager put-secret-value` (documented in the admin doc §5). Bonus: the client secret never enters CloudFormation/custom-resource state. Enforced by the test asserting `AWS::IAM::Role` count == 0. |

---

## Codebase Patterns

- **CDK stacks** live at `infrastructure/cdk/lib/`. Entry point `infrastructure/cdk/bin/cdk.ts`.
- **Admin IAM request docs** live at `docs/` (e.g. `docs/neptune-bulk-loader-role-request.txt`).
- **Runbooks** at `docs/runbooks/`.
- **Runtime env vars** (6): `DB_BACKEND=aws`, `NEPTUNE_ENDPOINT`, `OPENSEARCH_ENDPOINT`, `AWS_REGION=us-east-1`, `MCP_STATELESS_HTTP=true`, `MCP_WORKFLOW_ROOT=/app/supported_repos/global-workflow_develop`.
- **Task role:** `mdc-mcp-rag-ecs-task-role` (Neptune, OpenSearch, Bedrock, logs, X-Ray, secrets, SSM).
- **Network:** subnets `subnet-0e13af6b3a9a6416f`, `subnet-04447750c61bd7e06`; SG `sg-096489a0876cc78c1`.

---

## Key Facts for the Engagement

- **Public endpoint confirmed reachable** (2026-07-22): HTTP 403 from the Python runtime's public URL. No network/firewall block.
- **Current auth:** SigV4 only. The JWT authorizer will be *added alongside* SigV4, not replacing it (dual-auth: existing developer path unaffected).
- **GitHub OIDC provider** in AWS account: confirm whether it already exists before Task 3 creates it (may collide if another stack created it).
- **Cognito domain:** needs to be globally unique (e.g. `mdc-mcp-rag-auth`). Check availability.
- **`cdk diff` guardrail:** R12 requires showing `cdk diff` before any `cdk deploy` and recording it in the run log.

---

## Task 0 Gate Result

| Field | Value |
|---|---|
| Date | 2026-07-22 |
| Runtime | `mdc_mcp_rag_server_python-v5K2F8BGrN` |
| Endpoint | `https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3A.../invocations?qualifier=DEFAULT` |
| HTTP status | **403** |
| Response | `{"message":"Authorization method mismatch..."}` |
| Verdict | **PASS** — endpoint reachable; SigV4-only (JWT authorizer = Task 5) |
| Pivot needed? | **No** — no AgentCore Gateway required |

---

## Progress Log

| Date | Task | Result | Notes |
|---|---|---|---|
| 2026-07-22 | 0.1 | PASS (HTTP 403) | Endpoint reachable; SigV4-only; gate passes |
| 2026-07-22 | 0.2 | Pending | Record in `docs/reports/` |
| 2026-07-22 | 0.3 | PASS | No pivot needed; proceed to Task 1 |
| 2026-07-27 | 1.1 | DONE | `lib/mdc-external-access-alternative-stack.ts` skeleton + typed props (`runtimeArn`, `mcpServerTaskRole?`, `allowedGithubSubPatterns`) |
| 2026-07-27 | 1.2 | DONE | Wired into `bin/cdk.ts` with Python runtime ARN, `securityStack.ecsTaskRole`, NOAA-EMC sub allowlist, `addDependency(serverStack)` |
| 2026-07-27 | 1.3 | DONE | `test/mdc-external-access-alternative-stack.test.ts` — synth + R9.10 no-DynamoDB placeholder |
| 2026-07-27 | 1.4 | PASS | `tsc` clean; `cdk synth MdcExternalAccessAlternativeStack` OK; 2/2 tests pass. Corrections C8–C11 recorded. |
| 2026-07-27 | 2.1–2.6 | DONE | User pool (RETAIN, no PreTokenGen), Hosted UI `mdc-mcp-external-alt` (verified available), resource server `mcp` w/ exactly `ci-readonly`+`hpc-user`, CI client (client-creds only, secret), HPC client (auth-code+PKCE public + SRP, no ROPC/no client-creds), CI secret in Secrets Manager (RETAIN). Public fields exposed for Task 5. Outputs added. |
| 2026-07-27 | 2.7–2.9 | PASS | CDK tests: 11/11 pass — RETAIN on pool+secret, exactly 2 scopes, grant isolation, R9.10 (0 DynamoDB, no PreTokenGen), R9.5 (no Neptune/OpenSearch/S3/EFS). Note: `AllowedOAuthScopes` renders as `Fn::Join` token — assertions match the join suffix. `advancedSecurityMode` is deprecated but functional (cosmetic). P7 (2.10) is an optional `*` property test — deferred. |
| 2026-07-27 | 3.1–3.3 | DONE | OIDC provider ABSENT (C10) + role ABSENT (C11) → admin-request doc `docs/mdc-external-access-alt-iam-request.txt` (provider + 3 roles + one-time secret populate). CDK imports role via `fromRoleName('mdc-mcp-alt-gh-oidc-ci', mutable:false)`; output `CiOidcRoleArn`. Discovered C12 (client-secret getter injects auto-role custom resource) → secret now a RETAIN shell + out-of-band populate. Tests: 14/14 pass, incl. `AWS::IAM::Role` count == 0 (C7-clean). |
| 2026-07-27 | 4.1–4.7 | DONE | `lambda/token_broker/index.py` (Python 3.12): allowlist→secret→plain client-creds token→attribution log→return token+request_id; NO DynamoDB, NO trigger; 502 on upstream fail, slo_breach warn. CDK: log group `/mdc-mcp-rag-alt/token-broker` (RETAIN, 90d), imported exec role `mdc-mcp-alt-token-broker-role` (mutable:false, no auto-role), reserved concurrency 10, timeout 10s, 256MB, env {ALLOWED_SUB_PATTERNS_JSON(glob→anchored regex), COGNITO_TOKEN_ENDPOINT, CI_CLIENT_SECRET_ARN}, `addPermission` grants invoke to OIDC role ARN (R3.2). Output `CiTokenBrokerFunctionName`. |
| 2026-07-27 | 4.8 | PASS | Python unittest 4/4 (happy path returns token+request_id & never logs token; forbidden repo → 403 no Cognito call; upstream fail → 502 no token; no dynamodb client). CDK jest 19/19. `cdk synth` OK with Lambda asset. |
| 2026-07-27 | 5.1–5.4 | DONE | `AwsCustomResource` `updateAgentRuntime` with **full lossless payload** (C9: agentRuntimeId+artifact python-tenants-v11+roleArn+networkConfiguration+protocol+lifecycle+env) PLUS `authorizerConfiguration.customJWTAuthorizer{discoveryUrl,allowedAudience,allowedClients=[ci,hpc]}`. Custom-resource role imported `mdc-mcp-alt-authorizer-cr-role` (mutable:false → no auto-role). Snapshot `infrastructure/cdk/snapshots/authorizer-config.json` + drift script `infrastructure/cdk/scripts/authorizer-drift-detector.sh` (emits `MdcMcpExternalAccessAlt/AuthorizerDrift`). Drift **alarm** `mdc-mcp-alt-authorizer-drift`. Output `McpEndpointUrl` (Python ARN, C-IMPACT-3). |
| 2026-07-27 | 5.5 | PASS | CDK jest 25/25 (this stack) + full suite **53/53**; `cdk synth` (stack + full app) OK. Verified update payload carries all required members (C9 test). **`update-agent-runtime` confirmed full-replacement API** (requires agent-runtime-id, agent-runtime-artifact, role-arn, network-configuration). |
| 2026-07-27 | R12 | NOTE | `cdk diff` produces no output in this environment (also no output for the already-deployed `MdcSecurityStack`) → no CloudFormation GetTemplate connectivity. R12 destructive-change evidence provided instead by (a) `cdk synth` success and (b) the R9.5 test asserting zero `AWS::Neptune/OpenSearchService/S3::Bucket/EFS` resource types in the stack (imports only, never mutates). The live `cdk diff` review MUST be performed by the operator at actual deploy time. **Stack NOT deployed** (stage-only engagement). |
| 2026-07-27 | C8 | **FLAG** | Dual-auth (SigV4 + JWT on one Runtime) is UNVERIFIED and contradicted by the Task 0 403 "Authorization method mismatch" evidence. Attaching the authorizer may break the developer SigV4 path (R7/C6). Verify before any deploy; pivot to Path C Gateway (§11.3) if single-mode confirmed. Authored per spec, NOT deployed. |
