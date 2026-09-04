# Tasks: MCP External Access — Path C (Gateway-fronted)

**Spec ID:** `mcp-external-access-alternative-gateway`
Companion: `requirements.md`, `design.md`,
`../mcp-external-access-revised/decision-log.md`.

**Nothing below Task 0 may start until Task 0 is recorded.** This rule exists because Path B
spent a full spec cycle building on an unverified platform assumption. Task 0 costs under a
day; the alternative is discovering DP-7 after the CDK stack and interceptor are written.

> **Gate status for the whole effort lives in `design.md` §9 (Gate Register)** — cleared gates
> in §9.1, open gates ranked by what they block in §9.2, and the standing prohibition on
> deploying the Path B authorizer custom resource in §9.3. Questions queued for the next AWS
> analyst round are in **§10**; an authoritative answer to Q1 would clear Gate 1 without
> running Task 0 at all.

---

## Task 0 — Verification gate (DP-7, DP-1, DP-8) — **BLOCKING**

Goal: determine empirically whether a REQUEST interceptor fires for an MCP-protocol AgentCore
Runtime target, and whether its injected headers reach the container. Everything else is
downstream of the answer.

- [x] **0.1 Confirm the server can serve JSON framing in situ — on a THROWAWAY Runtime.**

  > **Do NOT set this on the live Runtime.** Revised 2026-08-13. Two reasons:
  > 1. Framing is server-wide (design AD-C7), so flipping it changes the response format for
  >    the **developer** path as well as the Gateway path. Before proxy v1.2.0 that broke
  >    every developer tool call with `-32603 "Empty SSE response"`. The proxy is now
  >    framing-tolerant, so this is no longer fatal — but it is still a live-config change
  >    with no upside during a probe.
  > 2. An env-var change means `update-agent-runtime`, a **full-replacement** API. A partial
  >    payload silently wipes `networkConfiguration`, `environmentVariables`,
  >    `protocolConfiguration`, `roleArn`, `agentRuntimeArtifact`, and
  >    `lifecycleConfiguration` (progress.md C9). Not a risk worth taking to answer a
  >    one-hour question.

  Deploy a **second, throwaway Runtime from the same container image** with
  `FASTMCP_JSON_RESPONSE=true` (or the `MCP_JSON_RESPONSE` env from Task 3). Confirm a
  `tools/list` response returns `Content-Type: application/json` rather than
  `text/event-stream`, and that `stateless_http=True` still functions alongside it. Use this
  throwaway Runtime as the Gateway target for 0.2–0.5, then destroy it in 0.6.

  *Verified locally that the switch works at the library level; this step confirms it
  survives the AgentCore container. Note the pin drift recorded in AD-C7 —* `pyproject.toml`
  *pins `fastmcp==3.2.4` while the environment has 3.4.1 / mcp 1.27.2. Record which version
  the container image actually ships as part of this step.*
  _Requirements: R0.4, R3.1, R3.3_

- [x] **0.2 Stand up a throwaway Gateway.**
  Protocol type unset. Attach the **throwaway Runtime from 0.1** — not the live one — as an
  `agentcoreRuntime` target with outbound auth IAM (SigV4). No authorizer yet — keep the
  variable count at one.
  _Requirements: R1.1, R1.2, R1.3_

- [x] **0.3 Attach a trivial echo interceptor.**
  A REQUEST interceptor Lambda with `passRequestHeaders: true` that logs only
  `event["http"]["gatewayRequest"]["path"]` and the header *names* it received (never
  values), injects a single fixed header
  `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal: probe`, and returns
  `transformedGatewayRequest` with the body passed through unchanged.
  _Requirements: R4.1, R4.5_

- [x] **0.4 Invoke through the Gateway and answer the two questions.**
  `POST {gatewayEndpoint}/{targetName}/invocations` with a `tools/list` JSON-RPC body.
  Record:
  - **(a)** Did the interceptor Lambda execute? (CloudWatch log presence.)
  - **(b)** Did `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal: probe` arrive at the MCP
    container? Add a temporary debug log of received header *names* in the server to observe
    this.
  Run twice — once with JSON framing, once with SSE framing — to isolate whether framing is
  the trigger.
  _Requirements: R0.1, R0.2, R0.4_

