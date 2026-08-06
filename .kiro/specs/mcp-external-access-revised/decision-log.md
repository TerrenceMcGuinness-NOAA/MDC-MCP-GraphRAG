# Decision Log — MCP External Access (supersedes parts of Path B)

**Date:** 2026-08-06
**Status:** Path B (Runtime-attached JWT) is INVALIDATED in part. **Path C (Gateway-fronted) adopted as the path forward.**
**Inputs:** RDHPC connectivity test (T. McGuinness, gaea64), AWS rep review, AWS AgentCore documentation.

---

## 1. Confirmed external findings

### F-1. RDHPC → AWS AgentCore egress works

```
Terry.McGuinness (gaea64) ~ $ curl --max-time 10 https://bedrock-agentcore.us-east-1.amazonaws.com
Invalid api path
```

DNS + TLS + HTTP egress from RDHPC (gaea64) to the AgentCore endpoint in `us-east-1`
succeeds. `Invalid api path` is an application-layer response from the AWS service,
which proves the request traversed the network and was served.

**Caveats to carry forward:**
- This is the **control-plane** host, not a Runtime data-plane invocation URL.
- The response is an API-path error, **not** the HTTP 401 that R8.5 / Task 0.3 specify as
  the gate condition.
- Under Path C the endpoint that actually needs verifying becomes the **Gateway**
  endpoint, so Task 0 must be rewritten rather than checked off.

**Effect:** the *network reachability* half of the R8.5 concern is satisfied. The
*authorizer behavior* half is now a different test against a different endpoint.

### F-2. Not operating inside a FedRAMP boundary

Confirmed. This resolves the highest-severity open question raised in
`docs/reports/2026-06-30-mcp-external-access-fedramp-control-mapping.md` (its follow-up
#1, "confirm AgentCore FedRAMP status / region before any further build").

**Effect:** the FedRAMP control mapping is **de-escalated from blocking to advisory**.
There is no boundary/region gate above the implementation tasks, and no forced GovCloud
migration. The report's remaining items (MFA, FIPS endpoints, customer-managed KMS,
audit retention reconciliation, GitHub interconnection, DoS posture) remain as
hardening backlog, not preconditions.

### F-3. Dual inbound auth at the Runtime is IMPOSSIBLE

From [Authenticate and authorize with Inbound Auth and Outbound Auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html):

> An AgentCore Runtime can support either IAM SigV4 or JWT Bearer Token based inbound
> auth, but not both simultaneously.

The same note adds that you *can* create **different versions** of a Runtime configured
for different inbound auth types.

**This is a direct factual contradiction of the shipped design.** Design §7.4 currently
asserts:

> The AgentCore Runtime accepts a valid SigV4 signature **or** a valid Bearer JWT on the
> same endpoint when a JWT authorizer is configured; it rejects only requests that have
> neither.

That statement is wrong and must be struck.

### F-4. Gateway-fronting is the documented remedy

> You can front your AgentCore Runtime with an AgentCore Gateway so that the gateway
> becomes the single, governed entry point to the runtime

Documented benefits: policy-based authorization, Bedrock Guardrails, request/response
interceptors, unified observability — all applied outside the agent's own environment.

Two supporting mechanisms exist for preventing gateway bypass:

- **SigV4 runtime (our chosen shape):** attach a **resource-based policy** to the Runtime
  allowing only the gateway execution role, plus an explicit `Deny` on all other
  principals keyed on `aws:PrincipalArn`. The gateway assumes its service role to sign
  requests to the Runtime, so the gateway role is the invoking principal.
- **JWT runtime (not our shape):** `allowedWorkloadConfiguration` on the
  `customJWTAuthorizer`, using `hostingEnvironments` (gateway ARN) and/or
  `workloadIdentities`.

### F-5. `allowedScopes` DOES exist — OQ-2 resolves favorably

The authorizer configuration documents five fields, not three:

- `discoveryUrl` (must match `^.+/\.well-known/openid-configuration$`)
- `allowedAudience` → validated against `aud`
- `allowedClients` → validated against `client_id`
- **`allowedScopes`** → "validated against the scope claim in the JWT token. The
  `allowedScopes` authorization field will be configured as a list of strings."
- **Required custom claims** → validated against claim name and value

Also: "If both `client_id` and `aud` is provided, the agent runtime authorizer will
verify both."

**Effect:** R2.1 ("non-empty list of allowed scopes") and R2.3 (verify `scope` claim) are
**satisfiable as written**. The concern that these were unimplementable is withdrawn.
Note the doc states the authorizer config shape is **identical for Runtime or Gateway**,
so this carries over to the Gateway unchanged.

### F-6. Claims propagation mechanism differs from the design's assumption

Design AD-6 assumes AgentCore forwards
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorizer-Claims` (base64url JSON) to the
container, and treats **absence** of that header as the `developer-sigv4` principal.

The documentation describes a different, opt-in mechanism: Step 7, "Propagate a JWT token
to AgentCore Runtime," which requires an explicit **request header allowlist**
(`RequestHeaderConfiguration`) to pass `Authorization` through, after which the agent
decodes claims itself with signature validation skipped (already validated upstream).

No mention of the `...Custom-Authorizer-Claims` header appears in this document. **AD-6's
propagation mechanism is unverified and likely incorrect as written.**

---

## 2. Adopted decision: Path C

**Shape:** Runtime stays on **default IAM SigV4** inbound auth. An **AgentCore Gateway**
fronts it and holds the **Cognito JWT authorizer**. JWT-bearing requests from CI and HPC
terminate at the Gateway; the Gateway signs SigV4 to the Runtime — the same call shape the
developer path already uses today.

**Why this is now the only coherent option:**

1. F-3 makes simultaneous JWT + SigV4 at the Runtime impossible, and the developer SigV4
   path is a hard requirement (R7.2, Property 6).
2. Keeping the Runtime on SigV4 means the developer path needs **zero change** — R7.2 and
   Property 6 are satisfied trivially rather than by regression-testing a coexistence
   behavior that does not exist.
3. The Gateway URL becomes the stable public endpoint, so Runtime redeploys stop forcing
   URL changes in CI workflows and HPC configs (already noted as a Path C benefit in
   design §14).

**Rejected alternative:** two Runtime *versions*, one SigV4 and one JWT (permitted per
F-3). Rejected because it doubles the endpoint surface, splits observability, doubles
drift-detection scope, and still leaves tool-level authorization duplicated in the MCP
server — while the Gateway exists precisely to be the single governed entry point.

---

## 3. What this invalidates in the shipped spec

| Item | Location | Status |
|---|---|---|
| SigV4/JWT coexistence on one endpoint | design §7.4 | **FALSE — strike entirely** |
| AD-6 absence-of-header ⇒ `developer-sigv4` | design AD-6, §8.2 | **Unverified mechanism; redesign** |
| R2.9 (SigV4 coexistence with authorizer) | requirements | **Unsatisfiable as written** |
| R7.2 / Property 6 (developer path preserved) | requirements, §13 | **Intent preserved, mechanism changes** — satisfied by Runtime staying SigV4 |
| Task 5.x (authorizer on Runtime) | tasks | **Retarget to Gateway** |
| AD-2 / R8.5 / R8.6 / Task 0 | design §11.2–11.3 | **Reframe** — public entry point is now the Gateway |
| "Path C — Deferred" framing | design §14, R11 | **Path C is now the baseline, not deferred** |
| OQ-2 (`allowedScopes` may not exist) | design §16 | **RESOLVED — the field exists (F-5)** |
| Cost/maturity/schedule rationale for deferring C | design §14 Rationale | **Moot — deferral is no longer available** |

**What survives intact and is directly reusable:**

- **AD-1** (PKCE primary + SRP fallback) — unaffected; Cognito-side only.
- **AD-3** (Token_Broker log-join on `broker_request_id`) — unaffected, and design
  §14 C-IMPACT-4 already anticipated that a Gateway interceptor can record the same
  field with no Cognito change.
- **All of §3** (Cognito user pool, resource server, scopes, both app clients) — the
  authorizer config shape is identical for Gateway per F-5.
- **§4** Token_Broker Lambda, **§5** composite action, **§6** HPC_CLI_Helper — all
  produce/consume tokens without caring where the authorizer is attached.
- **§10** tool enumeration (40 / 48 / 51) — content survives; enforcement point moves.
- The four **C-IMPACT** decisions in §14 were written to keep this migration cheap. They
  did their job: audit emission is stateless, scope enumeration is explicit
  default-deny, and consumers read `McpEndpointUrl` rather than hard-coded URLs.

---

## 4. New open decision points created by Path C

**DP-1 — How does principal/scope context reach the MCP_Server? (highest priority)**
With JWT terminated at the Gateway and SigV4 on the wire to the Runtime, the Runtime sees
a SigV4 request from the *gateway execution role*. Per F-6 the claims header is not a
documented passthrough. Options:
  (a) Gateway request interceptor injects principal/scope headers;
  (b) `RequestHeaderConfiguration` allowlist forwards `Authorization` and the MCP server
      decodes claims (doc Step 7 pattern);
  (c) move tool-level authorization **to the Gateway** (Cedar / policy-based authz) and
      let the MCP server trust the Gateway entirely.
Option (c) would substantially shrink or delete §8 middleware and §10's in-server
enumeration. This choice determines how much of §8/§9/§10 survives.

**DP-2 — Does the bypass-prevention resource policy break the developer path?**
The documented lockdown policy `Deny`s every principal except the gateway execution role.
Applied verbatim, **developers lose direct SigV4 access** — the exact thing Path C was
chosen to preserve. Either (a) do not lock the Runtime down, accepting that trusted
developers bypass the Gateway (this is today's architecture), or (b) add developer role
ARNs to the `ArnNotEquals` exception set. Decide explicitly; do not inherit the doc's
example unmodified.

**DP-3 — Gateway target semantics and tool naming.**
The Runtime is registered as a **gateway target**. Confirm whether the Gateway re-exposes
or prefixes the 51 MCP tool names, since §10's enumeration and all client configs depend
on exact names.

**DP-4 — Gateway execution role trust hardening.**
Per the docs, restricting the Runtime to the gateway role is only as strong as controls on
who may assume that role. Add `aws:SourceArn` / `aws:SourceAccount` conditions to the
gateway execution role trust policy, scoped to the Gateway ARN (confused-deputy
prevention).

**DP-5 — Spec disposition.**
Path C was explicitly scoped (R11.3) to a **separate follow-on spec**,
`.kiro/specs/mcp-external-access-alternative-gateway/`. Decide: create that spec now and
retire `mcp-external-access-revised`, or amend the revised spec in place. Recommendation:
new spec, reusing §3–§6 and §10 verbatim, since roughly half the revised spec's
Runtime-authorizer content is now dead and in-place editing will leave contradictions.

**DP-6 — Cost.**
The Gateway is an additional per-invocation priced service; design §14 cited cost as
deferral reason #1. That objection no longer permits a decision, but the cost still needs
sizing against expected CI + HPC volume.

---

## 5. Pre-existing issues still open (from prior review)

- **Naming split:** directory is `mcp-external-access-revised`, but requirements/design
  refer throughout to `.kiro/specs/mcp-external-access-alternative/`, including in binding
  criteria R8.5, R11.1, R11.3, R11.4 and every `Feature:` property tag. R11.6 is
  self-executing on this. Resolve during DP-5.
- **`MdcServerStack` missing:** `infrastructure/cdk/bin/cdk.ts:6` imports
  `MdcServerStack` from `../lib/mdc-server-stack`, but `infrastructure/cdk/lib/` contains
  only `cdk-stack.ts`, `mdc-data-stack.ts`, `mdc-security-stack.ts`, `mdc-vpc-stack.ts`.
  No `mdc-server-stack.ts` exists under `infrastructure/cdk`. On `develop`, `cdk synth`
  cannot resolve that import. Confirm whether the file lives on `develop_aws` before any
  CDK task starts.
- **Implementation state is zero:** no external-access CDK stack, no
  `mcp_server_node/src/auth/`, no `tools/mdc_mcp_jwt/`, no `.github/actions/`, no
  runbooks. Every task box unchecked. Nothing built needs unwinding.

---

## 6. Recommended next actions

1. Strike design §7.4 and mark AD-6 / R2.9 as superseded, so nobody implements against
   the false coexistence claim.
2. Resolve **DP-1** — it determines the scope of the follow-on spec.
3. Create `.kiro/specs/mcp-external-access-alternative-gateway/` per R11.3, carrying
   §3–§6 and §10 forward; fix the naming split in the process.
4. Decide **DP-2** before writing any resource-based policy.
5. Re-scope Task 0: verify JWT-in / SigV4-out through a Gateway, not 401 on the Runtime
   URL.

---

## Sources

- [Authenticate and authorize with Inbound Auth and Outbound Auth — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- [Configure inbound JWT authorizer — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html)
- [Set up inbound authorization for your gateway — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html)

*Content from AWS documentation was rephrased for compliance with licensing restrictions; direct quotations are kept short and attributed inline.*


---

# Part 2 — Path C mechanism research (2026-08-06, same day)

Follow-up investigation to resolve DP-1 and DP-3. Outcome: **both resolved**, one new
blocking issue found (DP-7), and one architecture fork surfaced that changes the shape of
the recommendation (DP-8).

## F-7. DP-3 RESOLVED — Runtime targets do not rename or aggregate tools

From [AgentCore Runtime targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html):
the gateway routes traffic straight to the runtime with no aggregation and no protocol
translation, forwarding requests and responses between client and runtime agent
unmodified — explicitly unlike MCP targets, which merge tool capabilities into one
unified virtual MCP server.

**Effect:** §10's 40 / 48 / 51 tool enumeration survives byte-for-byte. No prefixing, no
renaming, no client-config churn on tool names.

**But three consequences to absorb:**
- **No capability sync and no semantic tool search** for Runtime targets. Clients must
  know exact tool names or call the server's own `tools/list`.
- **Path-based routing** — the endpoint becomes
  `https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/{targetName}/invocations`.
  This is the new `McpEndpointUrl` value (C-IMPACT-3 anticipated exactly this).
- **Gateway protocol type must be unset.** Runtime targets can be added to gateways with
  no protocol type set, and *cannot* be added to MCP-protocol-type gateways.

## F-8. DP-1 RESOLVED — interceptor Lambda header injection is the designed channel

Under SigV4 outbound, the Runtime sees a signed request from the gateway execution role,
so JWT claims do not arrive on their own. The supported remedy is a **REQUEST interceptor
Lambda** that injects headers, per
[Header propagation with Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-headers.html):

- Interceptor-returned headers merge with the target allowlist
  (`metadataConfiguration.allowedRequestHeaders`).
- **Interceptor-provided headers take precedence over client-provided headers on
  conflict.** This is the anti-spoofing property we need — a CI or HPC caller cannot forge
  its own principal or scope. The docs name this use case directly: inject context derived
  from authenticated user claims rather than trusting client-supplied values.
- **`X-Amzn-` prefixed headers are prohibited *except* `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`.**
  That is a purpose-built channel for runtime-bound custom context — use it.
- `Authorization` cannot be allowlisted at target creation, **but is forwarded when
  supplied by an interceptor Lambda**. So passing the original JWT through is also possible.
- `passRequestHeaders: true` is required for the interceptor to see inbound headers at all.
  The docs flag this as sensitive (headers carry tokens); ensure the interceptor does not
  log them.

**Recommended DP-1 resolution:** REQUEST interceptor validates nothing (Gateway authorizer
already did), reads claims, and injects
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal`, `-Scope`, and `-BrokerRequestId`.
The MCP_Server middleware (§8) reads those instead of
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorizer-Claims`. AD-6's *intent* survives; only
the header names and their producer change. **AD-3's log-join keys on `broker_request_id`,
which rides through as one of these headers — attribution survives unchanged.**

Hard limits to design against: **max 10 request headers per target**, 4 KB per value,
printable ASCII only, names matching `^[a-zA-Z0-9_-]+$`.

**Bonus for §9 audit:** for HTTP targets the gateway passes `GATEWAY_ARN`,
`GATEWAY_ACCOUNT_ID`, `REQUEST_ID`, and `SOURCE_IP` to the Lambda via **client context**
(`SOURCE_IP` is optional — treat as may-be-absent). `SOURCE_IP` is otherwise hard to obtain
and is useful for the audit schema.

## F-9. Gateway CANNOT see tool names for a Runtime target — corrects the §14 Path C vision

Runtime targets use the **`http`** interceptor payload, not the `mcp` one. Differences that
matter:

| | MCP target | HTTP / Runtime target |
|---|---|---|
| Body format | parsed JSON (`Map<String,Object>`) | **base64-encoded string** |
| Path | always `/mcp` | actual path, e.g. `/my-target/invocations` |
| `rawGatewayRequest` | included | not included |
| Response interceptor | supported | **buffered mode only** |

Because the body is an opaque base64 string, **the gateway does not parse JSON-RPC and
therefore has no native view of `tools/call` or the tool name.** Design §14 asserted Path C
would bring "Cedar tool-level policies … evaluated per tool invocation, replacing the
single `allowedToolSets.js` enumeration." **That is not available in the Runtime-target
shape.** Two workable options instead:

- **(a) Keep tool gating in the MCP_Server.** §8 middleware and §10 enumeration survive
  essentially intact — a much smaller change than "Path C deletes §8."
- **(b) Enforce in the interceptor.** The Lambda base64-decodes the body, parses JSON-RPC,
  reads `params.name`, and on denial returns `transformedGatewayResponse` — which
  **short-circuits: the gateway replies immediately without calling the target, and the
  RESPONSE interceptor does not run.** This is a clean 403 path but re-implements §10 in a
  Lambda.

**Recommendation: (a), with (b) available later as defense-in-depth.** This preserves the
most existing design and is the least-risk path.

## F-10. NEW BLOCKING ISSUE — DP-7: interceptors are buffered-only, our server streams

Two facts that collide:

1. Runtime targets support SSE streaming, **but** "Request and response interceptor Lambda
   functions are supported in buffered mode. Interceptors are not yet supported in
   streaming mode."
2. Our deployed server is **FastMCP Streamable HTTP**. Confirmed in-repo:
   `mcp_server_python/src/mcp_server.py:331-336` defaults `--transport` to
   `streamable-http` (comment: "AgentCore/gateway"), and
   `mcp_server_python/src/config/environment.py:80` documents host/port as "Address for
   FastMCP's Streamable HTTP listener (Requirement 1.1)", port 8000
   (`src/config/aws_config.py:18`).

> **ERRATUM (corrected in Part 3):** this paragraph originally claimed no `stateless_http`
> setting existed either. **That was wrong** — `stateless_http` *is* already set and is
> required for AgentCore. The grep behind that claim truncated before reaching it. Only
> `json_response` is genuinely absent. See F-14 for the corrected, empirically verified
> position.

`json_response` is absent from `mcp_server_python/src/`. FastMCP's streamable-http default
returns SSE for responses, so as currently written **the interceptor may never fire — which
would silently remove the entire DP-1 claims channel and, with it, all principal/scope
enforcement and audit attribution.** Same failure mode as the original AD-3 defect: tokens
validate, calls succeed, governance data is absent.

**DP-7 (blocking): confirm whether the MCP server must be pinned to buffered/JSON-response
mode for interceptors to run, and whether doing so is acceptable for tool latency and
payload size.** This must be answered before committing to the interceptor mechanism.

**Related constraint:** Lambda synchronous invoke has a **6 MB combined request+response
payload limit**, and the base64-encoded body counts against it. For a RAG server returning
search results this is a live risk. Mitigation is documented: configure a payload filter
excluding `RESPONSE_BODY`, after which the interceptor still sees `statusCode`,
`contentType`, and `headers`, can inject headers, and can override status — and returning
`body: null` leaves the original response untouched. Our audit needs only metadata, so this
mitigation fits well.

## F-11. Outbound auth has four modes — one preserves §8 with no interceptor at all

AgentCore Runtime targets support: **IAM (SigV4)** (gateway assumes its service role to
sign — the chosen model), **caller IAM credentials**, **OAuth (JWT)** via credential
providers, and **token passthrough** — where the gateway validates the inbound token and
forwards it to the target unmodified, described as useful when the runtime handles its own
authorization.

**Token passthrough is a near-exact fit for the existing §8 design** (server reads the JWT
itself). But it requires the Runtime's *inbound* auth to accept that JWT, i.e. a
JWT-inbound Runtime — which reintroduces F-3's either/or and loses the "developer SigV4
needs zero change" benefit that motivated Path C. **Logged as a considered-and-rejected
alternative**, not a recommendation.

## F-12. DP-2 update — bypass prevention now exists for both inbound types

The docs now state you can enforce gateway-only access regardless of whether the runtime
uses SigV4 or JWT inbound: the gateway stamps the source of each forwarded request and the
runtime validates it. SigV4 runtimes use a resource-based policy scoped to the gateway
execution role; JWT runtimes use `allowedWorkloadConfiguration`.

**DP-2 remains an open decision, unchanged in substance:** the documented SigV4 policy
denies all principals except the gateway role, which would sever the developer path. Decide
explicitly between not locking down, or adding developer role ARNs to the `ArnNotEquals`
exception set. DP-4 (trust-policy hardening with `aws:SourceArn` / `aws:SourceAccount`)
still applies.

## F-13. Guardrails need a schema — but not for us

Runtime targets accept an optional `schema` (S3 URI or `inlinePayload`, OpenAPI or Smithy,
auto-detected) used by the gateway policy engine for features such as guardrails. HTTP
protocol runtimes must supply one; **runtimes using MCP or A2A get a default schema
automatically.** Ours is MCP, so no schema authoring is required unless we want guardrails
beyond the default.

---

## NEW DP-8 — architecture fork: Runtime target vs MCP target

This is the decision that most affects the follow-on spec, and it was not visible before
this research.

| | **Runtime target** (as proposed) | **MCP target** |
|---|---|---|
| Gateway sees tool names | No — opaque base64 body | **Yes — parsed JSON-RPC** |
| Tool aggregation / `tools/list` | No, isolated | Yes, unified virtual MCP server |
| Semantic tool search | No | Yes |
| Per-tool Cedar policy | Not natively (F-9) | Natively feasible |
| Response interceptor | Buffered only | Supported |
| Endpoint needed | Runtime ARN + qualifier only | Reachable MCP endpoint |
| Gateway protocol type | must be **unset** | MCP |

An MCP target would deliver the §14 Path C vision as originally written (Cedar per-tool
policy, aggregation) and sidesteps the base64/tool-name problem — and AgentCore Gateway
supports **VPC egress to self-hosted MCP servers via private endpoints backed by VPC
Lattice**, so a private MCP endpoint is achievable. The cost is a different hosting story
than "front the existing Runtime."

**Recommendation: proceed with the Runtime target** (matches the adopted decision, minimal
change, keeps §8/§10) **and record MCP-target as the fallback** if DP-7 rules out
interceptors or if per-tool Cedar policy later becomes a hard requirement. Note the two are
mutually exclusive on a single gateway because of the protocol-type constraint in F-7.

---

## Revised decision-point status

| DP | Status |
|---|---|
| DP-1 claims propagation | **RESOLVED** — interceptor injects `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`; §8 reads those (F-8) |
| DP-2 bypass policy vs developer path | **OPEN** — unchanged; decide before writing the resource policy |
| DP-3 tool naming | **RESOLVED** — no renaming; §10 survives (F-7) |
| DP-4 gateway role trust hardening | **OPEN** — confirmed still required (F-12) |
| DP-5 spec disposition | **OPEN** — new spec still recommended; scope is now smaller than feared, since §8/§10 largely survive |
| DP-6 gateway cost | **OPEN** — add interceptor Lambda invocations per MCP call to the estimate |
| **DP-7 buffered vs streaming** | **OPEN / BLOCKING** — gates the whole DP-1 mechanism (F-10) |
| **DP-8 Runtime vs MCP target** | **OPEN** — architecture fork; recommendation is Runtime target with MCP target as fallback (DP-8 table) |

## Revised next actions

1. **Answer DP-7 first.** If interceptors cannot run against our streamable-http server,
   DP-1's resolution collapses and DP-8 likely flips to MCP target. Everything else is
   downstream of this.
2. Decide DP-8 once DP-7 is known.
3. Decide DP-2 before any resource-based policy is written.
4. Then create the follow-on spec (DP-5), carrying forward §3–§6 and §10, and — now
   supported by F-9(a) — most of §8 with only the header names changed.
5. Re-scope Task 0 to verify JWT-in / SigV4-out **through a Gateway**, asserting the
   injected custom headers actually arrive at the container.

## Additional sources (Part 2)

- [Amazon Bedrock AgentCore Runtime targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html)
- [Header propagation with Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-headers.html)
- [Types of interceptors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-types.html)
- [Using interceptors with Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html)
- [Configure AgentCore Gateway VPC Egress for Gateway Targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-vpc-egress.html)

*AWS documentation content was rephrased for compliance with licensing restrictions; direct quotations are kept short and attributed inline.*


---

# Part 3 — DP-7 empirically narrowed (2026-08-06)

## Erratum against Part 2

Part 2 (F-10) stated that neither `json_response` nor `stateless_http` was set in
`mcp_server_python/src/`. **The `stateless_http` half of that was wrong.** The grep behind
it was truncated by `head -20` and never reached the relevant lines. Corrected position
below. Only `json_response` is genuinely absent.

## F-14. `stateless_http` is already set — and is mandatory for AgentCore

`mcp_server_python/src/mcp_server.py` (lines ~399–418) already passes
`stateless_http=stateless` to `mcp.run()`, defaulting to **true** via the
`MCP_STATELESS_HTTP` env var. The in-code comment documents why, and it is worth preserving
as institutional knowledge:

- AgentCore generates its own `Mcp-Session-Id` per request and expects the server to accept
  it rather than mint one.
- Stateful mode rejects the platform-supplied ID with **HTTP 400**, which AgentCore
  surfaces to the client as a 500-class runtime error.
- Load balancing and microVM affinity are handled by the platform, so stateless is correct
  server-side.

**Do not change this.** `MCP_STATELESS_HTTP=false` exists only for local multi-turn
elicitation/sampling development.

Note that `stateless_http` and `json_response` are **orthogonal**. Stateless controls
session handling; `json_response` controls response framing. Setting the former does not
avoid SSE.

## F-15. `json_response` is supported by the pinned FastMCP, and is an env-var flip

Verified against the actually pinned version (`fastmcp==3.2.4`,
`mcp_server_python/pyproject.toml:20`) by installing it and introspecting:

- `FastMCP.run(transport=None, show_banner=None, **transport_kwargs)` forwards to
  `run_async`, which forwards to `run_http_async`.
- `run_http_async(...)` accepts **`json_response: bool | None = None`** alongside
  `stateless_http: bool | None = None`. `http_app(...)` accepts it too.
- `fastmcp.settings.Settings` defaults: **`json_response = False`**,
  `stateless_http = False`, `streamable_http_path = "/mcp"`.
- FastMCP's own guidance for the setting names the env var **`FASTMCP_JSON_RESPONSE`** as an
  alternative to passing the kwarg.

**Consequence: the fix requires no code change.** Setting `FASTMCP_JSON_RESPONSE=true` in
the AgentCore Runtime container environment is sufficient. Adding an explicit
`json_response=` kwarg to `mcp.run()` remains available if we prefer it pinned in code
rather than in environment config — recommend the kwarg with an env override, mirroring how
`stateless_http` is already handled, so the behavior is not silently reconfigurable.

## F-16. Empirical confirmation that this actually removes SSE framing

Ran two real FastMCP 3.2.4 streamable-http servers on loopback and issued an MCP
`initialize` with `Accept: application/json, text/event-stream`:

| `json_response` | Response `Content-Type` | First bytes |
|---|---|---|
| `False` (today's effective default) | `text/event-stream` | `event: message\r\ndata: {"jsonrpc":"2.0",...` |
| `True` | `application/json` | `{"jsonrpc":"2.0","id":1,"result":{...` |

This confirms both halves of the concern:

1. **As deployed today the server emits SSE**, which is precisely the mode in which
   AgentCore documents interceptors as unsupported for HTTP/Runtime targets. DP-7 was a
   real risk, not a theoretical one.
2. **The mitigation works and is cheap** — one setting flips the wire format to plain
   `application/json`.

This is also consistent with the MCP specification itself, which states a server answers
each request with either a single JSON object or an SSE stream scoped to that request —
so single-JSON is spec-compliant, not a degradation.

## Revised DP-7 status

**DP-7 is now half-resolved and no longer blocking design work.**

- **Server side: RESOLVED.** We can serve plain `application/json` via
  `FASTMCP_JSON_RESPONSE=true` (or an explicit kwarg), with no code restructuring and no
  change to the mandatory `stateless_http=True`.
- **AWS side: still OPEN, and only testable live.** Do buffered-mode REQUEST interceptors
  actually fire for an MCP-protocol AgentCore Runtime target once the response is
  `application/json`? The docs say interceptors are unsupported "in streaming mode" without
  defining the trigger precisely — it may key on the target's response framing, on
  gateway-level response-streaming configuration, or on both.

**Costs to weigh when confirming:** disabling SSE forfeits incremental
`notifications/progress` delivery and multi-turn elicitation/sampling over the stream. For
the CI and HPC consumer classes in this spec — discrete `tools/call` request/response — that
is very likely acceptable. It would matter for interactive agent use.

**Residual risk if the AWS-side answer is negative:** DP-8 flips to the MCP-target
architecture, which uses the `mcp` interceptor payload (parsed JSON-RPC) rather than the
`http` payload, and does not carry the buffered-only restriction.

## Additional sources (Part 3)

- [MCP specification — Streamable HTTP transport](https://modelcontextprotocol.io/specification/draft/basic/transports/streamable-http)
- `fastmcp==3.2.4` package introspection (`FastMCP.run_http_async`, `fastmcp.settings.Settings`)