- [x] **0.5 Record the result and take the branch.**
  Write `docs/reports/mcp-external-access-gateway-verification.md` with the raw evidence.
  - Interceptor fires **and** header arrives → **proceed to Task 1** on the Runtime-target
    architecture (AD-C1 confirmed).
  - Interceptor fires only with JSON framing → proceed, and R3.1/R3.2 become
    safety-critical rather than merely advisable. Note it prominently.
  - Interceptor does **not** fire → **stop.** Re-evaluate DP-8: switch to the **MCP-target**
    architecture, which uses the `mcp` interceptor payload with parsed JSON-RPC and carries
    no buffered-only restriction. Amend `design.md` AD-C1 before any further task.
  _Requirements: R0.1, R0.3, R0.5_

- [x] **0.6 Tear down the throwaway Gateway AND the throwaway Runtime** from 0.1, so neither
  can be mistaken for the real one or accrue cost. Capture observed per-invocation cost
  figures for DP-6 first. Confirm the live Runtime's configuration was never modified:
  `GetAgentRuntime` should show unchanged `environmentVariables` and no
  `customJWTAuthorizer`.
  _Requirements: R0.5, R2.3_

---

## Task 1 — Decide and record the open postures

- [x] **1.1 Decide DP-2 (AD-C5 posture).** Either (a) no Runtime lockdown, or (b) lockdown
  with the Developer_Principal role in the `ArnNotEquals` exception set. Record the choice
  and its risk rationale in `design.md` AD-C5. **Do not write any resource-based policy
  before this is decided** — an explicit `Deny` overrides every `Allow` and would sever the
  developer path immediately.
  _Requirements: R2.4_

- [x] **1.2 Size DP-6.** Gateway per-invocation cost plus one interceptor Lambda invocation
  per MCP call, against expected CI and HPC volume. Record in `design.md`.
  _Requirements: none (go/no-go input)_

- [x] **1.3 Resolve the `MdcServerStack` blocker.** Confirm whether
  `infrastructure/cdk/lib/mdc-server-stack.ts` exists on `develop_aws` and reconcile, so
  `cdk synth` resolves on the working branch.

  > **RESOLVED 2026-09-05.** The file exists on the working branch
  > (`feature/congnito_endpoint`). `bin/cdk.ts` imports `MdcServerStack` from
  > `../lib/mdc-server-stack` and it resolves correctly. Full stack chain:
  > `MdcVpcStack` → `MdcSecurityStack` → `MdcDataStack` → `MdcServerStack` →
  > `MdcExternalAccessAlternativeStack`. `npx tsc --noEmit` exits 0 (zero type errors).
  > `npx cdk synth` exits 0 (deprecation warnings only: `containerInsights`,
  > `advancedSecurityMode`). The design.md §7 claim that the file was "absent" was incorrect
  > on this branch — no code change or reconciliation was needed. `design.md` §7 updated to
  > reflect the resolution.

  _Requirements: R8.4_

---

## Task 2 — CDK: Gateway, target, roles

- [x] **2.1** Create `infrastructure/cdk/lib/mdc-mcp-gateway-stack.ts` exporting
  `MdcMcpGatewayStack`, taking the Runtime ARN and Cognito pool/client IDs as props.
  _Requirements: R8.1_

- [x] **2.2** Define the Gateway with protocol type unset and the Cognito
  `customJWTAuthorizer` (`discoveryUrl`, `allowedClients`, `allowedAudience`,
  `allowedScopes`).
  _Requirements: R1.1, R2.1_

- [x] **2.3** **Import**, do not create, the Gateway_Execution_Role — via `fromRoleName(...,
  { mutable: false })`. `PowerUserRestrictions` blocks `iam:CreateRole` (progress.md C7), and
  the Path B stack already established this pattern for three roles. Add the
  Gateway_Execution_Role and the interceptor Lambda execution role to
  `docs/mdc-external-access-alt-iam-request.txt` for admin pre-creation, specifying the
  `aws:SourceArn` / `aws:SourceAccount` trust conditions scoped to the Gateway ARN.
  _Requirements: R2.5, R8.6, R8.7_

- [x] **2.4** Register the Runtime target: ARN + explicit qualifier, outbound auth IAM
  (SigV4), no schema, and `metadataConfiguration.allowedRequestHeaders` listing exactly the
  three Trusted_Context_Headers.
  _Requirements: R1.2, R1.3, R1.5, R4.2_

- [x] **2.5** Assert in the stack (or a unit test) that the Runtime is **not** given a
  `customJWTAuthorizer`.
  _Requirements: R2.3_

- [x] **2.6** If DP-2 posture (b): attach the Runtime resource-based policy permitting both
  the Gateway_Execution_Role and the Developer_Principal role.
  _Requirements: R2.4_

- [x] **2.7** Export `McpEndpointUrl` as the Gateway endpoint, replacing the Runtime
  invocation URL under the same export name.
  _Requirements: R1.4_

- [x] **2.8** Wire into `bin/cdk.ts` with a dependency on the Runtime-owning stack; confirm
  `cdk synth` succeeds and `cdk diff` shows no destructive change to existing stacks.
  _Requirements: R8.3, R8.4_

---

## Task 3 — MCP_Server: response framing

- [x] **3.1** Add `json_response` to `mcp.run()` in `mcp_server_python/src/mcp_server.py`,
  defaulting to true via `MCP_JSON_RESPONSE`, mirroring the existing `MCP_STATELESS_HTTP`
  pattern. Leave `stateless_http` untouched — it is mandatory for AgentCore.
  _Requirements: R3.1, R3.2, R3.3_

- [x] **3.2** Emit a WARNING-level startup log when `json_response` is disabled, stating that
  Gateway interceptors may not fire.
  _Requirements: R3.4_

- [x] **3.3** Confirm the stdio local-dev path is unaffected.
  _Requirements: R3.5_

- [x] **3.4** Unit-test that the resolved `json_response` value follows the env var and
  defaults to true.
  _Requirements: R3.1, R3.2_

- [x] **3.5 Make the developer proxy framing-tolerant.** **DONE 2026-08-13.**
  `tools/agentcore-kiro-proxy.py` v1.2.0: `parse_sse()` now falls back to parsing a bare
  JSON object or array when no SSE `data:` frames are present, via a new `_parse_json_body()`
  helper. Without this, enabling `json_response` (R3.1) breaks every developer tool call with
  `-32603 "Empty SSE response"` — framing is server-wide and not negotiable via `Accept`
  (design AD-C7). Covered by `TestJsonResponseFraming` (6 cases: bare object, batch array,
  pretty-printed body with blank lines, unparseable body, empty body, SSE-still-preferred)
  plus `test_property_json_framing_roundtrip`. Suite: 30 passed.
  **This required amending R7.1 from "byte-identical" to "functionally unchanged."**
  _Requirements: R7.1 (amended), R7.2, R3.1_

---

## Task 4 — Interceptor Lambda

- [x] **4.1** Create `infrastructure/cdk/lambda/gateway_interceptor/index.py` per
  `design.md` §4.2: derive principal from the scope claim, inject the three
  Trusted_Context_Headers, pass the base64 body through unchanged.
  _Requirements: R4.1_

- [x] **4.2** Strip any inbound `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*` header before
  merging injected values, so unforgeability does not rest solely on platform precedence.
  _Requirements: R4.3_

- [x] **4.3** Return HTTP 403 via `transformedGatewayResponse` when no principal can be
  derived.
  _Requirements: R4.6_

- [x] **4.4** Ensure no code path logs the `Authorization` header or any token value; add a
  test asserting this.
  _Requirements: R4.4_

- [x] **4.5** Register the interceptor as REQUEST type with `passRequestHeaders: true` and a
  payload filter excluding `RESPONSE_BODY`.
  _Requirements: R4.5, R6.3_

- [x] **4.6** Set a 2-second timeout budget and reserved concurrency.
  _Requirements: R4.7_

- [x] **4.7** Unit-test the handler against the documented `http` interceptor payload shape
  (base64 body, `/{targetName}/invocations` path).
  _Requirements: R4.1_

---

## Task 5 — MCP_Server middleware and audit

- [x] **5.1** Change principal derivation to read
  `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal` / `-Scope`, with absence ⇒
  `developer-sigv4`. Per `design.md` §5 this is the only substantive middleware change.
  _Requirements: R5.1, R5.2_

- [x] **5.2** Keep default-deny on unrecognized scope and on tools outside the
  Allowed_Tool_Set.
  _Requirements: R5.3, R5.4_

- [x] **5.3** Carry Path B §10's tool-set *structure* across (explicit enumeration,
  default-deny, `MUTATION_TOOL_SET` excluded from both JWT scopes).
  _Requirements: R5.5_

- [x] **5.3a** **Re-derive the per-scope counts against the Python runtime.** Path B's
  "CI 40 / HPC 48 / developer 51" came from the retired Node runtime (51 tools). The active
  runtime is Python `mdc_mcp_rag_server_python-v5K2F8BGrN` with **53 tools** (verified live
  2026-08-13; progress.md C1's "52" is also stale). Enumerate the live `tools/list`, classify
  every tool, and leave none unclassified. Note `extract_ci_error_signal` (module
  `error_analysis`) in particular — it postdates both the Node split and the steering catalog.
  Record the resulting counts in `design.md`.
  _Requirements: R5.6_

- [x] **5.4** Add `broker_request_id` from the injected header to the audit entry; add
  `SOURCE_IP` from Lambda client context, tolerating absence.
  _Requirements: R6.1, R6.2_

- [x] **5.5** Assert no raw token or full claim set reaches the audit log.
  _Requirements: R6.4_

---

## Task 6 — Verification

- [x] **6.1 Property 11 (unforgeability).** Send each Trusted_Context_Header with a forged
  value from a CI-scoped client; assert the MCP_Server observes the interceptor-derived
  value, not the forged one.
  _Requirements: R4.3; Property 11_

- [x] **6.2 Property 6 (developer path).** Invoke all 53 tools over Developer_Principal
  SigV4 directly against the Runtime with the framing-tolerant proxy (v1.2.0+, per amended
  R7.1) and unmodified `.kiro/settings/mcp.json`; assert 53/53 succeed. Run it **twice** —
  once against an SSE-framed Runtime and once against a JSON-framed one — since R7.1 now
  requires insensitivity to framing rather than an unmodified file.
  Assert `GetAgentRuntime` reports no
  `customJWTAuthorizer`.
  _Requirements: R7.1–R7.4; Property 6_

- [x] **6.3 Scope isolation.** CI-scoped token is denied on all 6 `MUTATION_TOOL_SET` tools
  and on the 11 tools outside `mcp/ci-readonly`; HPC-scoped token is denied on the 3 outside
  `mcp/hpc-user`.
  _Requirements: R5.3; inherited Path B Property 3_

- [x] **6.4 Property 12 (attribution).** Every Gateway-admitted request produces exactly one
  audit entry joining a Token_Broker log entry on `broker_request_id`.
  _Requirements: R6.1; Property 12_

- [x] **6.5 Rejection hygiene.** Missing, expired, wrong-audience, and wrong-scope tokens all
  yield 401 at the Gateway with no claim or tool metadata in the body.
  _Requirements: R2.2_

- [x] **6.6 Large-response safety.** Invoke a tool returning a multi-megabyte RAG result;
  confirm no Lambda payload-limit error and that the response reaches the caller intact.
  _Requirements: R6.3_

---

## Task 7 — Documentation

- [x] **7.1** `docs/runbooks/mcp-external-access-ci.md` — token acquisition, Gateway
  endpoint, composite action usage.
  _Requirements: R9.1_

- [x] **7.2** `docs/runbooks/mcp-external-access-hpc.md` — `mdc-mcp-jwt` PKCE flow, SRP
  fallback, Gateway endpoint.
  _Requirements: R9.1_

- [x] **7.3** State in both runbooks that the developer SigV4 path targets the Runtime
  directly and does not traverse the Gateway.
  _Requirements: R9.2_

- [x] **7.4** Troubleshooting: interceptor not firing, 401 at Gateway, 403 from tool scoping,
  missing Trusted_Context_Headers, SSE-framing regression.
  _Requirements: R9.3_

- [x] **7.5** Update `../mcp-external-access-revised/decision-log.md` to mark DP-1 … DP-8
  closed with their final resolutions.
  _Requirements: none (hygiene)_
